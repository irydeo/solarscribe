############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg tilt test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Anchors: the slope of a line is tan(angle) by definition, and the drift in
# pixels across the width is slope*width. A synthetic edge built as
# y = h/2 + slope*x is the external geometric reference; the fit must recover
# the slope that generated it. ADR-022: edge_std_px is the straightness, so a
# noisy edge must show a large residual.

import math

import numpy as np
import pytest

from solarscribe.shg import tilt

from .test_shg_support import FakeFrame, edge_frame


def test_fit_line_is_ordinary_least_squares():
    slope, intercept, residual = tilt.fit_line([0, 1, 2], [1, 3, 5])
    assert slope == pytest.approx(2.0)
    assert intercept == pytest.approx(1.0)
    assert residual == pytest.approx(0.0)


def test_flat_edge_has_zero_tilt():
    frame = edge_frame(width=200, height=40, slope_px_per_px=0.0)
    result = tilt.measure_tilt(frame, (0, 0, 200, 40), columns=40)
    assert result.ok
    assert result.tilt_deg == pytest.approx(0.0, abs=0.05)
    assert result.tilt_px == pytest.approx(0.0, abs=0.2)
    assert result.edge_std_px < 1.0


def test_tilted_edge_recovers_the_generating_slope():
    # The synthetic edge is y = 20 + 0.02*x, so the tilt is atan(0.02) =
    # 1.1458 deg and the drift across 200 px is 4.0 px.
    slope = 0.02
    frame = edge_frame(width=200, height=40, slope_px_per_px=slope)
    result = tilt.measure_tilt(frame, (0, 0, 200, 40), columns=64)
    assert result.ok
    assert result.tilt_deg == pytest.approx(math.degrees(math.atan(slope)),
                                            abs=0.1)
    assert result.tilt_px == pytest.approx(slope * 200.0, abs=0.3)
    assert result.edge_std_px < 1.0


def test_tilt_meter_impl_satisfies_the_contract():
    from solarscribe.shg.abc import TiltMeter
    meter = tilt.TiltMeterImpl(columns=64)
    assert isinstance(meter, TiltMeter)
    frame = edge_frame(width=200, height=40, slope_px_per_px=0.01)
    result = meter.measure(frame, (0, 0, 200, 40))
    assert result.ok
    assert result.tilt_deg == pytest.approx(math.degrees(math.atan(0.01)),
                                            abs=0.15)


def test_no_edge_is_reported_with_a_reason():
    # A flat frame has no gradient anywhere: the measurement must fail with
    # "no_edge" instead of inventing a tilt.
    frame = FakeFrame(np.zeros((40, 200), dtype=np.uint16))
    result = tilt.measure_tilt(frame, (0, 0, 200, 40), columns=40)
    assert not result.ok
    assert result.reason_code == "no_edge"


def test_a_noisy_edge_has_a_large_straightness_residual():
    # A random edge is not a line: the fit may exist, but edge_std_px must say
    # the figure is not trustworthy (ADR-022).
    rng = np.random.default_rng(1234)
    data = np.zeros((60, 200), dtype=np.uint16)
    for x in range(200):
        edge = 30 + int(rng.integers(-8, 9))
        data[edge:, x] = 1000
    frame = FakeFrame(data)
    result = tilt.measure_tilt(frame, (0, 0, 200, 60), columns=64,
                              reject_sigma=0.0)
    assert result.ok
    assert result.edge_std_px > 2.0
