############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg focus module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Focus aid for the SHG-700 (MLAstro), ported from nightscribe-focus.py.
#
# The MLAstro SHG-700 routine has three focusers that interact, so the observer
# iterates:
#   1. Spectrograph (camera focus): the absorption lines (H-alpha, the iron
#      doublet) must be as contrasted and sharp as possible.
#   2. Collimator: the physical slit edge must be as sharp and straight as
#      possible; a straight edge is the flatness figure.
#   3. Telescope: the surface detail must be as contrasted and abundant as
#      possible.
# The prototype computes every indicator along both axes, so the panel does not
# depend on the camera orientation, and this port keeps that property.
#
# The external reference is the MLAstro SHG-700 focus routine documented in the
# prototype header, and the reference implementation is
# /tmp/opencode/nightscribe-scan/nightscribe-focus.py with its
# tests/test_focus.py. The synthetic grids and the expected numbers below are
# the same cases, so a port that drifts from the prototype fails a test.
#
# What the figures mean, in the units the dialog shows (all dimensionless):
#   - contrast: relative standard deviation (std/mean) of a profile. Higher is
#     better; it is independent of the exposure because both terms scale.
#   - gradient: mean squared adjacent step divided by the mean level squared.
#     Higher is sharper: a focused line or edge has a large step per band.
#   - detail_count: local maxima above 25% of the profile's dynamic range.
#     More structures means the telescope is closer to focus.
#   - edge_sharp: the strongest adjacent-cell jump normalised by the grid mean.
#   - edge_flat: the standard deviation of the edge position along the
#     perpendicular axis; 0 is a perfectly straight edge, lower is better.
#   - edge_orientation: "vertical" (slit edge, a step along X) or
#     "horizontal".
#
# Cost: the grid is 24x12 by default. frame_grid does 288 block means, the
# profiles are two numpy reductions and detect_edge is vectorised. At the
# prototype's 0.25 s refresh that is far inside the capture-thread budget
# (ADR-013); there is no Python per-pixel loop.
#
# No Qt and no driver: the camera event wiring lives in the UI, this module
# just measures a Frame.

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

import numpy as np

from solarscribe.devices.abc import ROI, Frame

from .analysis import frame_array

__all__ = [
    "FocusHold",
    "FocusMetrics",
    "FocusWatcher",
    "col_profile",
    "compute_metrics",
    "contrast",
    "count_peaks",
    "detect_edge",
    "frame_grid",
    "gradient_energy",
    "row_profile",
]

# Prototype defaults (nightscribe-focus.py).
GRID_X = 24
GRID_Y = 12
PEAK_REL = 0.25


@dataclass(frozen=True)
class FocusMetrics:
    # One refresh of the focus panel. Frozen because it crosses from the
    # measurement to the dialog and nobody owns a private copy.
    #
    # The three groups are the three focusers of the MLAstro routine:
    #   line_*   -> spectrograph (absorption lines along the dispersion axis Y)
    #   edge_*   -> collimator (slit edge)
    #   detail_* -> telescope (surface detail along the slit axis X)
    line_contrast: float
    line_gradient: float
    detail_contrast: float
    detail_gradient: float
    detail_count: int
    edge_sharp: float
    edge_flat: float
    edge_orientation: str

    # @args: none
    # @return: the metrics as a plain dict, for the UI panel and the logs
    def as_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True)
class FocusHold:
    # Running max/min of one numeric metric, the dialog's hold display.
    high: float
    low: float


# @args: grid - 2D array grid[i][j], i along X (slit), j along Y (dispersion)
# @return: profile along Y, the mean over X for each Y band
# The dispersion axis is Y: absorption lines are features along Y, so their
# contrast is measured on this profile.
def row_profile(grid) -> np.ndarray:
    values = np.asarray(grid, dtype=float)
    if values.size == 0:
        return np.zeros(0, dtype=float)
    return np.mean(values, axis=0)


