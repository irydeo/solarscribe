############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg analysis module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Measurements on a live frame: the analysis regions, the left/right means of
# the slit axis, the illuminated slit extent and the centring centroid.
#
# The science lives here, not in devices (ARCHITECTURE 2.1): FrameStats is only
# a mean and a standard deviation, so shg reads Frame.data with numpy for
# everything else. That keeps the capture thread cheap and the measurement
# reproducible.
#
# Frame pixels: every ROI in this module is in FRAME pixels, counted from the
# top-left corner of the delivered frame (ARCHITECTURE 2). The capture ROI is
# in SENSOR pixels and is only used for its width and height, which are the
# frame dimensions.
#
# Physical anchors:
#   - The illuminated extent along the slit is the chord of the solar disk at
#     the slit position, L = 2*sqrt(R^2 - q^2): maximal at the disk centre and
#     zero at the limb (ADR-006).
#   - The centroid of the illuminated profile is the first moment of the
#     intensity distribution; for a symmetric disk it is the disk centre, so
#     its offset is a direct measure of the Dec error.
#   - The normalized imbalance (L-R)/(L+R) cancels the exposure, because
#     scaling both halves by the same factor leaves the ratio unchanged. That
#     is what makes the prototype's coarse loop usable at any gain.

from __future__ import annotations

import numpy as np

from solarscribe.devices.abc import ROI, Frame

__all__ = [
    "analysis_regions",
    "bright_fraction",
    "column_means",
    "dec_balance",
    "frame_array",
    "illuminated_columns",
    "left_right_means",
    "measure_left_right_means",
    "measure_percentile_pixel",
    "measure_slit_extent_px",
    "percentile_value",
    "region_mean",
    "region_std",
    "roi_array",
    "subdivide_roi",
    "symmetry_centroid_offset_px",
]

# The prototype (measure_slit_extent_px) calls a band illuminated when its mean
# is above the dark floor plus a quarter of the dark-to-bright span. The 0.25
# is deliberately low: the slit ends fade, and the extent is used to estimate a
# scale to a few percent, not to draw a hard edge.
SLIT_EXTENT_THRESHOLD = 0.25


# @args: frame - a delivered frame
# @return: the frame as a 2D numpy array (height, width)
# Frame.data is a C-contiguous memoryview (devices.abc), so frombuffer is a
# zero-copy view for a full frame and a cheap reshape. A test may hand a numpy
# array directly; both paths are accepted.
def frame_array(frame: Frame) -> np.ndarray:
    data = frame.data
    if isinstance(data, np.ndarray):
        array = data
    else:
        array = np.frombuffer(data, dtype=frame.dtype)
    return array.reshape(frame.height, frame.width)


# @args: roi - region in FRAME pixels
#        width, height - frame dimensions, to clamp a region that overhangs
# @return: the ROI clipped to the frame
def _clamp_roi(roi: ROI, width: int, height: int) -> ROI:
    x, y, w, h = roi
    x0 = max(0, min(int(x), width))
    y0 = max(0, min(int(y), height))
    x1 = max(x0, min(int(x) + int(w), width))
    y1 = max(y0, min(int(y) + int(h), height))
    return (x0, y0, x1 - x0, y1 - y0)


# @args: frame - a delivered frame
#        roi - region in FRAME pixels
# @return: the region as a 2D numpy array; raises ValueError if it is empty
def roi_array(frame: Frame, roi: ROI) -> np.ndarray:
    x, y, w, h = _clamp_roi(roi, frame.width, frame.height)
    if w <= 0 or h <= 0:
        raise ValueError("the ROI is empty after clipping to the frame")
    return frame_array(frame)[y:y + h, x:x + w]


# @args: frame - a delivered frame; roi - region in FRAME pixels
# @return: the mean pixel value of the region
def region_mean(frame: Frame, roi: ROI) -> float:
    return float(np.mean(roi_array(frame, roi)))


# @args: frame - a delivered frame; roi - region in FRAME pixels
# @return: the population standard deviation of the region
# Population (ddof=0), the same definition SharpCap's GetStats and the
# prototype's limb threshold use.
def region_std(frame: Frame, roi: ROI) -> float:
    return float(np.std(roi_array(frame, roi)))


# @args: frame - a delivered frame
#        left - left half of the slit in FRAME pixels
#        right - right half of the slit in FRAME pixels
# @return: (left mean, right mean)
# At the disk centre the slit is illuminated symmetrically, so the two means
# are equal (ADR-006). This is the prototype's measure_left_right_means,
# without the camera event plumbing: the engine already owns the frame.
def left_right_means(frame: Frame, left: ROI, right: ROI) -> tuple[float, float]:
    return region_mean(frame, left), region_mean(frame, right)


# @args: left_mean - mean of the left half
#        right_mean - mean of the right half
# @return: (left - right) / (left + right), or None when both are dark
# The normalization removes the exposure: doubling the light doubles both
# means and leaves the ratio unchanged. + means the left (north) half is
# brighter, so the Sun is pushed north and Dec must come down.
def dec_balance(left_mean: float, right_mean: float) -> float | None:
    total = left_mean + right_mean
    if total <= 0:
        return None
    return (left_mean - right_mean) / total


# @args: frame - a delivered frame
#        roi - region in FRAME pixels
#        pct - cumulative percentile in [0, 1]
# @return: the pixel value at that percentile
# The prototype uses pct=0.995 for auto-exposure and the coarse centring: a
# few hot pixels must not move the figure, but the bright continuum peak must.
# numpy's linear interpolation is the standard definition of a percentile.
def percentile_value(frame: Frame, roi: ROI, pct: float) -> float:
    return float(np.percentile(roi_array(frame, roi), pct * 100.0))


