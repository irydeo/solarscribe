############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg quick recon module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Quick recon: a light, NON-authoritative preview of the solar disk from a
# captured scan (ADR-020). The UI paints it only to judge whether the sweep
# went well. It is not post-processing: no alignment, no flat field, no
# stacking quality, no deconvolution and no export. The real recon, stacking
# and mosaic remain external (JSol'Ex and the nightscribe-scan tools, ADR-018).
#
# How it works, and why it is cheap:
#   - Each captured frame is a spectrum: the slit axis is the frame width and
#     the dispersion is the frame height. The band ROI is collapsed along the
#     dispersion axis (mean over the spectral rows), which leaves one intensity
#     per slit position.
#   - The scan moves the Sun across the slit, so stacking those 1D profiles in
#     time reconstructs the disk. That is the same chord geometry the scan
#     relies on: at scan position x the lit slit length is 2*sqrt(R^2 - x^2).
#   - The result is downsampled to a small image and normalised to 0..1, which
#     is what a preview painter needs. The whole thing is a few numpy passes
#     over the frames, no SER writing and no Qt.
#
# Honest limits, stated here because the UI must not present it as a result:
#   - It is a preview, not a calibrated image: the band is averaged, so the
#     spectral information is gone; the tilt and the 1/cos(Dec) sampling are
#     not corrected; there is no alignment between frames.
#   - The normalisation removes the absolute brightness, so it cannot be used
#     for photometry.
#   - A mosaic row is stacked by `row_step_px`; the caller must pass the step
#     it wants. The default concatenates the rows without overlap. Overlapping
#     rows are summed, so the overlap looks brighter: the preview is not
#     photometric and the caller should pass the real step to avoid a seam.
#   - It does not read SER files: the UI passes the frames it already has, so
#     shg never imports capture (ARCHITECTURE 1) and never touches a driver.

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from solarscribe.devices.abc import ROI, Frame

from .analysis import frame_array

__all__ = [
    "ReconResult",
    "frame_profile",
    "quick_recon",
    "recon_row",
]

# The preview is small on purpose: a 256 px wide image is enough to see the
# disk and cheap enough to paint while the session keeps running.
DEFAULT_WIDTH = 256
DEFAULT_MAX_HEIGHT = 128


@dataclass(frozen=True)
class ReconResult:
    # The preview. `image` is float32 in [0, 1]; the caller owns it and paints
    # it. `reason_code` is a stable key, not a sentence (ADR-014, ADR-016):
    # "no_frames", "band_empty" or "low_contrast".
    ok: bool
    image: np.ndarray
    width: int
    height: int
    frames_used: int
    rows: int
    reason_code: str = ""


# @args: frame - a Frame contract or a 2D numpy array
# @return: the frame as a 2D numpy array
def _as_array(frame: Frame | np.ndarray) -> np.ndarray:
    if isinstance(frame, np.ndarray):
        return frame
    return frame_array(frame)


# @args: array - a 2D frame; roi - band in FRAME pixels, or None for all
# @return: the cropped band, or None when the band does not intersect
def _crop(array: np.ndarray, roi: ROI | None) -> np.ndarray | None:
    if roi is None:
        return array
    x, y, w, h = roi
    x0 = max(0, int(x))
    y0 = max(0, int(y))
    x1 = min(array.shape[1], x0 + int(w))
    y1 = min(array.shape[0], y0 + int(h))
    if x1 <= x0 or y1 <= y0:
        return None
    return array[y0:y1, x0:x1]


# @args: values - 1D array; out - output length
# @return: the block mean of `values` resampled to `out` samples
# A plain block mean, not an interpolation: it is a preview, and averaging
# keeps the brightness of a slit column instead of inventing values between
# pixels.
def _block_mean_1d(values: np.ndarray, out: int) -> np.ndarray:
    if out <= 0:
        return np.zeros(0, dtype=np.float32)
    edges = np.linspace(0, values.size, out + 1).astype(int)
    result = np.empty(out, dtype=np.float32)
    for i in range(out):
        start = edges[i]
        stop = edges[i + 1]
        result[i] = float(np.mean(values[start:stop])) if stop > start else 0.0
    return result


# @args: array - 2D array; height, width - output size
# @return: the block-mean resized array
# Rows first, then columns: each pass is O(n*out), far inside the preview
# budget even for a few hundred frames.
def _resize_mean(array: np.ndarray, height: int, width: int) -> np.ndarray:
    rows = np.vstack([_block_mean_1d(row, width) for row in array]) \
        if array.size else np.zeros((0, width), dtype=np.float32)
    if rows.shape[0] == 0:
        return np.zeros((0, width), dtype=np.float32)
    if rows.shape[0] == height:
        return rows
    edges = np.linspace(0, rows.shape[0], height + 1).astype(int)
    result = np.empty((height, width), dtype=np.float32)
    for i in range(height):
        start = edges[i]
        stop = edges[i + 1]
        result[i] = np.mean(rows[start:stop], axis=0) if stop > start else 0.0
    return result


