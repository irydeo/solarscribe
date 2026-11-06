############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - capture roi module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# ROI validation and preset conversion (ADR-010, design/ARCHITECTURE.md 2.2).
#
# This module turns the checks of ADR-010 into stable RoiIssue codes and the
# numbers behind each one. It returns data, never sentences: the UI composes the
# sentence with self.tr() (ADR-016), and the ROI step decides what to do with an
# ERROR. Severity is the contract: ERROR means "this ROI cannot be scanned",
# WARNING and INFO are recommendations that never block (ADR-011).
#
# Coordinates, repeated here because they are the classic bug:
#   - model.capture is SENSOR pixels, binned. It is what set_roi() takes.
#   - model.band is FRAME pixels, counted from the top-left of the delivered
#     frame. It must fit inside the frame whose size is capture.width/height.
#
# The binning check is honest about what a model alone can know. When the camera
# switches binning the caller passes the new constraints, and a rectangle saved
# at the old binning is wider than the new maximum: if it is still within
# max * binning, the two came from different binnings and BINNING_MISMATCH says
# so instead of a bare SDK_BOUNDS. The camera's actual current binning is not in
# RoiConstraints, so a perfect check is impossible here; the UI owns the
# "binning changed" event and calls us with the right constraints.

from __future__ import annotations

from solarscribe.capture.abc import (
    RoiIssue, RoiModel, RoiWarning, Severity,
)
from solarscribe.config.schema import RoiPreset
from solarscribe.devices.abc import RoiConstraints

__all__ = [
    "TARGET_FPS", "TILT_MARGIN_PX", "model_to_preset", "preset_to_model",
    "validate_roi",
]

# ADR-013: the scan needs at least 120 fps at the reference ROI. A lower rate
# is a warning, not a gate: the observer may still choose to scan slower.
TARGET_FPS = 120.0

# Height (in pixels) that must be left above band + tilt drift so the band can
# move without touching the ROI edge. Two pixels is one pixel of rounding on each
# side; the tilt itself is added separately from tilt_px.
TILT_MARGIN_PX = 2.0

# How far the band centre may sit from the capture centre before we suggest
# re-centring the slit. 10% of the ROI height keeps the recommendation useful
# without nagging on every slightly off-centre spectrum.
_BAND_CENTRE_TOLERANCE = 0.10


