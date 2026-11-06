############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - auto exposure test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The auto-exposure loop (parity row 10). The simulated signal scales linearly
# with exposure, so the expected convergence is a closed-form number, not a
# guess: at 1000 us the mean is 8191.875 ADU and the target (25% of 65535) is
# reached at 2000 us.

import pytest

from solarscribe.capture.auto_exposure import AutoExposureConfig, AutoExposureLoop


FULL_16 = 65535.0
TARGET_16 = 0.25 * FULL_16


def _signal(exposure):
    # 8.191875 ADU per microsecond, chosen so 2000 us lands exactly on target.
    return exposure * (TARGET_16 / 2000.0)


def test_loop_converges_to_the_target_exposure():
    loop = AutoExposureLoop(initial_exposure_us=1000.0)
    now = 0.0
    exposure = 1000.0
    for _ in range(20):
        result = loop.observe(_signal(exposure), FULL_16, now)
        if result is not None:
            exposure = result
        now += 0.3
    assert loop.converged()
    assert not loop.failed()
    assert exposure == pytest.approx(2000.0, rel=1e-6)


def test_a_mean_inside_the_tolerance_is_converged_without_changing():
    loop = AutoExposureLoop(initial_exposure_us=1000.0)
    near = TARGET_16 * 1.02
    assert loop.observe(near, FULL_16, 0.0) is None
    assert loop.converged()
    assert loop.exposure() == pytest.approx(1000.0)


def test_one_correction_is_clamped_to_a_factor_of_two():
    loop = AutoExposureLoop(initial_exposure_us=1000.0)
    # Dark frame: the unlimited ratio would be enormous.
    result = loop.observe(10.0, FULL_16, 0.0)
    assert result == pytest.approx(2000.0)     # 1000 * max_ratio 2.0


def test_corrections_are_spaced_by_the_interval():
    loop = AutoExposureLoop(initial_exposure_us=1000.0)
    first = loop.observe(100.0, FULL_16, 0.0)
    assert first is not None
    assert loop.observe(100.0, FULL_16, 0.1) is None     # too soon
    assert loop.observe(100.0, FULL_16, 0.31) is not None


def test_no_signal_gives_up_and_reverts_to_the_starting_exposure():
    config = AutoExposureConfig(max_attempts=3, interval_s=0.0,
                                min_mean_adu=1.0)
    loop = AutoExposureLoop(config, initial_exposure_us=1000.0)
    results = [loop.observe(0.0, FULL_16, float(i)) for i in range(5)]
    non_none = [value for value in results if value is not None]
    assert non_none == [1000.0]        # one revert, then silence
    assert loop.failed()
    assert loop.attempts() == 3


def test_reset_rearms_the_loop():
    loop = AutoExposureLoop(initial_exposure_us=1000.0)
    loop.observe(0.0, FULL_16, 0.0)
    loop.reset(5000.0)
    assert loop.exposure() == pytest.approx(5000.0)
    assert loop.attempts() == 0
    assert not loop.failed()
    assert not loop.converged()


def test_eight_bit_full_scale_is_honoured():
    loop = AutoExposureLoop(initial_exposure_us=1000.0)
    loop.observe(0.25 * 255.0, 255.0, 0.0)
    assert loop.converged()
