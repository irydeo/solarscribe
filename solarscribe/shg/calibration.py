############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg calibration module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Scan-rate self-calibration.
#
# The scan must move the sky by PIXEL_SCALE arcseconds per frame, so that the
# reconstructed disk has X/Y = 1.000. The mount rate is a multiplier of the
# sidereal rate, but the real arcseconds per multiplier unit depend on the
# mount, its load and its firmware. The prototype measures it by crossing the
# disk at a known multiplier and timing the crossing, then scales the science
# multiplier to the target rate.
#
# The bug this module exists to prevent (nightscribe-scan, 2026-11 session):
# the old code measured the sky rate while slewing at 16x and then applied
# target/measured to the science multiplier. That ignored the measurement
# speed and made the scan ~4.6x too slow (actual_xy ~4.1 instead of ~1). The
# corrected formula normalises by the measurement speed first:
#
#   per_unit = measured_rate / measure_speed          arcsec/s per 1x
#   factor   = (target / per_unit) / current_multiplier
#
# The external anchor is the prototype's regression test and the real session
# fixture: measured 213.7"/s at 16x, per_unit 13.35, target 51.70, multiplier
# 3.437 -> corrected 51.70"/s. The same fixture row has calibration_factor
# 0.241944 and actual_xy 4.14377, which the guard rejects.

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CalibrationResult",
    "calibrated_rate_arcsec_s",
    "calibration_factor",
    "median_rate",
    "rate_is_sane",
    "scan_rate_calibration_factor",
    "sky_rate_per_unit",
    "target_rate_arcsec_s",
]

# The sanity guard of the prototype: a correction that leaves the sky rate
# outside 0.5x..2x the target is a bad measurement, not a real mount error.
# The correct factor is a small correction around 1 in normal use; the old
# buggy formula produced 0.24 here and is rejected.
CALIBRATION_LOW = 0.5
CALIBRATION_HIGH = 2.0


@dataclass(frozen=True)
class CalibrationResult:
    # Outcome of one or more calibration traverses.
    ok: bool
    factor: float                  # applied to the current multiplier
    measured_rate_arcsec_s: float  # sky rate at measure_speed
    per_unit_arcsec_s: float       # sky rate per 1x multiplier
    target_rate_arcsec_s: float
    reason_code: str = ""          # "" when ok


# @args: measured_rate_arcsec_s - sky rate measured while slewing at
#                                 measure_speed, arcsec/s
#        measure_speed - the multiplier used for the measurement
# @return: the mount's sky rate per unit multiplier, or None when invalid
# The measurement is taken at measure_speed, not at the science rate, so the
# division is the whole point. Without it the factor is off by that speed.
def sky_rate_per_unit(measured_rate_arcsec_s: float,
                      measure_speed: float) -> float | None:
    if measured_rate_arcsec_s <= 0 or measure_speed <= 0:
        return None
    return measured_rate_arcsec_s / float(measure_speed)


# @args: pixel_scale_arcsec_px - plate scale along the scan axis
#        fps - frames per second actually written
# @return: the sky rate that samples one pixel per frame
# The target: one pixel of sky per frame, so the recon is not stretched. The
# FPS must be the real capture rate, not the preview rate: the 2026-11-01 run
# previewed at ~154 fps and captured at 121.56 fps, and using the preview rate
# made the disk elliptical (X/Y = 0.79).
def target_rate_arcsec_s(pixel_scale_arcsec_px: float, fps: float) -> float:
    if pixel_scale_arcsec_px <= 0 or fps <= 0:
        raise ValueError("pixel scale and fps must be positive")
    return pixel_scale_arcsec_px * fps


# @args: measured_rate_arcsec_s - sky rate at measure_speed, arcsec/s
#        measure_speed - multiplier used for the measurement
#        target_rate_arcsec_s_value - desired sky rate, arcsec/s
#        scan_multiplier - current science multiplier
# @return: the factor to apply to scan_multiplier, or None when invalid
# Corrected formula (see the module comment). It is the prototype's
# scan_rate_calibration_factor ported unchanged, because its regression test
# is the external anchor.
def calibration_factor(measured_rate_arcsec_s: float, measure_speed: float,
                       target_rate_arcsec_s_value: float,
                       scan_multiplier: float) -> float | None:
    per_unit = sky_rate_per_unit(measured_rate_arcsec_s, measure_speed)
    if per_unit is None or per_unit <= 0 or target_rate_arcsec_s_value <= 0:
        return None
    if scan_multiplier <= 0:
        return None
    return (target_rate_arcsec_s_value / per_unit) / scan_multiplier


# @args: scan_multiplier - current science multiplier
#        factor - correction from calibration_factor
#        per_unit_arcsec_s - sky rate per unit multiplier
# @return: the corrected sky rate, arcsec/s
def calibrated_rate_arcsec_s(scan_multiplier: float, factor: float,
                             per_unit_arcsec_s: float) -> float:
    return scan_multiplier * factor * per_unit_arcsec_s


# @args: corrected_rate - sky rate after the correction
#        target - desired sky rate
#        low, high - accepted fraction of the target
# @return: whether the correction is believable
# A bad measurement must not be allowed to wreck the scan; the prototype keeps
# the current multiplier when the correction is outside 0.5x..2x.
def rate_is_sane(corrected_rate: float, target: float,
                 low: float = CALIBRATION_LOW,
                 high: float = CALIBRATION_HIGH) -> bool:
    if target <= 0 or corrected_rate <= 0:
        return False
    return low * target <= corrected_rate <= high * target


# @args: samples - measured sky rates, one per traverse
# @return: the median rate, or None when there is no valid sample
# The median, not the mean: a single traverse clipped by a cloud or a lost
# frame is an outlier, and the prototype sorts and takes the middle value.
def median_rate(samples: list[float]) -> float | None:
    values = sorted(float(s) for s in samples if s is not None and s > 0)
    if not values:
        return None
    return values[len(values) // 2]


# The prototype name of the corrected formula, kept as an alias so the parity
# note and any ported test find it.
scan_rate_calibration_factor = calibration_factor