# @args: grid - 2D array grid[i][j], i along X (slit), j along Y (dispersion)
# @return: profile along X, the mean over Y for each X band
# The slit axis is X: surface detail and the slit edge are features along X.
def col_profile(grid) -> np.ndarray:
    values = np.asarray(grid, dtype=float)
    if values.size == 0:
        return np.zeros(0, dtype=float)
    return np.mean(values, axis=1)


# @args: profile - 1D profile
# @return: relative standard deviation std/mean, 0 when undefined
# Population std (ddof=0), the prototype's definition. A constant profile has
# zero contrast; a mean of zero has no relative scale, so it returns 0 instead
# of infinity.
def contrast(profile) -> float:
    values = np.asarray(profile, dtype=float)
    if values.size == 0:
        return 0.0
    mean = float(np.mean(values))
    if mean <= 0:
        return 0.0
    return float(np.std(values, ddof=0) / mean)


# @args: profile - 1D profile
# @return: mean squared adjacent step divided by mean squared, 0 when undefined
# The prototype's formula: sum(diff^2) / (mean^2 * (n-1)). It is dimensionless
# and does not depend on the exposure; a sharp line or edge raises it.
def gradient_energy(profile) -> float:
    values = np.asarray(profile, dtype=float)
    if values.size < 2:
        return 0.0
    mean = float(np.mean(values))
    if mean <= 0:
        return 0.0
    steps = np.diff(values)
    return float(np.sum(steps * steps) / (mean * mean * (values.size - 1)))


# @args: profile - 1D profile; rel - fraction of the dynamic range a maximum
#        must exceed
# @return: number of local maxima above lo + rel*(hi-lo)
# The prototype's plateau rule: the left neighbour may be equal (>=), the right
# one must be strictly lower (>), so a flat top counts once and a flat line
# counts zero.
def count_peaks(profile, rel: float = PEAK_REL) -> int:
    values = np.asarray(profile, dtype=float)
    if values.size < 3:
        return 0
    low = float(np.min(values))
    high = float(np.max(values))
    if high <= low:
        return 0
    threshold = low + rel * (high - low)
    left = values[1:-1] >= values[:-2]
    right = values[1:-1] > values[2:]
    above = values[1:-1] > threshold
    return int(np.count_nonzero(left & right & above))


# @args: grid - 2D array grid[i][j]
# @return: (sharp, flat, orientation)
#   sharp: the strongest adjacent-cell jump divided by the grid mean.
#   flat: the standard deviation of the edge position along the perpendicular
#         axis; 0 for a perfectly straight edge.
#   orientation: "vertical" when the strongest step is along X (the slit edge),
#                "horizontal" when it is along Y.
# Vectorised over the 12 rows and 24 columns: the prototype loops over them
# with _max_jump, and the indices of the first maximum are the same.
def detect_edge(grid) -> tuple[float, float, str]:
    values = np.asarray(grid, dtype=float)
    if values.ndim != 2 or values.size == 0:
        return 0.0, 0.0, "vertical"
    nx, ny = values.shape
    mean = float(np.mean(values))
    if mean <= 0:
        return 0.0, 0.0, "vertical"

    best_v = 0.0
    pos_v = np.zeros(ny, dtype=int)
    if nx >= 2:
        diff_x = np.abs(np.diff(values, axis=0))   # (nx-1, ny)
        pos_v = np.argmax(diff_x, axis=0)
        best_v = float(np.max(diff_x))

    best_h = 0.0
    pos_h = np.zeros(nx, dtype=int)
    if ny >= 2:
        diff_y = np.abs(np.diff(values, axis=1))   # (nx, ny-1)
        pos_h = np.argmax(diff_y, axis=1)
        best_h = float(np.max(diff_y))

    if best_v >= best_h:
        return best_v / mean, float(np.std(pos_v, ddof=0)), "vertical"
    return best_h / mean, float(np.std(pos_h, ddof=0)), "horizontal"


