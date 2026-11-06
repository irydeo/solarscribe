############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg centering module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Dec centring of the Sun on the slit (ADR-006).
#
# Two stages, because the signal is honest only in different regimes:
#
# 1. Coarse, by histogram and extent. A hill-climb in Dec that maximises a high
#    percentile of the frame (the illuminated spectral continuum). It is fast
#    and works on a live frame without a scan. It CANNOT resolve the centre:
#    the illuminated extent along the slit is the chord of the disk,
#    L = 2*sqrt(R^2 - q^2), whose derivative is zero at q = 0. Near the centre
#    the score is flat (the dead zone) and the climb stops at its edge.
#
# 2. Fine, by symmetry or chord. Symmetry is valid when the disk fits along the
#    slit: the intensity centroid along the slit is the disk centre, so its
#    offset from the slit centre is the Dec error directly. When the disk does
#    not fit, the slit clips the disk and symmetry is lost; the chord method
#    measures the on-disk span during a short sweep and inverts
#    L = 2*sqrt(R^2 - e^2) with e = max(0, |q| - S/2). The chord is symmetric in
#    q, so a +Dec probe resolves the sign, and the method deliberately leaves
#    the dead zone |q| < S/2 before trusting the measurement.
#
# The dead zone is a geometric limit, not a tuning problem. Every result
# carries it so the UI can say "centred within +/- S/2" instead of pretending
# to a precision it does not have.
#
# External anchors:
#   - the chord L = 2*sqrt(R^2 - e^2), the same geometry as ADR-006 and
#     geometry.chord_arcsec;
#   - the centroid is the first moment of the intensity distribution;
#   - the normalized imbalance (L-R)/(L+R) cancels the exposure, which is why
#     the prototype's left/right loop works at any gain;
#   - the +Dec probe sign rule is the prototype's center_dec_chord.

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

from solarscribe.devices.abc import ROI, Axis, Frame, Mount

from .abc import CenteringResult, CenteringStatus, DecCenterMethod, FrameSource
from .analysis import (
    bright_fraction,
    column_means,
    percentile_value,
    symmetry_centroid_offset_px,
)
from .geometry import dead_zone_arcsec, ra_diff_arcsec
from .limb import LIMB_STDDEV_MIN, ON_DISK_STDDEV, LimbDetector, LimbState

__all__ = [
    "CenterResult",
    "SunCenteringImpl",
    "chord_center",
    "chord_offset_from_arcsec",
    "coarse_center",
    "coarse_score",
    "measure_symmetry_offset_arcsec",
    "symmetry_center",
]

# Prototype defaults (nightscribe-scan section 4 and 5).
DEC_CENTER_TOLERANCE = 0.03       # (L-R)/(L+R), the legacy loop
DEC_MAX_CORRECTIONS = 8
MOSAIC_CENTER_MAX_ITER = 3
MOSAIC_CENTER_RESIDUAL_ARCSEC = 300.0
MOSAIC_MIN_CHORD_FRACTION = 0.15  # of the solar diameter

# Probe and reposition constants. They are the prototype's SIDEREAL,
# MOSAIC_CHORD_SPEED and RETURN_MULTIPLIER; the chord sweep and the rewind use
# them exactly as nightscribe-scan does.
SIDEREAL_ARCSEC_S = 15.04
CHORD_SPEED_MULTIPLIER = 16.0
RETURN_MULTIPLIER = 32.0
REWIND_MARGIN_ARCSEC = 600.0
POLL_S = 0.02


