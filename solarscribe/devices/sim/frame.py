############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices sim frame module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Frames and deterministic test patterns for the simulator (ADR-005).
#
# The camera simulator is a first-class backend, so its frames must satisfy the
# same contract as a real SDK frame: an owned, C-contiguous buffer, a sequence
# number and a timestamp taken on receipt. The pattern is a pure function of the
# sequence, so two runs against the same simulator produce identical pixels and
# the SHG tests can assert exact numbers.
#
# Why a pattern with a moving vertical marker: a test that receives frames needs
# a cheap way to tell them apart. The marker shifts one pixel per frame, the
# spectral band stays put, and the horizontal ramp models the dispersion axis.
# None of it is science: it is a fixture with known properties.
#
# The "solar" pattern is the exception that IS meant to be physical enough for
# the SHG engine. It models what the slit sees: the long frame axis (x) is the
# slit image (north-south), the short axis (y) is the dispersion, and the
# illuminated strip along x is the chord of the solar disk at the current RA.
# The chord length changes as the mount scans in RA (leading/trailing limb) and
# its centre shifts along x with the Dec error (left/right imbalance and the
# centroid that centring measures). The spectral lines along y give the on-disk
# standard deviation that the limb detector needs; the dark sky round the chord
# gives the low baseline. It is deterministic: a fixed seed makes the sensor
# noise, and every frame is a pure function of the mount position.

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

import numpy as np

from solarscribe.devices.abc import ROI

__all__ = ["PATTERNS", "SimFrame", "SolarPattern", "make_pattern",
           "make_solar_pattern"]

# Patterns the simulator can emit. "test" is the default; "ramp" and "flat" are
# there for tests that need a mathematically simple image. "solar" is the
# physical one described above.
PATTERNS = ("test", "ramp", "flat", "solar")

# The static part of a pattern (ramp + spectral band) depends only on the size,
# bit depth and ROI offset, not on the frame number. Recomputing the Gaussian
# with exp() on every frame costs more than the whole capture pipeline at the
# 3480x248 reference ROI (measured: the simulator alone fell to ~117 fps, under
# the 120 budget before the engine even saw a frame). Caching the base and
# stamping only the one-column marker brings the source back above the target.
# The cache is small and bounded: a handful of ROI sizes, never a leak.
_BASE_CACHE: dict[tuple, np.ndarray] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_ENTRIES = 8

# Solar pattern: the sensor noise and the line profile are fixed for a given
# geometry and seed, so they are generated once and reused. The chord itself
# changes every frame and is cheap to apply to the cached profile.
_NOISE_CACHE: dict[tuple, np.ndarray] = {}
_SPECTRUM_CACHE: dict[tuple, np.ndarray] = {}

# Fraunhofer-like absorption lines as (position in the band, depth, half width
# in pixels). The exact lines are not a spectrum atlas: they only need to be
# deep and narrow enough to give an on-disk std well above the limb detector's
# 500 ADU floor and to look like a dispersed solar spectrum in the viewer.
_SPECTRAL_LINES = (
    (0.18, 0.30, 2.0),
    (0.31, 0.38, 2.4),
    (0.45, 0.22, 1.8),
    (0.59, 0.42, 3.0),
    (0.72, 0.30, 2.2),
    (0.85, 0.20, 1.6),
)

# One hour of RA is 15 degrees = 54000 arcsec of coordinate.
_ARCSEC_PER_RA_HOUR = 54000.0


@dataclass(frozen=True)
class SolarPattern:
    # What the "solar" pattern simulates and the knobs that change it.
    #
    # The defaults are the reference setup of the MVP: the Touptek G3M678M at
    # 3480x248, 16 bit, a 1920" solar disk and 0.5778"/px along the slit (the
    # default focal length and pixel size of the SHG-700). `band_y` and
    # `band_height` place the useful spectrum inside the 248 rows; the frame
    # outside it is dark sky, which is exactly what the limb detector needs.
    #
    # seed makes the sensor noise deterministic. Changing it changes only the
    # noise, never the geometry or the lines.
    #
    # The geometry is expressed in FRAME pixels and assumes the full reference
    # strip (the SHG workflow captures that strip). A hardware sub-ROI would
    # need the sensor offset added to the chord centre; that is not modelled
    # because the scan never uses a sub-ROI as the slit image.
    seed: int = 20261106
    sun_ra_hours: float = 12.0
    sun_dec_deg: float = 0.0
    solar_diameter_arcsec: float = 1920.0
    slit_arcsec_px: float = 0.5778
    band_y: int = 40
    band_height: int = 160
    peak_fraction: float = 0.55       # continuum peak as a fraction of full scale
    exposure_reference_us: float = 1000.0
    noise_adu: float = 20.0           # fixed-pattern sensor noise, ADU
    limb_darkening: float = 0.55      # edge / centre brightness ratio at the limb


