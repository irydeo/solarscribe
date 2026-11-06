############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ROI validation test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# ADR-010's validation list, one test per code. The codes and severities are the
# contract: the UI translates them, and only ERROR may disable the scan action.

import pytest

from solarscribe.capture.abc import RoiIssue, RoiModel, Severity
from solarscribe.capture.roi import (
    TARGET_FPS, model_to_preset, preset_to_model, validate_roi,
)
from solarscribe.config.schema import RoiPreset
from solarscribe.devices.abc import RoiConstraints


def _constraints(**overrides):
    values = dict(max_width=3480, max_height=248, width_multiple=8,
                  height_multiple=2, offset_multiple=8)
    values.update(overrides)
    return RoiConstraints(**values)


def _model(capture=(0, 0, 3480, 248), band=(0, 40, 3480, 160), **kwargs):
    return RoiModel(
        capture=capture, band=band, constraints=_constraints(
            **kwargs.pop("constraint_overrides", {}),
        ),
        **kwargs,
    )


def _issues(warnings):
    return [warning.issue for warning in warnings]


def test_a_reference_roi_is_clean():
    # 3480x248, band 40..200, no tilt: the geometry of the reference camera.
    assert validate_roi(_model(), fps=TARGET_FPS) == []


def test_band_outside_the_frame_is_clipped():
    warnings = validate_roi(_model(band=(0, 100, 3480, 160)))
    assert RoiIssue.BAND_CLIPPED in _issues(warnings)
    warning = next(w for w in warnings if w.issue is RoiIssue.BAND_CLIPPED)
    assert warning.severity is Severity.WARNING
    assert warning.args["band_height"] == 160
    assert warning.args["frame_height"] == 248


def test_a_band_with_tilt_that_does_not_fit_is_an_error():
    warnings = validate_roi(_model(band=(0, 20, 3480, 200), tilt_px=60.0))
    assert RoiIssue.TILT_HEIGHT in _issues(warnings)
    warning = next(w for w in warnings if w.issue is RoiIssue.TILT_HEIGHT)
    assert warning.severity is Severity.ERROR
    assert warning.args["needed"] > warning.args["capture_height"]
    assert warning.args["tilt_px"] == pytest.approx(60.0)


def test_sdk_multiples_are_enforced():
    warnings = validate_roi(_model(
        capture=(4, 0, 3472, 248),
        constraint_overrides={"offset_multiple": 8},
    ))
    # x=4 breaks the offset multiple; it is inside the sensor, so no bounds.
    assert RoiIssue.SDK_MULTIPLE in _issues(warnings)
    assert RoiIssue.SDK_BOUNDS not in _issues(warnings)

    warnings = validate_roi(_model(
        capture=(0, 0, 3481, 248),
        constraint_overrides={"width_multiple": 8},
    ))
    assert RoiIssue.SDK_MULTIPLE in _issues(warnings)


def test_out_of_bounds_is_an_error():
    warnings = validate_roi(_model(
        capture=(0, 0, 3480, 248),
        constraint_overrides={"max_height": 200},
    ))
    assert RoiIssue.SDK_BOUNDS in _issues(warnings)
    assert next(w for w in warnings
                if w.issue is RoiIssue.SDK_BOUNDS).severity is Severity.ERROR


def test_rectangles_from_another_binning_are_reported_as_a_mismatch():
    # A rect saved at binning 1 (3480x248) used with binning-2 limits (1740x124)
    # is wider than the maximum but still inside max * binning: that is a
    # binning mismatch, not a plain out-of-bounds.
    warnings = validate_roi(_model(
        binning=2,
        constraint_overrides={"max_width": 1740, "max_height": 124},
    ))
    assert RoiIssue.BINNING_MISMATCH in _issues(warnings)
    assert RoiIssue.SDK_BOUNDS not in _issues(warnings)
    assert next(w for w in warnings
                if w.issue is RoiIssue.BINNING_MISMATCH).severity is Severity.ERROR


def test_invalid_binning_is_an_error():
    warnings = validate_roi(_model(binning=0))
    assert RoiIssue.BINNING_MISMATCH in _issues(warnings)


def test_low_rate_is_a_warning_not_a_gate():
    warnings = validate_roi(_model(), fps=60.0)
    rate = next(w for w in warnings if w.issue is RoiIssue.LOW_RATE)
    assert rate.severity is Severity.WARNING
    assert rate.args["target_fps"] == TARGET_FPS
    assert rate.args["fps"] == pytest.approx(60.0)


def test_a_band_far_from_the_centre_suggests_re_centring_the_slit():
    warnings = validate_roi(_model(band=(0, 0, 3480, 40)))
    assert RoiIssue.SLIT_OFF_CENTRE in _issues(warnings)
    warning = next(w for w in warnings
                   if w.issue is RoiIssue.SLIT_OFF_CENTRE)
    assert warning.severity is Severity.WARNING
    assert warning.args["offset_px"] < 0      # band above the centre


def test_preset_and_model_round_trip_without_arithmetic():
    preset = RoiPreset(name="ref", capture=(0, 0, 3480, 248),
                       band=(0, 40, 3480, 160))
    model = preset_to_model(preset, _constraints(), binning=1)
    assert model.capture == preset.capture
    assert model.band == preset.band
    assert model.binning == 1

    model.set_tilt(0.4, 1.7)
    back = model_to_preset(model, "saved")
    assert back.name == "saved"
    assert back.capture == model.capture
    assert back.band == model.band
    # Only the two rectangles are persisted; tilt lives in the model and the
    # INI hint, not in the preset (ARCHITECTURE 3.2).
    assert not hasattr(back, "tilt_deg")