class CenterResult:
    # Small value type used by the pure functions. It mirrors the contract's
    # CenteringResult but keeps the centering module independent of the abc
    # import cycle (abc imports devices only, centering imports analysis).
    # @args: ok - the loop converged
    #        dec_offset_arcsec - residual estimate, arcsec
    #        iterations - loops used
    #        dead_zone_arcsec - the unresolvable band, arcsec
    #        reason_code - "" when ok
    def __init__(self, ok: bool, dec_offset_arcsec: float, iterations: int = 0,
                 dead_zone_arcsec_value: float = 0.0,
                 reason_code: str = "") -> None:
        self.ok = ok
        self.dec_offset_arcsec = dec_offset_arcsec
        self.iterations = iterations
        self.dead_zone_arcsec = dead_zone_arcsec_value
        self.reason_code = reason_code

    # @args: none
    # @return: a plain tuple, for the tests and the logs
    def as_tuple(self) -> tuple[bool, float, int, float, str]:
        return (self.ok, self.dec_offset_arcsec, self.iterations,
                self.dead_zone_arcsec, self.reason_code)


# @args: frame - a live frame
#        band - the spectral band in FRAME pixels
#        pct - the cumulative percentile that represents the bright continuum
#        level - fraction of that reference used as the bright threshold
# @return: the fraction of band pixels above the threshold, in [0, 1]
# ADR-006's coarse stage maximises the ILLUMINATED EXTENT, which is the fraction
# of the slit that is lit, not the brightness of the brighest pixels. The high
# percentile (0.995) is the bright continuum level and ignores a few hot pixels;
# half of it still counts the fainter slit ends. The score is dimensionless, so
# the hill-climb does not depend on the exposure. A dark frame has no reference
# and scores 0.
def coarse_score(frame: Frame, band: ROI, pct: float = 0.995,
                 level: float = 0.5) -> float:
    reference = percentile_value(frame, band, pct)
    if reference <= 0:
        return 0.0
    return bright_fraction(frame, band, level * reference)


# @args: probe - function(dec_deg) -> score; it moves the mount and measures
#        start_dec_deg - initial Dec
#        step_arcsec - hill-climb step
#        max_steps - maximum probes
#        tolerance - score improvement below which the climb stops
# @return: CenterResult with the best Dec in dec_offset_arcsec? No: the best
#          Dec is not an offset; see the tuple below.
# The coarse stage returns the best Dec it found, not an offset. The caller
# subtracts the target Dec. The dead zone is reported honestly: the climb stops
# when neither neighbour improves the score, which happens at the edge of the
# flat top.
def coarse_center(probe: Callable[[float], float], start_dec_deg: float,
                  step_arcsec: float, max_steps: int = 12,
                  tolerance: float = 0.0) -> tuple[bool, float, float, int]:
    if step_arcsec <= 0:
        raise ValueError("the step must be positive")
    best_dec = float(start_dec_deg)
    best_score = float(probe(best_dec))
    steps = 0
    for _ in range(max(1, max_steps)):
        up_dec = best_dec + step_arcsec / 3600.0
        down_dec = best_dec - step_arcsec / 3600.0
        up_score = float(probe(up_dec))
        down_score = float(probe(down_dec))
        steps += 2
        if up_score >= down_score and up_score > best_score + tolerance:
            best_dec, best_score = up_dec, up_score
        elif down_score > up_score and down_score > best_score + tolerance:
            best_dec, best_score = down_dec, down_score
        else:
            # Neither neighbour improves: the top is flat here. That is the
            # dead zone of the chord, not a measurement failure.
            return True, best_dec, best_score, steps
    return True, best_dec, best_score, steps