# @args: frame - a Frame contract or a 2D numpy array
#        band - spectral band in FRAME pixels, or None for the whole frame
# @return: one intensity per slit position (mean over the band rows), or None
# The mean over the dispersion axis is the cheap collapse: the spectrum lines
# average out and what remains is the illuminated slit, which is the chord the
# scan needs.
def frame_profile(frame: Frame | np.ndarray,
                  band: ROI | None = None) -> np.ndarray | None:
    array = _as_array(frame)
    cropped = _crop(array, band)
    if cropped is None or cropped.size == 0:
        return None
    return np.mean(cropped.astype(np.float32), axis=0)


# @args: frames - the frames of one scan, in scan order
#        band - spectral band in FRAME pixels, or None
#        width - output width (slit axis)
#        max_height - output height (scan axis) before the rows are stacked
# @return: the row image (float32, not normalised), or None when no profile
# The row image has one row per captured frame (downsampled to max_height), so
# the scan axis is time and the slit axis is space. The caller normalises it
# after stacking the mosaic rows.
def recon_row(frames: Sequence[Frame | np.ndarray],
              band: ROI | None = None,
              width: int = DEFAULT_WIDTH,
              max_height: int = DEFAULT_MAX_HEIGHT) -> np.ndarray | None:
    profiles: list[np.ndarray] = []
    for frame in frames:
        profile = frame_profile(frame, band)
        if profile is not None:
            profiles.append(profile)
    if not profiles:
        return None
    stacked = np.vstack(profiles).astype(np.float32)
    out_height = max(1, min(int(max_height), stacked.shape[0]))
    return _resize_mean(stacked, out_height, max(1, int(width)))


# @args: rows - one or more scans, each a sequence of frames
#        band - spectral band in FRAME pixels, or None
#        width - output width
#        max_height - output height cap
#        row_step_px - vertical step between mosaic rows; 0 concatenates
# @return: the ReconResult with a normalised 0..1 preview
# The row step is the caller's geometry: a mosaic row that overlaps its
# neighbour by a few pixels passes the step in output pixels. The preview does
# not try to align rows; that is post-processing and out of scope (ADR-020).
def quick_recon(rows: Sequence[Sequence[Frame | np.ndarray]],
                band: ROI | None = None,
                width: int = DEFAULT_WIDTH,
                max_height: int = DEFAULT_MAX_HEIGHT,
                row_step_px: int = 0) -> ReconResult:
    if not rows:
        return ReconResult(False, np.zeros((0, 0), dtype=np.float32),
                           0, 0, 0, 0, "no_frames")
    seen_frames = any(len(row) > 0 for row in rows)
    row_images: list[np.ndarray] = []
    frames_used = 0
    for row in rows:
        frames_used += len(row)
        image = recon_row(row, band, width, max_height)
        if image is not None and image.size:
            row_images.append(image)
    if not row_images:
        reason = "band_empty" if seen_frames else "no_frames"
        return ReconResult(False, np.zeros((0, 0), dtype=np.float32),
                           0, 0, frames_used, 0, reason)

    out_width = max(1, int(width))
    if row_step_px <= 0 or len(row_images) == 1:
        canvas = np.vstack(row_images)
        step = row_images[0].shape[0]
    else:
        step = max(1, min(int(row_step_px), row_images[0].shape[0]))
        total = row_images[0].shape[0] + step * (len(row_images) - 1)
        canvas = np.zeros((total, out_width), dtype=np.float32)
        for index, image in enumerate(row_images):
            start = index * step
            canvas[start:start + image.shape[0]] += image

    if canvas.shape[0] > max_height:
        canvas = _resize_mean(canvas, max_height, out_width)
    elif canvas.shape[1] != out_width:
        canvas = _resize_mean(canvas, canvas.shape[0], out_width)

    low = float(np.min(canvas))
    high = float(np.max(canvas))
    if high - low <= 0:
        return ReconResult(True, np.zeros_like(canvas), out_width,
                           canvas.shape[0], frames_used, len(row_images),
                           "low_contrast")
    image = (canvas - low) / (high - low)
    return ReconResult(True, image.astype(np.float32), out_width,
                       image.shape[0], frames_used, len(row_images), "")
