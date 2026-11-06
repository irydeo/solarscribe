############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg focus test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Ported from /tmp/opencode/nightscribe-scan/tests/test_focus.py. The synthetic
# grids and the expected numbers are the prototype's, so a drift from the
# MLAstro SHG-700 routine fails here. The flat and tilted vertical grids and the
# horizontal grid were also run through the prototype's compute_metrics to pin
# the exact values (not just the qualitative signs).

from dataclasses import FrozenInstanceError, fields

import numpy as np
import pytest

from solarscribe.shg import focus

from .test_shg_support import FakeFrame


def _grid(nx, ny, fn):
    # grid[i][j] with i along X (slit) and j along Y (dispersion), the
    # prototype's orientation.
    return [[float(fn(i, j)) for j in range(ny)] for i in range(nx)]


def test_profiles_match_the_prototype():
    grid = [[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]]   # nx=2, ny=3
    assert np.allclose(focus.row_profile(grid), [1.0, 2.0, 3.0])
    assert np.allclose(focus.col_profile(grid), [2.0, 2.0])


def test_contrast_is_the_relative_standard_deviation():
    assert focus.contrast([5.0, 5.0, 5.0]) == 0.0
    # mean 2, population std 1 -> 0.5.
    assert focus.contrast([1.0, 3.0]) == pytest.approx(0.5)
    assert focus.contrast([]) == 0.0


def test_gradient_energy_is_the_mean_squared_step_over_mean_squared():
    assert focus.gradient_energy([5.0, 5.0, 5.0]) == 0.0
    # diffs 10, -10, 10 -> 300 / (25 * 3) = 4.0.
    assert focus.gradient_energy([0.0, 10.0, 0.0, 10.0]) == pytest.approx(4.0)
    assert focus.gradient_energy([5.0]) == 0.0


def test_count_peaks_matches_the_plateau_rule():
    assert focus.count_peaks([0.0, 1.0, 0.0, 1.0, 0.0]) == 2
    assert focus.count_peaks([0.0, 0.0, 0.0, 0.0]) == 0
    # A flat top counts once: the left neighbour may be equal.
    assert focus.count_peaks([0.0, 1.0, 1.0, 0.0]) == 1
    assert focus.count_peaks([0.0, 1.0, 0.5, 0.0]) == 1


def test_detect_edge_vertical_is_flat():
    grid = _grid(5, 6, lambda i, j: 0.0 if i < 3 else 10.0)
    sharp, flat, orientation = focus.detect_edge(grid)
    assert orientation == "vertical"
    assert flat == 0.0
    assert sharp == pytest.approx(2.5)   # 10 / mean 4


def test_detect_edge_vertical_is_tilted():
    grid = _grid(8, 5, lambda i, j: 0.0 if i < 2 + j else 10.0)
    sharp, flat, orientation = focus.detect_edge(grid)
    assert orientation == "vertical"
    assert flat == pytest.approx(1.4142135623730951)
    assert sharp == pytest.approx(2.0)


def test_detect_edge_horizontal():
    grid = _grid(4, 5, lambda i, j: 0.0 if j < 3 else 10.0)
    sharp, flat, orientation = focus.detect_edge(grid)
    assert orientation == "horizontal"
    assert flat == 0.0
    assert sharp == pytest.approx(2.5)


def test_compute_metrics_matches_the_prototype_numbers():
    # The prototype's compute_metrics() on this grid returns exactly these
    # values (checked against nightscribe-focus.py):
    #   line_contrast 0.0, line_gradient 0.0,
    #   detail_contrast 1.224744871391589, detail_gradient 1.5625,
    #   detail_count 0, edge_sharp 2.5, edge_flat 0.0, "vertical".
    grid = _grid(5, 6, lambda i, j: 0.0 if i < 3 else 10.0)
    metrics = focus.compute_metrics(grid)
    assert metrics.line_contrast == pytest.approx(0.0)
    assert metrics.line_gradient == pytest.approx(0.0)
    assert metrics.detail_contrast == pytest.approx(1.224744871391589)
    assert metrics.detail_gradient == pytest.approx(1.5625)
    assert metrics.detail_count == 0
    assert metrics.edge_sharp == pytest.approx(2.5)
    assert metrics.edge_flat == pytest.approx(0.0)
    assert metrics.edge_orientation == "vertical"


def test_compute_metrics_matches_the_prototype_on_a_tilted_edge():
    # The prototype's compute_metrics() on this tilted grid returns these
    # values; the edge is still vertical but no longer straight.
    grid = _grid(8, 5, lambda i, j: 0.0 if i < 2 + j else 10.0)
    metrics = focus.compute_metrics(grid)
    assert metrics.line_contrast == pytest.approx(0.3535533905932738)
    assert metrics.line_gradient == pytest.approx(0.0625)
    assert metrics.detail_contrast == pytest.approx(0.7745966692414834)
    assert metrics.detail_gradient == pytest.approx(0.11428571428571428)
    assert metrics.detail_count == 0
    assert metrics.edge_sharp == pytest.approx(2.0)
    assert metrics.edge_flat == pytest.approx(1.4142135623730951)
    assert metrics.edge_orientation == "vertical"