# @args: width, height - frame size in pixels
#        x0, y0 - sensor offset of the ROI; kept in the cache key so a future
#                 ROI-dependent pattern cannot reuse another offset's image
#        sequence - frame number; it moves the marker and makes the frame unique
#        bit_depth - 8 or 16, which fixes the full-scale value
#        kind - one of PATTERNS
# @return: a C-contiguous uint8 or uint16 array with the test pattern
def make_pattern(
    width: int,
    height: int,
    x0: int = 0,
    y0: int = 0,
    sequence: int = 0,
    bit_depth: int = 16,
    kind: str = "test",
) -> np.ndarray:
    if kind not in PATTERNS:
        raise ValueError(f"unknown sim pattern {kind!r}")
    if bit_depth == 8:
        dtype, full = np.uint8, 255.0
    elif bit_depth == 16:
        dtype, full = np.uint16, 65535.0
    else:
        raise ValueError("bit depth must be 8 or 16")

    if kind == "solar":
        # Direct callers get the default sky (slit at the disk centre); the
        # camera passes the real mount position through make_solar_pattern.
        solar = SolarPattern()
        return make_solar_pattern(
            width, height,
            slit_ra_hours=solar.sun_ra_hours,
            slit_dec_deg=solar.sun_dec_deg,
            exposure_us=solar.exposure_reference_us,
            solar=solar, bit_depth=bit_depth,
        )

    if kind == "flat":
        return np.full((height, width), int(0.25 * full), dtype=dtype)

    # The static image is computed once per geometry and then copied. The copy
    # is a memcpy of the frame (1.7 MB at the reference ROI), far cheaper than
    # the exp() and the broadcast over 863k pixels on every frame.
    base = _cached_base(width, height, int(y0), bit_depth, kind)
    frame = base.copy()

    if kind == "test":
        # Moving marker: one column, one pixel per frame. It is the cheap
        # fingerprint a test uses to prove frames arrive in order. Only this
        # column changes, so the rest of the frame stays a memcpy.
        marker = int(sequence) % max(1, width)
        column = frame[:, marker].astype(np.int32) + int(0.20 * full)
        np.clip(column, 0, int(full), out=column)
        frame[:, marker] = column.astype(dtype)
    return frame


# @args: width, height - frame size
#        y0 - sensor row of the ROI, so a lower strip sees the band elsewhere
#        bit_depth - 8 or 16
#        kind - "test" or "ramp"
# @return: the static base pattern (ramp plus band), shared read-only
def _cached_base(width: int, height: int, y0: int, bit_depth: int,
                 kind: str) -> np.ndarray:
    key = (width, height, y0, bit_depth, kind)
    with _CACHE_LOCK:
        cached = _BASE_CACHE.get(key)
        if cached is not None:
            return cached

    dtype, full = (np.uint8, 255.0) if bit_depth == 8 else (np.uint16, 65535.0)
    # Local coordinates: the pattern is generated for the ROI, not the sensor.
    x = np.arange(width, dtype=np.float32)[None, :]
    y = np.arange(height, dtype=np.float32)[:, None] + float(y0)

    # Dispersion ramp: dim on the left, brighter to the right. This mirrors the
    # continuum gradient of a real spectrum closely enough to exercise stats.
    data = full * (0.10 + 0.55 * x / max(1.0, float(width)))
    if kind == "test":
        # Spectral band: a Gaussian strip across the whole width. Its height and
        # position are fixed, so the band is a stable reference for cut_roi.
        band_y = 0.45 * float(height) + 0.0 * y0
        sigma = max(1.0, 0.06 * float(height))
        data = data + full * 0.30 * np.exp(-0.5 * ((y - band_y) / sigma) ** 2)

    base = np.clip(data, 0.0, full).astype(dtype)
    with _CACHE_LOCK:
        if len(_BASE_CACHE) >= _CACHE_ENTRIES:
            _BASE_CACHE.clear()
        _BASE_CACHE[key] = base
    return base