# @args: frame - a live frame
#        band - the spectral band in FRAME pixels
#        slit_arcsec_px - arcseconds per pixel along the slit axis
#        columns - number of column bands for the profile
# @return: the Dec offset in arcsec, positive when the Sun is to the right
#          (north) of the slit centre; None when the frame has no signal
def measure_symmetry_offset_arcsec(frame: Frame, band: ROI,
                                   slit_arcsec_px: float,
                                   columns: int = 64) -> float | None:
    means = column_means(frame, band, columns)
    offset_px = symmetry_centroid_offset_px(means, max(1, band[2] // columns))
    if offset_px is None:
        return None
    return offset_px * slit_arcsec_px


# @args: probe - function(dec_deg) -> measured offset_arcsec at that Dec
#        start_dec_deg - initial Dec
#        tolerance_arcsec - convergence threshold
#        max_iterations - maximum corrections
#        gain - fraction of the measured offset applied per step
# @return: CenterResult; dec_offset_arcsec is the residual offset
# The probe moves the mount to the given Dec and measures the Sun's offset.
# A positive offset means the Sun is north of the slit, so the slit must follow
# it north: dec_new = dec + offset*gain. (The prototype's left/right loop moved
# the opposite way because it learned the sign of MoveAxis(1); the Mount
# contract fixes a positive Dec rate as increasing Dec, so here the sign is
# explicit.) gain < 1 damps a noisy measurement; 1.0 is the prototype's
# proportional loop without the time-based nudge.
def symmetry_center(probe: Callable[[float], float | None],
                    start_dec_deg: float,
                    tolerance_arcsec: float = 1.0,
                    max_iterations: int = DEC_MAX_CORRECTIONS,
                    gain: float = 1.0) -> CenterResult:
    dec = float(start_dec_deg)
    offset: float | None = None
    for iteration in range(1, max(1, max_iterations) + 1):
        offset = probe(dec)
        if offset is None:
            return CenterResult(False, 0.0, iteration, 0.0, "no_limb")
        if abs(offset) <= tolerance_arcsec:
            # The symmetry method has no dead zone when the disk fits the slit:
            # the centroid moves linearly with q. The dead zone is 0.
            return CenterResult(True, offset, iteration, 0.0, "")
        dec += gain * offset / 3600.0
    assert offset is not None
    return CenterResult(False, offset, max_iterations, 0.0, "max_iterations")


# @args: chord_arcsec_value - measured chord
#        slit_arcsec - effective slit length
#        solar_diameter_arcsec - apparent diameter
# @return: |offset| and nearest edge distance, arcsec
# The inverse chord. Kept here so the centring logic has no geometry import
# loop and the formula is visible next to its use.
def chord_offset_from_arcsec(chord_arcsec_value: float, slit_arcsec: float,
                             solar_diameter_arcsec: float) -> tuple[float, float]:
    radius = solar_diameter_arcsec / 2.0
    half = min(max(chord_arcsec_value, 0.0) / 2.0, radius)
    edge = math.sqrt(max(radius * radius - half * half, 0.0))
    return edge + max(slit_arcsec, 0.0) / 2.0, edge


# @args: measure_chord - function() -> chord arcsec or None; it sweeps the disk
#                        and leaves the mount just before the leading limb
#        move_dec - function(delta_arcsec): relative Dec move
#        current_dec - function() -> current Dec, degrees
#        solar_diameter_arcsec - apparent diameter
#        slit_arcsec - effective slit length
#        trust_arcsec - minimum nearest-edge distance to trust the chord
#        step_arcsec - walk step out of the dead zone
#        max_iterations - correction rounds
#        min_chord_arcsec - below this the chord is not a usable disk
#        rewind - optional function() that puts the mount back before the disk
#                 after a probe lost it (the prototype's rewind_before_disk)
# @return: CenterResult; dead_zone_arcsec is slit/2
# Faithful port of the prototype's center_dec_chord:
#   1. If the nearest slit edge e = sqrt(R^2 - (L/2)^2) is below trust, the
#      slit is inside the dead zone: walk +Dec in steps until e >= trust. The
#      step is shorter than trust, so the walk stops before the limb.
#   2. Outside, q_abs = e + S/2. A short +Dec probe tells the side: if the
#      chord shrinks (e grows) the probe went away from the centre, so the
#      current position is north (q > 0); if it grows, the current position is
#      south (q < 0).
#   3. Move to dec0 - q and repeat. Once a correction has been applied, a
#      residual e < trust is chord noise, not dead-zone width.
# If the probe loses the disk, the slit was north of centre (q > 0) and the
# mount may be past the trailing limb; the next measurement must rewind.
def chord_center(measure_chord: Callable[[], float | None],
                 move_dec: Callable[[float], None],
                 current_dec: Callable[[], float],
                 solar_diameter_arcsec: float,
                 slit_arcsec: float,
                 trust_arcsec: float = 0.0,
                 step_arcsec: float = 0.0,
                 max_iterations: int = MOSAIC_CENTER_MAX_ITER,
                 min_chord_arcsec: float = 0.0,
                 rewind: Callable[[], None] | None = None) -> CenterResult:
    radius = solar_diameter_arcsec / 2.0
    trust = trust_arcsec if trust_arcsec > 0 else 0.5 * radius
    step = step_arcsec if step_arcsec > 0 else 0.3 * radius
    min_chord = (min_chord_arcsec if min_chord_arcsec > 0
                 else MOSAIC_MIN_CHORD_FRACTION * solar_diameter_arcsec)
    zone = dead_zone_arcsec(slit_arcsec)

    chord = measure_chord()
    if chord is None or chord < min_chord:
        return CenterResult(False, zone, 0, zone, "no_limb")
    dec0 = current_dec()
    _q_abs, edge = chord_offset_from_arcsec(chord, slit_arcsec,
                                            solar_diameter_arcsec)

    # 1. Leave the dead zone. From the centre the north edge of the dead zone
    # is S/2+trust away; starting at the south edge doubles that, so S+2*trust
    # covers both sides with two extra steps of margin.
    max_walk = int(math.ceil((slit_arcsec + 2.0 * trust) / step)) + 2
    walked = 0
    while edge < trust:
        if walked >= max_walk:
            return CenterResult(False, zone, walked, zone, "dead_zone")
        move_dec(step)
        walked += 1
        chord = measure_chord()
        if chord is None or chord < min_chord:
            return CenterResult(False, zone, walked, zone, "no_limb")
        dec0 = current_dec()
        _q_abs, edge = chord_offset_from_arcsec(chord, slit_arcsec,
                                                solar_diameter_arcsec)

    corrected = False
    last_edge = edge
    recovery = False
    for iteration in range(1, max(1, max_iterations) + 1):
        if iteration > 1:
            # A failed probe may have left the mount past the trailing limb.
            # The caller can pass a rewind() that puts it back before the disk;
            # without one the next measurement may simply fail, which is why
            # the engine supplies it.
            if recovery and rewind is not None:
                rewind()
            chord = measure_chord()
            if chord is None or chord < min_chord:
                return CenterResult(False, last_edge, iteration, zone, "no_limb")
            dec0 = current_dec()
            _q_abs, edge = chord_offset_from_arcsec(chord, slit_arcsec,
                                                    solar_diameter_arcsec)
            last_edge = edge
            recovery = False

        if corrected and edge < trust:
            # The correction came from a trusted (outside-dead-zone) chord, so
            # this residual is measurement noise, not dead-zone width.
            return CenterResult(True, 0.0, iteration, zone, "")
        if edge < trust:
            return CenterResult(False, edge, iteration, zone, "dead_zone")

        q_abs = edge + slit_arcsec / 2.0
        probe = min(0.3 * radius, max(0.15 * radius, 0.6 * (radius - edge)))
        move_dec(probe)
        probed = measure_chord()
        if probed is None:
            # The probe left the disk, so the slit was north of centre. The
            # mount is now past the trailing limb; the next measure must rewind.
            q = q_abs
            recovery = True
        else:
            _q2, edge2 = chord_offset_from_arcsec(probed, slit_arcsec,
                                                 solar_diameter_arcsec)
            q = q_abs if edge2 > edge else -q_abs
        # From dec0+probe to dec0-q. The move is relative to the current
        # position, so it is -q-probe. The +Dec approach used by mosaic rows is
        # a separate concern: here the loop must simply reach the target.
        move_dec(-q - probe)
        corrected = True

    # The last correction has not been measured yet; verify it once.
    if recovery and rewind is not None:
        rewind()
    chord = measure_chord()
    if chord is not None and chord >= min_chord:
        _q, edge = chord_offset_from_arcsec(chord, slit_arcsec,
                                            solar_diameter_arcsec)
        last_edge = edge
        if edge < trust:
            return CenterResult(True, 0.0, max_iterations, zone, "")
    return CenterResult(False, last_edge, max_iterations, zone,
                        "dead_zone" if last_edge < trust else "max_iterations")


# Prototype names, kept as aliases so the parity note and a reader coming from
# nightscribe-scan find them.
center_dec = symmetry_center
center_dec_chord = chord_center
center_dec_coarse = coarse_center


class SunCenteringImpl:
    # The concrete Find-the-Sun service (shg/abc.py: SunCenteringService).
    #
    # It composes the two stages exactly as ADR-006 describes, so the UI does
    # not have to invent the order or the dead-zone reporting:
    #   1. coarse: a Dec hill-climb on the illuminated fraction of the band,
    #      cheap, on the live frame, no sweep;
    #   2. fine: symmetry when the disk fits along the slit, chord otherwise.
    #
    # It owns no Qt and no driver: it moves the mount through `Mount` and reads
    # frames from the `FrameSource` port. The constructor is explicit so the UI
    # copies the band and the slit geometry from the ROI step (shg cannot import
    # capture's RoiModel).
    #
    # `chord_measure` and `rewind` are test/advanced seams. In production the
    # class measures the chord with its own RA sweep (`_default_chord_measure`)
    # and rewinds with `_default_rewind`; the unit tests inject a deterministic
    # chord function to pin the dead zone and the reason codes.

    # @args: mount - the mount contract
    #        frames - the FrameSource port (the class registers on_frame)
    #        band - the spectral band in FRAME pixels
    #        slit_arcsec - effective slit length on the sky
    #        solar_diameter_arcsec - apparent diameter for the chord geometry
    #        slit_arcsec_px - arcsec per pixel along the slit; 0 estimates it
    #                         from slit_arcsec / band width
    #        method - AUTO, SYMMETRY or CHORD; AUTO picks symmetry when
    #                 slit_arcsec >= solar_diameter_arcsec
    #        coarse - run the coarse hill-climb first (True; False for a chord
    #                 test or a manually pointed slit)
    #        coarse_step_arcsec - hill-climb step; 0 uses 0.3 R
    #        coarse_max_steps - hill-climb probes per direction
    #        coarse_min_score - below this the coarse frame has no contrast
    #        fine_tolerance_arcsec - fine convergence threshold
    #        fine_max_iterations - symmetry corrections
    #        chord_trust_arcsec - nearest-edge distance to trust a chord; 0 = 0.5R
    #        chord_step_arcsec - walk step out of the dead zone; 0 = 0.3R
    #        chord_max_iterations - chord correction rounds
    #        chord_measure - optional function() -> chord or None, for tests
    #        rewind - optional function() that puts the mount back before the
    #                 disk after a lost probe
    #        clock, sleep - injected for the tests
    #        frame_timeout_s - how long to wait for a fresh frame after a move
    #        poll_s - polling interval
    def __init__(self, mount: Mount, frames: FrameSource, *,
                 band: ROI,
                 slit_arcsec: float,
                 solar_diameter_arcsec: float,
                 slit_arcsec_px: float = 0.0,
                 method: DecCenterMethod = DecCenterMethod.AUTO,
                 coarse: bool = True,
                 coarse_step_arcsec: float = 0.0,
                 coarse_max_steps: int = 10,
                 coarse_min_score: float = 0.0,
                 fine_tolerance_arcsec: float = 1.0,
                 fine_max_iterations: int = DEC_MAX_CORRECTIONS,
                 chord_trust_arcsec: float = 0.0,
                 chord_step_arcsec: float = 0.0,
                 chord_max_iterations: int = MOSAIC_CENTER_MAX_ITER,
                 chord_measure: Callable[[], float | None] | None = None,
                 rewind: Callable[[], None] | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep,
                 frame_timeout_s: float = 3.0,
                 poll_s: float = POLL_S) -> None:
        if band[2] <= 0 or band[3] <= 0:
            raise ValueError("the band must have a positive width and height")
        if slit_arcsec <= 0:
            raise ValueError("the slit length must be positive")
        if solar_diameter_arcsec <= 0:
            raise ValueError("the solar diameter must be positive")
        self._mount = mount
        self._band = band
        self._slit_arcsec = float(slit_arcsec)
        self._solar_diameter = float(solar_diameter_arcsec)
        self._slit_arcsec_px = (float(slit_arcsec_px) if slit_arcsec_px > 0
                                else slit_arcsec / float(band[2]))
        self._method = method
        self._coarse = bool(coarse)
        radius = self._solar_diameter / 2.0
        self._coarse_step = (float(coarse_step_arcsec) if coarse_step_arcsec > 0
                             else 0.3 * radius)
        self._coarse_max_steps = max(1, int(coarse_max_steps))
        self._coarse_min_score = float(coarse_min_score)
        self._fine_tolerance = float(fine_tolerance_arcsec)
        self._fine_max_iterations = max(1, int(fine_max_iterations))
        self._chord_trust = float(chord_trust_arcsec)
        self._chord_step = float(chord_step_arcsec)
        self._chord_max_iterations = max(1, int(chord_max_iterations))
        self._chord_measure = chord_measure
        self._rewind = rewind
        self._clock = clock
        self._sleep = sleep
        self._frame_timeout_s = float(frame_timeout_s)
        self._poll_s = float(poll_s)
        self._columns = 64

        self._lock = threading.Lock()
        self._latest_frame: Frame | None = None
        self._latest_std = 0.0
        self._frame_count = 0
        frames.on_frame(self._on_frame)

    # @args: frame - a frame delivered on the capture thread
    # @return: none. Latches the frame and its std, never blocks
    def _on_frame(self, frame: Frame) -> None:
        try:
            std = float(frame.stats().std)
        except Exception:
            std = 0.0
        with self._lock:
            self._latest_frame = frame
            self._latest_std = std
            self._frame_count += 1

    # @return: (latest frame, latest std, frame count), a consistent snapshot
    def _snapshot(self) -> tuple[Frame | None, float, int]:
        with self._lock:
            return self._latest_frame, self._latest_std, self._frame_count

    # @args: after_count - the frame count before the move
    # @return: a frame newer than after_count, or None on timeout
    # A centring measurement must not read the frame cached before the Dec
    # nudge: that frame describes the old position and would make the loop
    # oscillate.
    def _wait_fresh_frame(self, after_count: int) -> Frame | None:
        start = self._clock()
        while self._clock() - start < self._frame_timeout_s:
            frame, _std, count = self._snapshot()
            if frame is not None and count > after_count:
                return frame
            self._sleep(self._poll_s)
        return None

    # @args: target_dec - absolute Dec, degrees
    # @return: none. Closed-loop Dec move with a bounded rate and timeout
    def _move_dec_to(self, target_dec: float) -> None:
        current = self._mount.position()[1]
        delta = (target_dec - current) * 3600.0
        if abs(delta) < 0.5:
            return
        direction = 1.0 if delta > 0 else -1.0
        # Same compromise as the scan engine: fast enough to be usable, slow
        # enough that the 30 ms poll overshoots less than a pixel.
        rate = min(max(5.0, abs(delta) * 2.0), 10.0 * SIDEREAL_ARCSEC_S)
        self._mount.move_axis(Axis.DEC, direction * rate)
        start = self._clock()
        timeout = abs(delta) / rate * 1.5 + 1.0
        while self._clock() - start < timeout:
            current = self._mount.position()[1]
            if (current - target_dec) * direction >= 0:
                break
            self._sleep(0.03)
        self._mount.stop()
        self._sleep(0.1)

    # @args: delta_arcsec - relative Dec move
    # @return: none
    def _move_dec_relative(self, delta_arcsec: float) -> None:
        self._move_dec_to(self._mount.position()[1] + delta_arcsec / 3600.0)

    # @args: none
    # @return: the chosen fine method (AUTO already resolved)
    def _resolved_method(self) -> DecCenterMethod:
        if self._method != DecCenterMethod.AUTO:
            return self._method
        return (DecCenterMethod.SYMMETRY
                if self._slit_arcsec >= self._solar_diameter
                else DecCenterMethod.CHORD)

    # @args: rate - probe rate, arcsec/s
    # @return: the dark std, or None when the backup timed out
    def _ensure_off_disk(self, rate: float) -> float | None:
        _frame, std, _count = self._snapshot()
        if std <= ON_DISK_STDDEV:
            return std
        self._mount.move_axis(Axis.RA, rate)
        start = self._clock()
        while self._clock() - start < 40.0:
            self._sleep(self._poll_s)
            _frame, std, _count = self._snapshot()
            if std < LIMB_STDDEV_MIN:
                self._mount.stop()
                self._sleep(0.2)
                return self._snapshot()[1]
        self._mount.stop()
        return None

    # @args: none
    # @return: none. Slew backwards in RA by more than a disk diameter
    def _default_rewind(self) -> None:
        _ra, dec = self._mount.position()
        span = (self._solar_diameter + REWIND_MARGIN_ARCSEC) / max(
            0.5, math.cos(math.radians(dec)))
        rate = RETURN_MULTIPLIER * SIDEREAL_ARCSEC_S
        self._mount.move_axis(Axis.RA, rate)
        self._sleep(span / rate)
        self._mount.stop()
        self._sleep(0.2)

    # @args: none
    # @return: the on-disk chord at the current Dec, arcsec, or None
    # The production chord sweep: back off the disk, run RA forward at 16x,
    # watch the stddev, time the on-disk interval, convert the coordinate span
    # with cos(Dec) and leave the mount before the leading limb. It is the same
    # physics as the engine's sweep; the unit tests inject a deterministic
    # function instead of driving this one.
    def _default_chord_measure(self) -> float | None:
        before = self._snapshot()[2]
        if self._wait_fresh_frame(before) is None:
            return None
        rate = CHORD_SPEED_MULTIPLIER * SIDEREAL_ARCSEC_S
        dark = self._ensure_off_disk(rate)
        if dark is None:
            return None
        detector = LimbDetector()
        detector.set_dark(dark)
        _ra, dec0 = self._mount.position()
        ra_start = self._mount.position()[0]
        self._mount.move_axis(Axis.RA, -rate)
        start = self._clock()
        ra_end: float | None = None
        on_disk = False
        while self._clock() - start < 120.0:
            self._sleep(self._poll_s)
            state = detector.update(self._snapshot()[1])
            if state == LimbState.ON_DISK:
                on_disk = True
            elif state == LimbState.TRAILING and on_disk:
                ra_end = self._mount.position()[0]
                break
        self._mount.stop()
        if ra_end is None:
            return None
        span = abs(ra_diff_arcsec(ra_end, ra_start))
        return span * math.cos(math.radians(dec0))

    # @args: cb - optional progress callback
    # @return: the contract CenteringResult with the residual and the dead zone
    def center(self, cb: Callable[[CenteringStatus], None] | None = None) -> CenteringResult:
        method = self._resolved_method()
        start_dec = self._mount.position()[1]

        if self._coarse:
            total = max(1, 2 * self._coarse_max_steps)
            counter = [0]

            def coarse_probe(dec_deg: float) -> float:
                before = self._snapshot()[2]
                self._move_dec_to(dec_deg)
                frame = self._wait_fresh_frame(before)
                if frame is None:
                    return 0.0
                score = coarse_score(frame, self._band)
                counter[0] += 1
                if cb is not None:
                    cb(CenteringStatus(
                        phase="coarse",
                        progress=min(0.49, 0.5 * counter[0] / total),
                        score=score,
                    ))
                return score

            _ok, best_dec, best_score, _steps = coarse_center(
                coarse_probe, start_dec, self._coarse_step,
                self._coarse_max_steps)
            if best_score <= self._coarse_min_score and method == DecCenterMethod.SYMMETRY:
                # The coarse frame has no illuminated spectrum and the fine
                # symmetry needs one; a chord sweep is still worth trying.
                return CenteringResult(False, 0.0, method, "low_contrast")
            self._move_dec_to(best_dec)
            if cb is not None:
                cb(CenteringStatus(phase="coarse", progress=0.5,
                                   score=best_score))
        else:
            best_dec = start_dec

        if method == DecCenterMethod.SYMMETRY:
            return self._center_symmetry(best_dec, cb)
        return self._center_chord(cb)

    # @args: start_dec - Dec after the coarse stage
    #        cb - optional progress callback
    # @return: the contract CenteringResult; symmetry has no dead zone
    def _center_symmetry(self, start_dec: float,
                         cb: Callable[[CenteringStatus], None] | None) -> CenteringResult:
        counter = [0]

        def probe(dec_deg: float) -> float | None:
            before = self._snapshot()[2]
            self._move_dec_to(dec_deg)
            frame = self._wait_fresh_frame(before)
            if frame is None:
                return None
            offset = measure_symmetry_offset_arcsec(
                frame, self._band, self._slit_arcsec_px, self._columns)
            counter[0] += 1
            if cb is not None:
                cb(CenteringStatus(
                    phase="fine",
                    progress=min(0.99, 0.5 + 0.5 * counter[0]
                                / self._fine_max_iterations),
                    dec_offset_arcsec=offset,
                ))
            return offset

        result = symmetry_center(probe, start_dec,
                                 tolerance_arcsec=self._fine_tolerance,
                                 max_iterations=self._fine_max_iterations)
        if cb is not None:
            cb(CenteringStatus(phase="fine", progress=1.0,
                               dec_offset_arcsec=result.dec_offset_arcsec))
        return CenteringResult(
            ok=result.ok,
            dec_offset_arcsec=result.dec_offset_arcsec,
            method=DecCenterMethod.SYMMETRY,
            reason_code=result.reason_code,
            dead_zone_arcsec=0.0,
        )

    # @args: cb - optional progress callback
    # @return: the contract CenteringResult; the dead zone is slit/2
    def _center_chord(self, cb: Callable[[CenteringStatus], None] | None) -> CenteringResult:
        measure = self._chord_measure or self._default_chord_measure
        counter = [0]
        budget = max(1, 4 * self._chord_max_iterations)

        def measured() -> float | None:
            chord = measure()
            counter[0] += 1
            if cb is not None:
                cb(CenteringStatus(
                    phase="fine",
                    progress=min(0.99, 0.5 + 0.5 * counter[0] / budget),
                ))
            return chord

        rewind = self._rewind or self._default_rewind
        result = chord_center(
            measured, self._move_dec_relative,
            lambda: self._mount.position()[1],
            self._solar_diameter, self._slit_arcsec,
            trust_arcsec=self._chord_trust,
            step_arcsec=self._chord_step,
            max_iterations=self._chord_max_iterations,
            rewind=rewind,
        )
        if cb is not None:
            cb(CenteringStatus(phase="fine", progress=1.0,
                               dec_offset_arcsec=result.dec_offset_arcsec))
        return CenteringResult(
            ok=result.ok,
            dec_offset_arcsec=result.dec_offset_arcsec,
            method=DecCenterMethod.CHORD,
            reason_code=result.reason_code,
            dead_zone_arcsec=result.dead_zone_arcsec,
        )
