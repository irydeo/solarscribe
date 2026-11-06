############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg analysis test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Anchors: the chord geometry of ADR-006 for the slit extent, the definition of
# a percentile, and the first moment of the intensity distribution for the
# centroid. The normalized imbalance (L-R)/(L+R) cancels the exposure, which is
# why the prototype's left/right loop works at any gain.

import numpy as np
import pytest

from solarscribe.shg import analysis

from .test_shg_support import FakeFrame, block_frame, uniform_frame


def test_analysis_regions_split_the_band_at_its_middle():
    regions = analysis.analysis_regions((0, 0, 3480, 248), (0, 40, 3480, 160))
    assert set(regions) == {"left", "right", "limb"}
    assert regions["left"] == (0, 40, 1740, 160)
    assert regions["right"] == (1740, 40, 1740, 160)
    assert regions["limb"] == (0, 40, 3480, 160)


def test_analysis_regions_clamp_a_stale_band_to_the_frame():
    regions = analysis.analysis_regions((0, 0, 100, 50), (0, 0, 200, 80))
    assert regions["limb"] == (0, 0, 100, 50)
    assert regions["left"] == (0, 0, 50, 50)
    assert regions["right"] == (50, 0, 50, 50)


def test_slit_extent_matches_the_prototype_threshold_rule():
    # lo=10, hi=100, threshold=10+0.25*90=32.5: bands 2,3,4 are lit.
    means = [10.0, 10.0, 100.0, 100.0, 100.0, 10.0]
    assert analysis.illuminated_columns(means) == (2, 4)
    assert analysis.measure_slit_extent_px(means, band_px=10) == pytest.approx(30.0)


def test_slit_extent_is_zero_for_a_flat_or_dark_profile():
    assert analysis.measure_slit_extent_px([5.0, 5.0, 5.0], 4) == 0.0
    assert analysis.measure_slit_extent_px([], 4) == 0.0


def test_symmetry_centroid_is_the_first_moment():
    # A symmetric block around index 3 of 6 has centroid 3; the centre is 2.5,
    # so the offset is half a band = 5 px with band=10.
    means = [0.0, 0.0, 10.0, 10.0, 10.0, 0.0]
    assert analysis.symmetry_centroid_offset_px(means, band_px=10) == pytest.approx(5.0)
    # A profile centred on the middle has zero offset.
    assert analysis.symmetry_centroid_offset_px([0, 1, 2, 2, 1, 0], 10) == pytest.approx(0.0)


def test_left_right_means_and_exposure_free_balance():
    left = uniform_frame(20, 10, value=100)
    right = uniform_frame(20, 10, value=300)
    l_mean, r_mean = analysis.left_right_means(left, (0, 0, 20, 10),
                                               (0, 0, 20, 10))
    # The two calls read the same uniform frame; use real sub-regions instead.
    frame = FakeFrame(np.zeros((10, 40), dtype=np.uint16))
    frame.data[:, :20] = 100
    frame.data[:, 20:] = 300
    l_mean, r_mean = analysis.left_right_means(frame, (0, 0, 20, 10),
                                               (20, 0, 20, 10))
    assert (l_mean, r_mean) == (100.0, 300.0)
    assert analysis.dec_balance(l_mean, r_mean) == pytest.approx(-0.5)
    # Doubling the exposure doubles both halves and leaves the ratio unchanged.
    frame.data = (frame.data.astype(np.uint32) * 2).astype(np.uint16)
    l2, r2 = analysis.left_right_means(frame, (0, 0, 20, 10), (20, 0, 20, 10))
    assert analysis.dec_balance(l2, r2) == pytest.approx(-0.5)


def test_percentile_and_bright_fraction_follow_their_definitions():
    data = np.arange(100, dtype=np.uint16).reshape(10, 10)
    frame = FakeFrame(data)
    assert analysis.percentile_value(frame, (0, 0, 10, 10), 0.5) == pytest.approx(49.5)
    assert analysis.percentile_value(frame, (0, 0, 10, 10), 0.99) == pytest.approx(98.01)
    assert analysis.bright_fraction(frame, (0, 0, 10, 10), 49.5) == pytest.approx(0.5)


def test_column_means_cover_the_full_width():
    frame = uniform_frame(64, 16, value=10)
    means = analysis.column_means(frame, (0, 0, 64, 16), 4)
    assert len(means) == 4
    assert all(value == pytest.approx(10.0) for value in means)


def test_subdivide_roi_covers_the_width_without_gaps():
    bands = analysis.subdivide_roi((5, 0, 10, 4), 3)
    assert sum(band[2] for band in bands) == 10
    assert bands[0][0] == 5
    assert bands[-1][0] + bands[-1][2] == 15


def test_symmetry_offset_recovers_a_known_shift():
    # A 10 px block centred 8 px right of the band centre: the centroid says
    # +8 px, and with 0.5778"/px that is 4.62".
    frame = block_frame(width=64, height=32, centre_px=40, block_px=10)
    offset = analysis.symmetry_centroid_offset_px(
        analysis.column_means(frame, (0, 0, 64, 32), 64), 1)
    assert offset == pytest.approx(8.0, abs=1.0)