# @args: model - the ROI to validate
#        fps - measured or estimated frame rate, if known
# @return: the list of findings; empty means the ROI is coherent and scannable
def validate_roi(model: RoiModel, *, fps: float | None = None) -> list[RoiWarning]:
    warnings: list[RoiWarning] = []
    constraints = model.constraints
    x, y, width, height = model.capture
    band_x, band_y, band_w, band_h = model.band

    if width <= 0 or height <= 0:
        warnings.append(_warn(
            RoiIssue.SDK_BOUNDS, Severity.ERROR,
            width=width, height=height,
        ))
        return warnings

    # --- binning coherence ---------------------------------------------------
    if model.binning < 1:
        warnings.append(_warn(
            RoiIssue.BINNING_MISMATCH, Severity.ERROR,
            binning=model.binning,
        ))
    elif model.binning > 1 and (
        width > constraints.max_width or height > constraints.max_height
    ) and (
        width <= constraints.max_width * model.binning
        and height <= constraints.max_height * model.binning
    ):
        # The rectangle fits the sensor at the old binning but not at the one
        # the model declares: the preset was saved before the binning changed.
        warnings.append(_warn(
            RoiIssue.BINNING_MISMATCH, Severity.ERROR,
            binning=model.binning, width=width, height=height,
            max_width=constraints.max_width, max_height=constraints.max_height,
        ))

    # --- sensor limits and SDK multiples ------------------------------------
    out_of_bounds = (
        x < 0 or y < 0
        or width < constraints.min_width or height < constraints.min_height
        or x + width > constraints.max_width
        or y + height > constraints.max_height
        or band_x < 0 or band_y < 0
    )
    if out_of_bounds and not _has(warnings, RoiIssue.BINNING_MISMATCH):
        warnings.append(_warn(
            RoiIssue.SDK_BOUNDS, Severity.ERROR,
            x=x, y=y, width=width, height=height,
            max_width=constraints.max_width, max_height=constraints.max_height,
        ))

    if (
        x % constraints.offset_multiple
        or y % constraints.offset_multiple
        or width % constraints.width_multiple
        or height % constraints.height_multiple
    ):
        warnings.append(_warn(
            RoiIssue.SDK_MULTIPLE, Severity.ERROR,
            x=x, y=y, width=width, height=height,
            width_multiple=constraints.width_multiple,
            height_multiple=constraints.height_multiple,
            offset_multiple=constraints.offset_multiple,
        ))

    # --- the spectral band must fit inside the frame ------------------------
    if (
        band_w <= 0 or band_h <= 0
        or band_x + band_w > width or band_y + band_h > height
    ):
        warnings.append(_warn(
            RoiIssue.BAND_CLIPPED, Severity.WARNING,
            band_x=band_x, band_y=band_y,
            band_width=band_w, band_height=band_h,
            frame_width=width, frame_height=height,
        ))

    # --- the tilt drift must fit above the band -----------------------------
    needed = band_h + abs(model.tilt_px) + TILT_MARGIN_PX
    if height < needed:
        warnings.append(_warn(
            RoiIssue.TILT_HEIGHT, Severity.ERROR,
            capture_height=height, band_height=band_h,
            tilt_px=abs(model.tilt_px), margin=TILT_MARGIN_PX,
            needed=needed, deficit=needed - height,
        ))

    # --- the slit and the spectrum should be centred ------------------------
    capture_centre = height / 2.0
    band_centre = band_y + band_h / 2.0
    offset = band_centre - capture_centre
    tolerance = max(1.0, _BAND_CENTRE_TOLERANCE * height)
    if abs(offset) > tolerance:
        warnings.append(_warn(
            RoiIssue.SLIT_OFF_CENTRE, Severity.WARNING,
            offset_px=offset, tolerance_px=tolerance,
            capture_centre_px=capture_centre, band_centre_px=band_centre,
        ))

    # --- rate budget ---------------------------------------------------------
    if fps is not None and fps < TARGET_FPS:
        warnings.append(_warn(
            RoiIssue.LOW_RATE, Severity.WARNING,
            fps=float(fps), target_fps=TARGET_FPS,
            deficit_fps=TARGET_FPS - float(fps),
        ))

    return warnings


# @args: preset - the two rectangles saved in the profile
#        constraints - the camera limits at the current binning
#        binning - the binning the rectangles refer to
#        tilt_deg, tilt_px - last measured tilt, if known
# @return: a RoiModel without arithmetic: both formats use the same units
def preset_to_model(
    preset: RoiPreset,
    constraints: RoiConstraints,
    *,
    binning: int = 1,
    tilt_deg: float = 0.0,
    tilt_px: float = 0.0,
) -> RoiModel:
    return RoiModel(
        capture=tuple(preset.capture),
        band=tuple(preset.band),
        constraints=constraints,
        binning=binning,
        tilt_deg=tilt_deg,
        tilt_px=tilt_px,
    )


# @args: model - the live model
#        name - preset name to store
# @return: the RoiPreset the profile persists; only the two rectangles
def model_to_preset(model: RoiModel, name: str = "default") -> RoiPreset:
    return RoiPreset(name=name, capture=tuple(model.capture),
                     band=tuple(model.band))


# @args: issue, severity, **args - the numbers the UI sentence needs
# @return: a frozen RoiWarning
def _warn(issue: RoiIssue, severity: Severity, **args: float) -> RoiWarning:
    return RoiWarning(issue=issue, severity=severity, args=dict(args))


# @args: warnings - findings so far; issue - the code to look for
# @return: whether the code is already present
def _has(warnings: list[RoiWarning], issue: RoiIssue) -> bool:
    return any(warning.issue is issue for warning in warnings)