# @args: width, height - frame size in pixels
#        slit_ra_hours, slit_dec_deg - where the telescope (the slit) points
#        exposure_us - current exposure, which scales the signal linearly
#        solar - the SolarPattern that fixes the sun, optics and seed
#        bit_depth - 8 or 16 (16 is the reference SER contract)
# @return: a C-contiguous uint8/uint16 frame on the devices.Frame contract
# Physics in one paragraph: the slit is the long axis x (north-south) and the
# grating disperses along y. At a sky offset q from the disk centre the slit
# sees a chord of length 2*sqrt(R^2 - q^2); the chord maps to x through the
# slit plate, and its centre shifts along x by the Dec error. Inside the chord
# the light is the dispersed spectrum (continuum envelope times absorption
# lines) attenuated by limb darkening towards the chord edges. Outside it there
# is only fixed sensor noise, so the frame standard deviation collapses there:
# that is the signal the SHG limb detector watches.
def make_solar_pattern(
    width: int,
    height: int,
    *,
    slit_ra_hours: float,
    slit_dec_deg: float,
    exposure_us: float,
    solar: SolarPattern | None = None,
    bit_depth: int = 16,
) -> np.ndarray:
    solar = solar or SolarPattern()
    if bit_depth == 8:
        dtype, full = np.uint8, 255.0
    elif bit_depth == 16:
        dtype, full = np.uint16, 65535.0
    else:
        raise ValueError("bit depth must be 8 or 16")

    # Start from the fixed sensor noise. It is the same every frame, so the
    # kind of temporal flicker that would make a test non-deterministic is not
    # introduced; a real camera would have it, and the limb detector tolerates
    # it because the on-disk signal is orders of magnitude larger.
    frame = _solar_noise(height, width, solar.seed) * float(solar.noise_adu)

    # East-west offset of the slit from the disk centre, in sky arcsec. One
    # hour of RA is 54000 arcsec of coordinate; the sky distance is that times
    # cos(Dec), the same 1/cos(Dec) correction the scan uses.
    q_arcsec = (
        (float(slit_ra_hours) - solar.sun_ra_hours)
        * _ARCSEC_PER_RA_HOUR
        * math.cos(math.radians(solar.sun_dec_deg))
    )
    radius_px = max(
        1e-6, 0.5 * float(solar.solar_diameter_arcsec) / solar.slit_arcsec_px,
    )
    q_px = q_arcsec / solar.slit_arcsec_px

    if abs(q_px) < radius_px:
        # Half chord of the disk at this RA. At the limb it goes to zero, which
        # is what makes the on-disk standard deviation collapse there.
        half_chord = math.sqrt(radius_px * radius_px - q_px * q_px)
        # Dec error: the Sun north of the slit (sun_dec > slit_dec) puts the
        # illuminated chord north, which is +x in the shg convention.
        dec_offset_px = (
            (solar.sun_dec_deg - float(slit_dec_deg)) * 3600.0
            / solar.slit_arcsec_px
        )
        center_x = width / 2.0 + dec_offset_px
        x0 = max(0, int(math.ceil(center_x - half_chord)))
        x1 = min(width, int(math.floor(center_x + half_chord)) + 1)
        if x1 > x0:
            spectrum = _solar_spectrum(height, solar)
            dx = np.arange(x0, x1, dtype=np.float32) + 0.5 - center_x
            # Linear limb darkening: the centre of the disk is brighter than
            # the edges, so shifting the chord changes the left/right means
            # and moves the intensity centroid that Dec centring measures.
            ratio = np.clip(np.abs(dx) / half_chord, 0.0, 1.0)
            limb = 1.0 - solar.limb_darkening * ratio
            exposure_scale = max(
                0.0,
                min(4.0, float(exposure_us) / solar.exposure_reference_us),
            )
            scale = solar.peak_fraction * full * exposure_scale
            frame[:, x0:x1] += spectrum[:, None] * limb[None, :] * scale

    return np.clip(frame, 0.0, full).astype(dtype)