def test_compute_metrics_matches_the_prototype_on_a_horizontal_edge():
    # A step along Y: the dispersion profile carries the contrast and the
    # collimator sees a horizontal edge.
    grid = _grid(4, 5, lambda i, j: 0.0 if j < 3 else 10.0)
    metrics = focus.compute_metrics(grid)
    assert metrics.line_contrast == pytest.approx(1.224744871391589)
    assert metrics.line_gradient == pytest.approx(1.5625)
    assert metrics.detail_contrast == pytest.approx(0.0)
    assert metrics.detail_gradient == pytest.approx(0.0)
    assert metrics.detail_count == 0
    assert metrics.edge_sharp == pytest.approx(2.5)
    assert metrics.edge_flat == pytest.approx(0.0)
    assert metrics.edge_orientation == "horizontal"


def test_focus_metrics_is_frozen_and_lists_the_eight_fields():
    grid = _grid(4, 4, lambda i, j: float(i + j))
    metrics = focus.compute_metrics(grid)
    names = {field.name for field in fields(focus.FocusMetrics)}
    assert names == {
        "line_contrast", "line_gradient", "detail_contrast",
        "detail_gradient", "detail_count", "edge_sharp", "edge_flat",
        "edge_orientation",
    }
    assert set(metrics.as_dict()) == names
    with pytest.raises(FrozenInstanceError):
        metrics.line_contrast = 1.0


def test_frame_grid_with_a_uniform_frame():
    frame = FakeFrame(np.full((100, 200), 7, dtype=np.uint16))
    grid = focus.frame_grid(frame, (0, 0, 200, 100), 4, 2)
    assert grid.shape == (4, 2)
    assert np.allclose(grid, 7.0)


def test_frame_grid_reads_the_roi_not_the_whole_frame():
    data = np.zeros((100, 200), dtype=np.uint16)
    data[20:40, 10:60] = 1000
    frame = FakeFrame(data)
    grid = focus.frame_grid(frame, (10, 20, 50, 20), 2, 2)
    assert np.allclose(grid, 1000.0)


def test_frame_grid_last_cell_absorbs_the_remainder():
    # A 10 px width split into 3 cells is 3, 3, 4; the last cell has the same
    # mean as the rest, so the block boundaries are the prototype's.
    data = np.tile(np.arange(10, dtype=np.uint16), (6, 1))
    frame = FakeFrame(data)
    grid = focus.frame_grid(frame, (0, 0, 10, 6), 3, 2)
    expected = [1.0, 4.0, 7.5]
    assert np.allclose(grid[:, 0], expected)
    assert np.allclose(grid[:, 1], expected)


def test_frame_grid_rejects_an_empty_roi():
    frame = FakeFrame(np.zeros((100, 200), dtype=np.uint16))
    with pytest.raises(ValueError):
        focus.frame_grid(frame, (500, 500, 10, 10), 4, 2)


def test_focus_watcher_holds_the_running_max_and_min():
    watcher = focus.FocusWatcher()
    first = focus.FocusMetrics(1.0, 2.0, 3.0, 4.0, 5, 6.0, 7.0, "vertical")
    second = focus.FocusMetrics(2.0, 1.0, 2.0, 5.0, 4, 5.0, 8.0, "horizontal")
    watcher.update(first)
    watcher.update(second)
    holds = watcher.holds()
    assert holds["line_contrast"] == focus.FocusHold(high=2.0, low=1.0)
    assert holds["line_gradient"] == focus.FocusHold(high=2.0, low=1.0)
    assert holds["detail_contrast"] == focus.FocusHold(high=3.0, low=2.0)
    assert holds["detail_gradient"] == focus.FocusHold(high=5.0, low=4.0)
    assert holds["detail_count"] == focus.FocusHold(high=5.0, low=4.0)
    assert holds["edge_sharp"] == focus.FocusHold(high=6.0, low=5.0)
    assert holds["edge_flat"] == focus.FocusHold(high=8.0, low=7.0)
    # The orientation is a string and has no hold.
    assert "edge_orientation" not in holds
    assert watcher.latest() is second

    watcher.reset()
    assert watcher.holds() == {}
    assert watcher.latest() is None


def test_focus_watcher_keeps_a_single_value_twice():
    watcher = focus.FocusWatcher()
    metrics = focus.FocusMetrics(1.0, 2.0, 3.0, 4.0, 5, 6.0, 7.0, "vertical")
    watcher.update(metrics)
    watcher.update(metrics)
    assert watcher.holds()["line_contrast"] == focus.FocusHold(high=1.0, low=1.0)
