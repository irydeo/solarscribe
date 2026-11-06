############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg calibration test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# External anchors:
#   - the nightscribe-scan regression test test_calibration.py, which is the
#     reference implementation of this formula;
#   - the real 2026-11-04 session log (tests/fixtures/scan_log.csv of the
#     prototype), whose rows carry calibration_factor 0.241944 and actual_xy
#     ~4.14: the bug this module prevents. The log's target is 51.70"/s at
#     969 mm focal and 121.39 fps (PIXEL_SCALE 0.4257"/px).
#   - the sidereal rate 15.04"/s per multiplier unit, the prototype constant.

import pytest

from solarscribe.shg import calibration


def test_factor_normalises_by_the_measurement_speed():
    # Prototype test_calibration.py: per_unit=13.35, measure_speed=16,
    # measured=16*13.35, target=51.70, multiplier=3.437.
    per_unit = 13.35
    measure_speed = 16.0
    measured = measure_speed * per_unit
    target = 51.70
    multiplier = 3.437
    factor = calibration.calibration_factor(measured, measure_speed, target,
                                            multiplier)
    assert factor == pytest.approx((target / per_unit) / multiplier, rel=1e-9)
    assert multiplier * factor * per_unit == pytest.approx(target, rel=1e-9)


def test_invalid_input_returns_none():
    assert calibration.calibration_factor(0.0, 16.0, 51.7, 3.4) is None
    assert calibration.calibration_factor(200.0, 0.0, 51.7, 3.4) is None
    assert calibration.calibration_factor(200.0, 16.0, 51.7, 0.0) is None
    assert calibration.calibration_factor(-5.0, 16.0, 51.7, 3.4) is None


def test_the_old_formula_is_off_by_the_measurement_speed():
    # The real numbers that exposed the bug: target 51.70, measured 213.7 at
    # 16x, sidereal 15.04.
    target, measured, measure_speed, sidereal = 51.70, 213.7, 16.0, 15.04
    multiplier = target / sidereal
    old = target / measured
    new = (target / (measured / measure_speed)) / multiplier
    assert old < 0.5                     # the guard would reject it
    assert new > 1.0
    assert new / old == pytest.approx(measure_speed * sidereal / target, rel=0.01)


def test_guard_rejects_the_old_factor():
    # The guard must reject the factor the old code applied to the real log.
    target = 0.4257 * 121.39          # 969 mm, 2 um, 121.39 fps
    old_factor = target / 213.7
    corrected = 0.831352 * old_factor * 15.04
    assert not calibration.rate_is_sane(corrected, target)


def test_real_session_row_is_recovered_by_the_corrected_formula():
    # Row r01_s01 of the prototype fixture: scan_multiplier 0.831352,
    # fps_used 121.391052, calibration_factor 0.241944, actual_xy 4.143770.
    # The target at 969 mm focal is 0.4257*121.391 = 51.68"/s.
    target = 0.4257 * 121.391052
    per_unit = 213.7 / 16.0
    factor = calibration.calibration_factor(213.7, 16.0, target, 0.831352)
    corrected = 0.831352 * factor * per_unit
    assert corrected == pytest.approx(target, rel=1e-9)
    assert calibration.rate_is_sane(corrected, target)
    # The old factor recorded in the fixture is the one the guard rejects.
    assert not calibration.rate_is_sane(
        0.831352 * 0.241944 * 15.04, target)


def test_target_rate_is_one_pixel_per_frame():
    # 0.5778"/px at 120 fps -> 69.34"/s, the rate that samples 1:1.
    assert calibration.target_rate_arcsec_s(0.5778, 120.0) == pytest.approx(
        69.336, abs=1e-3)


def test_median_ignores_a_bad_traverse():
    assert calibration.median_rate([13.2, 13.4, 100.0]) == pytest.approx(13.4)
    assert calibration.median_rate([]) is None
    assert calibration.median_rate([0.0, -1.0]) is None


def test_sky_rate_per_unit_is_the_measurement_rate_over_speed():
    assert calibration.sky_rate_per_unit(213.6, 16.0) == pytest.approx(13.35)
    assert calibration.sky_rate_per_unit(0.0, 16.0) is None
