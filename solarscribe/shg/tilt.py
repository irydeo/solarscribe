############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg tilt module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Spectral/slit tilt measurement (ADR-022).
#
# A line is fitted to the position of the slit edge (or of an absorption line)
# across the ROI width. The slope b of y = a + b*x is the tilt:
#
#   tilt_deg = atan(b)
#   tilt_px  = b * width_px
#
# The angle is the inverse tangent of the slope by definition, and the drift in
# pixels across the width is the slope times the width. The residual standard
# deviation of the fit is the straightness of the edge, the prototype's
# edge_flat: a large value means the edge is not a line and the tilt figure is
# not trustworthy, so the UI must say so instead of showing a number (ADR-022).
#
# Why a fitted line and not a single column: the slit edge is a straight
# physical line, so a global fit uses every column and rejects the noisy ones.
# The per-column edge is the maximum of the vertical gradient, refined by a
# parabola; that is the standard sub-pixel edge estimator and it is what makes
# a 0.1 deg tilt measurable in a 3480 px wide ROI.
#
# The measurement only touches Frame.data with numpy; it never moves the mount
# and never writes a file. That is what lets the ROI step call it on a live
# preview and the post-processing trust the number it records.

from __future__ import annotations

import math

import numpy as np

from solarscribe.devices.abc import ROI, Frame

from .analysis import frame_array

__all__ = [
    "TiltMeterImpl",
    "edge_positions",
    "fit_line",
    "measure_tilt",
]


# @args: xs - x coordinates
#        ys - y coordinates, same length
# @return: (slope, intercept, residual standard deviation)
# Ordinary least squares for y = a + b*x. The residual is the population RMS
# of the distances to the fitted line, in pixels.
def fit_line(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("a line needs at least two matching points")
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    x_mean = float(np.mean(x))
    y_mean = float(np.mean(y))
    denominator = float(np.sum((x - x_mean) ** 2))
    if denominator <= 0:
        raise ValueError("all points have the same x")
    slope = float(np.sum((x - x_mean) * (y - y_mean)) / denominator)
    intercept = y_mean - slope * x_mean
    residual = y - (intercept + slope * x)
    return slope, intercept, float(np.sqrt(np.mean(residual ** 2)))


# @args: profile - one column profile along the spectral axis
# @return: (edge index, gradient strength); the index is sub-pixel
# The edge is the strongest vertical gradient. A parabola through the three
# samples around the maximum gives the sub-pixel position: for a smooth edge
# the gradient peak is locally quadratic, and the vertex is half a pixel
# accurate. Returns (-1, 0) for a flat profile.
def _edge_in_profile(profile: np.ndarray) -> tuple[float, float]:
    if profile.size < 3:
        return -1.0, 0.0
    gradient = np.abs(np.gradient(profile))
    index = int(np.argmax(gradient))
    strength = float(gradient[index])
    if strength <= 0:
        return -1.0, 0.0
    if 0 < index < gradient.size - 1:
        left = float(gradient[index - 1])
        centre = float(gradient[index])
        right = float(gradient[index + 1])
        denominator = left - 2.0 * centre + right
        if abs(denominator) > 1e-12:
            offset = 0.5 * (left - right) / denominator
            return index + max(-0.5, min(0.5, offset)), strength
    return float(index), strength


# @args: frame - a delivered frame
#        band - the spectral band in FRAME pixels
#        columns - number of column bands to fit
#        min_contrast - minimum gradient strength to accept a column
# @return: [(x_center_px, edge_y_px), ...] for the columns with an edge
# The profile of each band is the mean over its columns, which suppresses the
# sensor noise without moving a straight edge. The x coordinate is relative to
# the band, so the slope is in frame pixels per frame pixel.
def edge_positions(frame: Frame, band: ROI, columns: int = 64,
                   min_contrast: float = 1.0) -> list[tuple[float, float]]:
    if columns <= 0:
        raise ValueError("columns must be positive")
    x, y, w, h = band
    x0 = max(0, int(x))
    y0 = max(0, int(y))
    x1 = min(frame.width, x0 + int(w))
    y1 = min(frame.height, y0 + int(h))
    if x1 - x0 < 2 or y1 - y0 < 3:
        return []
    values = frame_array(frame)[y0:y1, x0:x1].astype(float)
    width = x1 - x0
    edges = np.linspace(0, width, columns + 1).astype(int)
    points: list[tuple[float, float]] = []
    for i in range(columns):
        start = edges[i]
        stop = edges[i + 1]
        if stop <= start:
            continue
        profile = np.mean(values[:, start:stop], axis=1)
        position, strength = _edge_in_profile(profile)
        if position < 0 or strength < min_contrast:
            continue
        points.append(((start + stop - 1) / 2.0, position))
    return points


# @args: frame - a delivered frame
#        band - the spectral band in FRAME pixels
#        columns - number of column bands to fit
#        min_contrast - minimum gradient strength to accept a column
#        reject_sigma - residual threshold, in standard deviations, for the
#                       outlier rejection pass; <= 0 disables it
# @return: the fitted tilt as a TiltResult (shg/abc.py)
# The fit is done twice: once on every edge, once after dropping the points
# whose residual is beyond reject_sigma. One dust mote or one hot column must
# not rotate the slit.
def measure_tilt(frame: Frame, band: ROI, columns: int = 64,
                 min_contrast: float = 1.0,
                 reject_sigma: float = 3.0):
    from .abc import TiltResult

    points = edge_positions(frame, band, columns, min_contrast)
    if len(points) < 3:
        return TiltResult(ok=False, reason_code="no_edge")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    slope, _intercept, residual = fit_line(xs, ys)
    if reject_sigma > 0 and residual > 0:
        keep = []
        for x, y in points:
            predicted = _intercept + slope * x
            if abs(y - predicted) <= reject_sigma * residual:
                keep.append((x, y))
        if len(keep) >= 3 and len(keep) < len(points):
            xs = [p[0] for p in keep]
            ys = [p[1] for p in keep]
            slope, _intercept, residual = fit_line(xs, ys)
    tilt_deg = math.degrees(math.atan(slope))
    width = float(max(1, band[2]))
    return TiltResult(
        ok=True,
        tilt_deg=tilt_deg,
        tilt_px=slope * width,
        edge_std_px=residual,
    )


class TiltMeterImpl:
    # The TiltMeter contract (shg/abc.py). It holds the measurement parameters
    # so the ROI step builds it once and calls measure() on every preview.

    # @args: columns - number of column bands; min_contrast - edge threshold;
    #        reject_sigma - outlier rejection; 0 disables it
    def __init__(self, columns: int = 64, min_contrast: float = 1.0,
                 reject_sigma: float = 3.0) -> None:
        self.columns = columns
        self.min_contrast = min_contrast
        self.reject_sigma = reject_sigma

    # @args: frame - a live frame; band - the spectral band in FRAME pixels
    # @return: the fitted tilt; ok=False with a reason when no edge fits
    def measure(self, frame: Frame, band: ROI):
        return measure_tilt(frame, band, self.columns, self.min_contrast,
                            self.reject_sigma)
