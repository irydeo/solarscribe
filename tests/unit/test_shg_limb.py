############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg limb test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# External anchor: the nightscribe-scan limb constants and its measured
# behaviour. On the disk the Fraunhofer lines give a 16-bit stddev of ~10000+;
# off the disk the sensor noise is ~20-100. The threshold is the largest of
# dark*5, dark+300 and 500 (prototype section 3). The two-sample confirmation
# is the prototype's "below >= 2" guard.

import numpy as np
import pytest

from solarscribe.shg import limb

from .test_shg_support import FakeFrame


def test_threshold_is_relative_to_the_dark_baseline():
    # Clean dark: the absolute floor wins.
    assert limb.limb_threshold(100.0) == pytest.approx(500.0)
    # Noisy dark: the multiple of the baseline wins and stops a false limb.
    assert limb.limb_threshold(1000.0) == pytest.approx(5000.0)
    # The offset term wins just above the floor.
    assert limb.limb_threshold(400.0) == pytest.approx(2000.0)


def test_detect_limb_columns_finds_a_run_above_the_threshold():
    profile = [100.0, 100.0, 10000.0, 12000.0, 9000.0, 100.0]
    assert limb.detect_limb_columns(profile, 500.0) == (2, 4)
    # A single hot column is not a disk when a run of two is required.
    assert limb.detect_limb_columns([100.0, 10000.0, 100.0], 500.0, min_run=2) is None


def test_detector_needs_two_samples_on_disk():
    detector = limb.LimbDetector()
    detector.set_dark(100.0)
    assert detector.update(100.0) == limb.LimbState.DARK
    assert detector.update(10000.0) == limb.LimbState.DARK
    assert detector.update(12000.0) == limb.LimbState.ON_DISK
    assert detector.peak == pytest.approx(12000.0)


def test_detector_reports_the_trailing_limb_after_two_dark_samples():
    detector = limb.LimbDetector()
    detector.set_dark(100.0)
    for std in (100.0, 10000.0, 12000.0, 12000.0):
        detector.update(std)
    assert detector.state == limb.LimbState.ON_DISK
    assert detector.update(100.0) == limb.LimbState.ON_DISK
    assert detector.update(100.0) == limb.LimbState.TRAILING


def test_a_noisy_dark_does_not_trigger_a_false_limb():
    # dark 1000 -> threshold 5000; a 3000 sample is still the dark sky.
    detector = limb.LimbDetector()
    detector.set_dark(1000.0)
    for _ in range(5):
        assert detector.update(3000.0) == limb.LimbState.DARK


def test_column_std_profile_separates_a_spectrum_from_flat_sky():
    # A frame with a high-contrast pattern in the middle columns: the std of
    # those bands is large, the flat ones are zero. This is the physical signal
    # the limb detector uses (Fraunhofer lines on the disk).
    data = np.zeros((32, 64), dtype=np.uint16)
    x = np.arange(64)
    data[:, 24:40] = (np.sin(x[24:40] * 1.7) * 8000 + 10000).astype(np.uint16)
    frame = FakeFrame(data)
    profile = limb.column_std_profile(frame, (0, 0, 64, 32), 8)
    assert max(profile) > 500.0
    assert min(profile) == pytest.approx(0.0)
    found = limb.detect_limb_columns(profile, 500.0)
    assert found is not None
    assert found[0] >= 2 and found[1] <= 5