# @args: grid - 2D array grid[i][j], i along X (slit), j along Y (dispersion)
# @return: the FocusMetrics dataclass with all the focus indicators
# The grouping is the MLAstro routine: the row profile (Y) drives the
# spectrograph figures, the column profile (X) drives the telescope figures,
# and detect_edge drives the collimator figures.
def compute_metrics(grid) -> FocusMetrics:
    values = np.asarray(grid, dtype=float)
    rows = row_profile(values)
    cols = col_profile(values)
    sharp, flat, orientation = detect_edge(values)
    return FocusMetrics(
        line_contrast=contrast(rows),
        line_gradient=gradient_energy(rows),
        detail_contrast=contrast(cols),
        detail_gradient=gradient_energy(cols),
        detail_count=count_peaks(cols),
        edge_sharp=sharp,
        edge_flat=flat,
        edge_orientation=orientation,
    )


# @args: frame - a delivered Frame
#        roi - region in FRAME pixels, (x, y, width, height)
#        nx - cells along X (slit axis)
#        ny - cells along Y (dispersion axis)
# @return: grid[i][j] of cell means, shape (nx, ny)
# The prototype calls CutROI(...).GetStats() 288 times; here one numpy view of
# the frame is sliced into the same cells, so the numbers are identical and the
# capture thread is not asked to copy 288 sub-frames. The last cell on each
# axis absorbs the remainder, exactly like the prototype's `w - x` / `h - y`.
def frame_grid(frame: Frame, roi: ROI, nx: int = GRID_X,
               ny: int = GRID_Y) -> np.ndarray:
    if nx <= 0 or ny <= 0:
        raise ValueError("the grid must have positive dimensions")
    array = frame_array(frame)
    x0 = max(0, int(roi[0]))
    y0 = max(0, int(roi[1]))
    x1 = min(frame.width, x0 + int(roi[2]))
    y1 = min(frame.height, y0 + int(roi[3]))
    width = x1 - x0
    height = y1 - y0
    if width <= 0 or height <= 0:
        raise ValueError("the ROI does not intersect the frame")
    cell_w = max(1, width // nx)
    cell_h = max(1, height // ny)
    x_edges = [i * cell_w for i in range(nx)] + [width]
    y_edges = [j * cell_h for j in range(ny)] + [height]
    grid = np.empty((nx, ny), dtype=float)
    for i in range(nx):
        for j in range(ny):
            cell = array[y0 + y_edges[j]:y0 + y_edges[j + 1],
                         x0 + x_edges[i]:x0 + x_edges[i + 1]]
            grid[i, j] = float(np.mean(cell)) if cell.size else 0.0
    return grid


class FocusWatcher:
    # Running max/min per numeric metric, the dialog's hold display. The
    # prototype attached this to the camera event; in SolarScribe the UI owns
    # the event and calls update(), so the class stays Qt-free and driver-free.
    #
    # edge_orientation is a string and has no hold; the seven numeric figures
    # do, exactly like the prototype's HOLD_KEYS.

    # @args: none
    def __init__(self) -> None:
        self._holds: dict[str, FocusHold] = {}
        self._latest: FocusMetrics | None = None

    # @args: metrics - one refresh from compute_metrics
    # @return: none
    def update(self, metrics: FocusMetrics) -> None:
        for key, value in metrics.as_dict().items():
            if key == "edge_orientation" or isinstance(value, bool):
                continue
            if not isinstance(value, (int, float)):
                continue
            number = float(value)
            previous = self._holds.get(key)
            if previous is None:
                self._holds[key] = FocusHold(high=number, low=number)
            else:
                self._holds[key] = FocusHold(
                    high=max(previous.high, number),
                    low=min(previous.low, number),
                )
        self._latest = metrics

    # @return: a copy of the holds, keyed by metric name
    def holds(self) -> dict[str, FocusHold]:
        return dict(self._holds)

    # @return: the last metrics, or None before the first update
    def latest(self) -> FocusMetrics | None:
        return self._latest

    # @args: none
    # @return: none. Clears the holds and the last metrics
    def reset(self) -> None:
        self._holds.clear()
        self._latest = None
