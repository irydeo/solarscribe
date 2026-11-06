############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg limb module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Limb detection by standard deviation.
#
# Why stddev and not mean: the SHG slit projects a spectrum onto the sensor.
# On the solar disk the spectrum carries dark Fraunhofer lines, so the frame
# standard deviation is large (the prototype measured 10000+ at 16 bit). Off
# the disk the frame is sensor noise only, so the standard deviation is small
# (tens to a few hundred). The signal is robust whichever way the spectral axis
# lies and does not need a brightness target (the idea is borrowed from Patrick
# Hsieh's SHGScan and is what nightscribe-scan's find_solar_limb uses).
#
# The threshold is relative to the measured dark baseline, not fixed: gain,
# exposure and hot pixels move the noise floor, and a fixed number would either
# trigger on a noisy dark or miss a clean disk. The prototype requires all
# three of: dark*LIMB_DARK_MULT, dark+300 and LIMB_STDDEV_MIN, whichever is
# largest. Those measured numbers are the external anchor of this module.
#
# The detector is pure: it consumes std values, so it is tested without a
# camera. The engine feeds it from Frame.stats() and decides when to stop.

from __future__ import annotations

from dataclasses import dataclass

from solarscribe.devices.abc import ROI, Frame

from .analysis import region_std, subdivide_roi

__all__ = [
    "LimbDetector",
    "LimbState",
    "column_std_profile",
    "detect_limb_columns",
    "limb_threshold",
]

# Prototype defaults (nightscribe-scan section 3). LIMB_STDDEV_MIN is the
# absolute floor: on-disk stddev is typically 10000+, dark is 20-100.
LIMB_STDDEV_MIN = 500.0
ON_DISK_STDDEV = 2000.0
LIMB_DARK_MULT = 5.0
LIMB_DARK_OFFSET = 300.0

# Fraction of the peak below which the frame counts as off disk while the
# trailing limb leaves the slit (TRAILING_STDDEV_FRACTION = 0.15).
TRAILING_STDDEV_FRACTION = 0.15


class LimbState:
    # Plain string states, not an Enum: the engine publishes them in progress
    # records and the tests compare them without importing an enum.
    UNKNOWN = "unknown"
    DARK = "dark"
    ON_DISK = "on_disk"
    TRAILING = "trailing"


# @args: dark_std - measured standard deviation of the dark sky
#        dark_mult - multiple of the dark baseline
#        dark_offset - absolute margin over the dark baseline
#        floor - absolute floor of the on-disk standard deviation
# @return: the threshold above which the frame counts as on disk
# A noisy dark must not trigger a false limb (mult and offset); a very clean
# dark must not detect a barely lit disk (floor). All three are the prototype's
# rule and its measured values.
def limb_threshold(dark_std: float, dark_mult: float = LIMB_DARK_MULT,
                   dark_offset: float = LIMB_DARK_OFFSET,
                   floor: float = LIMB_STDDEV_MIN) -> float:
    return max(float(dark_std) * dark_mult, float(dark_std) + dark_offset,
               floor)


# @args: frame - a delivered frame
#        roi - the "limb" region in FRAME pixels
#        columns - number of bands along the slit
# @return: one standard deviation per band, left to right
# The spatial profile answers "which part of the slit is on the disk". The
# engine normally uses the whole-frame std over time, but the same physics
# applies per column and the ROI contract lets shg subdivide "limb".
def column_std_profile(frame: Frame, roi: ROI, columns: int) -> list[float]:
    return [region_std(frame, band) for band in subdivide_roi(roi, columns)]


# @args: profile - standard deviations along the slit
#        threshold - on-disk threshold from limb_threshold
#        min_run - bands above the threshold needed to accept a limb
# @return: (first, last) illuminated band indices, or None
# Requiring a run avoids a single hot column being taken for the disk. The
# prototype polls for a jump and then confirms it twice while scanning, which
# is the temporal version of the same guard.
def detect_limb_columns(profile: list[float], threshold: float,
                        min_run: int = 1) -> tuple[int, int] | None:
    needed = max(1, min_run)
    run_start: int | None = None
    best: tuple[int, int] | None = None
    for index, value in enumerate(profile):
        if value > threshold:
            if run_start is None:
                run_start = index
        elif run_start is not None:
            if best is None and index - run_start >= needed:
                best = (run_start, index - 1)
            run_start = None
    if best is None and run_start is not None and len(profile) - run_start >= needed:
        best = (run_start, len(profile) - 1)
    return best


@dataclass
class LimbDetector:
    # Temporal limb detector: consumes the frame std and says whether the slit
    # is on the disk, off it, or has just seen the trailing limb.
    #
    # It is deliberately stateful and tiny: the engine calls update() from its
    # polling loop, which must stay inside a few microseconds.
    floor: float = LIMB_STDDEV_MIN
    dark_mult: float = LIMB_DARK_MULT
    dark_offset: float = LIMB_DARK_OFFSET
    on_disk_std: float = ON_DISK_STDDEV
    trailing_fraction: float = TRAILING_STDDEV_FRACTION
    min_run: int = 2

    # @args: none
    def __post_init__(self) -> None:
        self.dark_std = 0.0
        self.threshold = limb_threshold(self.dark_std, self.dark_mult,
                                        self.dark_offset, self.floor)
        self.peak = 0.0
        self.state = LimbState.UNKNOWN
        self._below_run = 0
        self._on_disk_run = 0

    # @args: std - a measured dark baseline
    # @return: the new threshold
    # Called once the slit is known to be off the disk. Rebuilding the
    # threshold here is what adapts to gain and exposure changes.
    def set_dark(self, std: float) -> float:
        self.dark_std = max(0.0, float(std))
        self.threshold = limb_threshold(self.dark_std, self.dark_mult,
                                        self.dark_offset, self.floor)
        return self.threshold

    # @args: none
    def reset(self) -> None:
        self.dark_std = 0.0
        self.threshold = limb_threshold(self.dark_std, self.dark_mult,
                                        self.dark_offset, self.floor)
        self.peak = 0.0
        self.state = LimbState.UNKNOWN
        self._below_run = 0
        self._on_disk_run = 0

    # @args: std - standard deviation of the current frame
    # @return: LimbState after this sample
    # A single frame is never trusted: the leading limb needs min_run samples
    # above the threshold, and the trailing limb needs min_run samples below
    # max(floor, peak*trailing_fraction) after a genuine on-disk peak. That is
    # the prototype's "below >= 2" guard.
    def update(self, std: float) -> str:
        value = float(std)
        if value > self.peak:
            self.peak = value
        if self.state in (LimbState.UNKNOWN, LimbState.DARK):
            if value > self.threshold:
                self._on_disk_run += 1
                if self._on_disk_run >= max(1, self.min_run):
                    self.state = LimbState.ON_DISK
            else:
                self._on_disk_run = 0
                self.state = LimbState.DARK
            return self.state

        # On disk: watch for the trailing limb. The peak guard stops the dark
        # baseline itself being mistaken for a genuine disk that has left.
        trailing_threshold = max(self.floor, self.peak * self.trailing_fraction)
        if self.peak > self.on_disk_std and value < trailing_threshold:
            self._below_run += 1
            if self._below_run >= max(1, self.min_run):
                self.state = LimbState.TRAILING
        else:
            self._below_run = 0
        return self.state