# @args: height - frame rows; solar - the pattern parameters
# @return: the normalized spectrum along the dispersion axis, shape (height,)
# The continuum is a Gaussian envelope centred in the band; the absorption
# lines are the narrow dips. The envelope makes the spectrum fade at the band
# edges, so the frame does not depend on a hard band boundary.
def _solar_spectrum(height: int, solar: SolarPattern) -> np.ndarray:
    key = (height, solar.band_y, solar.band_height)
    with _CACHE_LOCK:
        cached = _SPECTRUM_CACHE.get(key)
        if cached is not None:
            return cached

    y = np.arange(height, dtype=np.float32)
    center = solar.band_y + solar.band_height / 2.0
    sigma = max(1.0, solar.band_height / 3.0)
    profile = np.exp(-0.5 * ((y - center) / sigma) ** 2)
    for position, depth, half_width in _SPECTRAL_LINES:
        line_y = solar.band_y + position * solar.band_height
        profile -= depth * np.exp(
            -0.5 * ((y - line_y) / max(0.5, half_width)) ** 2,
        )
    profile = np.clip(profile, 0.0, 1.0).astype(np.float32)

    with _CACHE_LOCK:
        if len(_SPECTRUM_CACHE) >= _CACHE_ENTRIES:
            _SPECTRUM_CACHE.clear()
        _SPECTRUM_CACHE[key] = profile
    return profile


# @args: height, width - frame size; seed - fixed noise seed
# @return: a unit-standard-deviation float32 noise field, shared read-only
def _solar_noise(height: int, width: int, seed: int) -> np.ndarray:
    key = (height, width, int(seed))
    with _CACHE_LOCK:
        cached = _NOISE_CACHE.get(key)
        if cached is not None:
            return cached
    noise = np.random.default_rng(int(seed)).standard_normal(
        (height, width), dtype=np.float32,
    )
    with _CACHE_LOCK:
        if len(_NOISE_CACHE) >= 4:
            _NOISE_CACHE.clear()
        _NOISE_CACHE[key] = noise
    return noise


class SimFrame:
    # One frame produced by the simulator. It mirrors the contract in
    # devices/abc.py, including the copy-on-cut rule that protects numpy's
    # frombuffer from row strides.

    # @args: array - 2-D C-contiguous uint8/uint16 pixels
    #        roi - SENSOR ROI the frame was captured from
    #        sequence - backend counter
    #        timestamp - seconds, taken on receipt
    def __init__(
        self,
        array: np.ndarray,
        roi: ROI,
        sequence: int,
        timestamp: float | None = None,
    ) -> None:
        self._array = np.ascontiguousarray(array)
        self.data = memoryview(self._array)
        self.height, self.width = self._array.shape
        self.dtype = self._array.dtype
        self.roi = roi
        self.sequence = sequence
        self.timestamp = time.monotonic() if timestamp is None else timestamp
        self._stats_cache: tuple[float, float] | None = None

    # @args: none
    # @return: mean and standard deviation of the whole frame
    def stats(self):
        if self._stats_cache is None:
            # Computed once: the engine calls stats() on every frame and a test
            # may call it again; the second call must stay free.
            self._stats_cache = (
                float(self._array.mean()),
                float(self._array.std()),
            )
        mean, std = self._stats_cache
        # A tiny local value type keeps the FrameStats protocol satisfied
        # without dragging a module-level class into the contract surface.
        return _Stats(mean, std)

    # @args: roi - sub-region in FRAME pixels, (0, 0) at the frame's top-left
    # @return: the sub-region as a frame; full-width strips stay zero-copy
    def cut_roi(self, roi: ROI):
        x, y, width, height = roi
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError(f"invalid frame ROI {roi!r}")
        if x + width > self.width or y + height > self.height:
            raise ValueError(f"frame ROI {roi!r} outside {self.width}x{self.height}")
        if x == 0 and width == self.width:
            sub = self._array[y:y + height, :]
        else:
            # ascontiguousarray is what turns a strided sub-rectangle into a
            # buffer np.frombuffer can read; it is a no-op on the strip above.
            sub = np.ascontiguousarray(self._array[y:y + height, x:x + width])
        return SimFrame(sub, self.roi, self.sequence, self.timestamp)


class _Stats:
    # @args: mean, std - the two numbers of the FrameStats contract
    # @return: none
    def __init__(self, mean: float, std: float) -> None:
        self.mean = mean
        self.std = std