# @args: frame - a delivered frame
#        roi - region in FRAME pixels
#        threshold - pixel value above which a pixel is bright
# @return: the fraction of pixels strictly above the threshold, [0, 1]
def bright_fraction(frame: Frame, roi: ROI, threshold: float) -> float:
    values = roi_array(frame, roi)
    if values.size == 0:
        return 0.0
    return float(np.count_nonzero(values > threshold)) / float(values.size)


# @args: frame - a delivered frame
#        roi - region in FRAME pixels
#        columns - number of bands along the slit axis
# @return: one mean per band, left to right
# The slit runs along the frame width; dividing it into bands is the cheap
# profile the prototype uses (SLIT_EXTENT_BANDS = 48) instead of a per-column
# loop. linspace covers the full width, so no pixel at the right edge is lost.
def column_means(frame: Frame, roi: ROI, columns: int) -> list[float]:
    if columns <= 0:
        raise ValueError("columns must be positive")
    x, y, w, h = _clamp_roi(roi, frame.width, frame.height)
    if w <= 0 or h <= 0:
        raise ValueError("the ROI is empty after clipping to the frame")
    values = frame_array(frame)[y:y + h, x:x + w]
    edges = np.linspace(0, w, columns + 1).astype(int)
    means: list[float] = []
    for i in range(columns):
        start = edges[i]
        stop = edges[i + 1]
        if stop <= start:
            means.append(0.0)
        else:
            means.append(float(np.mean(values[:, start:stop])))
    return means


# @args: means - profile of band means along the slit
#        band_px - width of one band in pixels
# @return: (first illuminated band index, last illuminated band index)
# None when the profile is flat or has no band above the threshold. The
# threshold is lo + 0.25*(hi-lo), the prototype's rule.
def illuminated_columns(means: list[float], band_px: int = 1) -> tuple[int, int] | None:
    if not means:
        return None
    lo = min(means)
    hi = max(means)
    if hi <= lo:
        return None
    threshold = lo + SLIT_EXTENT_THRESHOLD * (hi - lo)
    on = [i for i, value in enumerate(means) if value > threshold]
    if not on:
        return None
    return on[0], on[-1]


# @args: means - profile of band means along the slit
#        band_px - width of one band in pixels
# @return: illuminated extent along the slit, pixels (0 when no profile)
# The extent is (last - first + 1) bands, capped at the profile length. It is
# the chord of the solar disk at the slit, so at the disk centre it is the full
# diameter and it is what gives the slit plate scale (geometry.
# slit_plate_scale_arcsec_px).
def measure_slit_extent_px(means: list[float], band_px: int) -> float:
    found = illuminated_columns(means, band_px)
    if found is None:
        return 0.0
    first, last = found
    extent = (last - first + 1) * max(1, int(band_px))
    return float(min(extent, len(means) * max(1, int(band_px))))


# @args: means - profile of band means along the slit
#        band_px - width of one band in pixels
# @return: offset of the intensity centroid from the profile centre, pixels
# The first moment of the illumination is the disk centre along the slit when
# the disk fits there. Subtracting the darkest band removes the sensor
# pedestal and the stray light, so the centroid is not dragged by the
# background. None when the profile has no signal.
def symmetry_centroid_offset_px(means: list[float], band_px: int) -> float | None:
    if not means:
        return None
    values = np.asarray(means, dtype=float)
    weights = np.clip(values - float(np.min(values)), 0.0, None)
    total = float(np.sum(weights))
    if total <= 0:
        return None
    index = np.arange(values.size, dtype=float)
    centroid = float(np.sum(index * weights) / total)
    centre = (values.size - 1) / 2.0
    return (centroid - centre) * max(1, int(band_px))


# @args: roi - a rectangle in FRAME pixels; columns - number of bands
# @return: one ROI per band along the x axis
# The limb detection subdivides the "limb" region into columns internally
# (ARCHITECTURE 2.3: the columns are not part of the contract).
def subdivide_roi(roi: ROI, columns: int) -> list[ROI]:
    if columns <= 0:
        raise ValueError("columns must be positive")
    x, y, w, h = roi
    edges = np.linspace(0, w, columns + 1).astype(int)
    result: list[ROI] = []
    for i in range(columns):
        start = edges[i]
        stop = edges[i + 1]
        if stop > start:
            result.append((x + int(start), y, int(stop - start), h))
    return result


# @args: capture - hardware ROI in SENSOR pixels; its size is the frame size
#        band - spectral band in FRAME pixels
# @return: the analysis regions in FRAME pixels, keyed "left", "right", "limb"
# The implementation of the contract declared in shg/abc.py (analysis_regions).
# "left" and "right" split the band at its middle along the slit axis, which is
# the frame width; "limb" is the whole band. The band is clamped to the frame
# so a stale preset cannot ask numpy to read outside the data.
def analysis_regions(capture: ROI, band: ROI) -> dict[str, ROI]:
    width = int(capture[2])
    height = int(capture[3])
    x, y, w, h = _clamp_roi(band, width, height)
    if w <= 0 or h <= 0:
        raise ValueError("the band does not intersect the frame")
    middle = w // 2
    left = (x, y, middle, h)
    right = (x + middle, y, w - middle, h)
    return {"left": left, "right": right, "limb": (x, y, w, h)}


# Prototype names. The prototype measured the means and the percentile through
# the camera event; here the frame is already in hand, so the functions take it
# directly and the engine keeps the capture thread free.
measure_left_right_means = left_right_means
measure_percentile_pixel = percentile_value
