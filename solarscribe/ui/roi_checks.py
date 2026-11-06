############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui roi checks module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The UI's only arithmetic: turning a RoiModel into the warnings the ROI step
# shows. No Qt here, so cli can call it for the dry run.
#
# The owner of this check is capture/roi.py (valldate_roi, ADR-010, ADR-023) and
# this module delegates to it as soon as it exists. The fallback below covers
# the same documented issues with the same codes and the same numbers, so the
# step is usable and testable until video lands its module. It never invents a
# code: every warning is one of RoiIssue.

from __future__ import annotations

from solarscribe.capture.abc import RoiIssue, RoiModel, RoiWarning, Severity
from solarscribe.config.schema import default_value

__all__ = ["validate_roi_model"]

# The margin the ROI keeps between the spectral band and the edge once the tilt
# has been added, in pixels. Two pixels is small on purpose: it catches the
# usual "band glued to the edge" mistake without wasting height.
TILT_MARGIN_PX = 2.0


# @args: model - the rectangles, the sensor constraints and the measured tilt
#        fps - the estimated rate of this ROI, or None when it is not known
# @return: the findings, errors first. Delegates to capture/roi.py when it is
#          importable (ADR-010); otherwise runs the documented fallback
def validate_roi_model(model: RoiModel, fps: float | None = None) -> list[RoiWarning]:
    try:
        from solarscribe.capture.roi import validate_roi  # type: ignore
    except (ImportError, AttributeError):
        return _fallback(model, fps)
    try:
        return list(validate_roi(model, fps=fps))
    except TypeError:
        # An older signature without the keyword: still better than no check.
        return list(validate_roi(model))


# @args: model - the ROI model; fps - estimated rate or None
# @return: the findings of the fallback checks, in the order a user reads them
def _fallback(model: RoiModel, fps: float | None) -> list[RoiWarning]:
    warnings: list[RoiWarning] = []
    x, y, width, height = model.capture
    band_x, band_y, band_w, band_h = model.band
    limits = model.constraints

    # 1. The rectangle must exist and stay on the sensor. An SDK rejects it
    #    instead of cropping silently, so this is an error, not advice.
    right = x + width
    bottom = y + height
    if (x < 0 or y < 0 or width < limits.min_width or height < limits.min_height
            or right > limits.max_width or bottom > limits.max_height):
        warnings.append(RoiWarning(
            issue=RoiIssue.SDK_BOUNDS,
            severity=Severity.ERROR,
            args={
                "x": float(x), "y": float(y),
                "right": float(right), "bottom": float(bottom),
                "max_width": float(limits.max_width),
                "max_height": float(limits.max_height),
                "min_width": float(limits.min_width),
                "min_height": float(limits.min_height),
            },
        ))
        return warnings

    # 2. The SDK's alignment rules: a width the sensor will not produce is a
    #    failed configure(), not a slow frame.
    for value, multiple, axis in (
        (width, limits.width_multiple, "width"),
        (height, limits.height_multiple, "height"),
        (x, limits.offset_multiple, "x"),
        (y, limits.offset_multiple, "y"),
    ):
        if multiple > 1 and value % multiple:
            warnings.append(RoiWarning(
                issue=RoiIssue.SDK_MULTIPLE,
                severity=Severity.ERROR,
                args={"axis": axis, "value": float(value),
                      "multiple": float(multiple)},
            ))

    # 3. The spectral band lives in FRAME pixels, so it must fit inside the
    #    delivered frame. A clipped band loses part of the spectrum, which the
    #    reconstruction cannot get back.
    if (band_x < 0 or band_y < 0 or band_w <= 0 or band_h <= 0
            or band_x + band_w > width or band_y + band_h > height):
        warnings.append(RoiWarning(
            issue=RoiIssue.BAND_CLIPPED,
            severity=Severity.ERROR,
            args={
                "band_x": float(band_x), "band_y": float(band_y),
                "band_w": float(band_w), "band_h": float(band_h),
                "frame_w": float(width), "frame_h": float(height),
            },
        ))

    # 4. A tilted line needs a taller frame; the drift is a straight count of
    #    pixels across the width (ADR-022).
    needed = band_h + abs(model.tilt_px) + TILT_MARGIN_PX
    if height < needed:
        warnings.append(RoiWarning(
            issue=RoiIssue.TILT_HEIGHT,
            severity=Severity.WARNING,
            args={"height": float(height), "band_height": float(band_h),
                  "tilt_px": float(abs(model.tilt_px)),
                  "margin": TILT_MARGIN_PX, "needed": float(needed)},
        ))

    # 5. The rate is a recommendation, never a gate: a slow ROI still scans,
    #    it just takes longer and the Sun moves further.
    if fps is not None:
        target = float(default_value("capture", "target_fps"))
        if fps < target:
            warnings.append(RoiWarning(
                issue=RoiIssue.LOW_RATE,
                severity=Severity.WARNING,
                args={"fps": float(fps), "target": target},
            ))

    # 6. The slit should sit near the middle of the ROI. This is information:
    #    the scan works, but one side has less margin.
    slit_centre = band_x + band_w / 2.0
    roi_centre = width / 2.0
    offset = abs(slit_centre - roi_centre)
    if band_w <= width and offset > 2.0:
        warnings.append(RoiWarning(
            issue=RoiIssue.SLIT_OFF_CENTRE,
            severity=Severity.INFO,
            args={"offset": float(offset)},
        ))

    warnings.sort(key=lambda item: _severity_rank(item.severity))
    return warnings


# @args: severity - the finding's severity
# @return: an order so errors are read first
def _severity_rank(severity: Severity) -> int:
    return {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}[severity]
