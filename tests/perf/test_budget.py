############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - performance budget consistency test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The budget in tests/perf/budget.py is the gate; the INI defaults and the
# reference geometry are the contract (ADR-003, ADR-010, ADR-013). These tests
# keep the three from drifting apart and exercise the pass/fail logic itself,
# with no simulator needed.

import pytest

from tests.perf.budget import (
    FRAME_BYTES, MAX_DROPPED_PCT, MAX_LATENCY_MS, MIN_DISK_MB_S,
    MIN_THROUGHPUT_MB_S, QUEUE_BUDGET_MB, REFERENCE_BAND, REFERENCE_CAPTURE,
    TARGET_FPS, Measurement, checks, report_markdown, violations,
)


def test_reference_frame_arithmetic_matches_the_adr():
    # ADR-013: 1.73 MB/frame at 16 bit, 1.73 MB x 120 = ~207 MB/s.
    assert FRAME_BYTES == 3480 * 248 * 2
    throughput = FRAME_BYTES * TARGET_FPS / 1e6
    assert 205.0 <= throughput <= 209.0, (
        f"the reference strip at {TARGET_FPS} fps gives {throughput:.2f} MB/s, "
        f"not the ~207 MB/s of ADR-013"
    )


def test_budget_matches_the_config_schema_defaults():
    from solarscribe.config.schema import default_value

    assert default_value("capture", "target_fps") == TARGET_FPS
    assert default_value("capture", "queue_budget_mb") == QUEUE_BUDGET_MB
    assert default_value("capture", "stall_timeout_s") == 3.0
    assert default_value("camera", "bit_depth") == 16


def test_reference_roi_matches_the_schema_and_the_band_fits_inside():
    from solarscribe.config.schema import default_value

    capture = tuple(
        int(default_value("roi", f"capture_{name}"))
        for name in ("x", "y", "width", "height")
    )
    band = tuple(
        int(default_value("roi", f"band_{name}"))
        for name in ("x", "y", "width", "height")
    )
    assert capture == REFERENCE_CAPTURE
    assert band == REFERENCE_BAND

    # FRAME pixels: the band is described relative to the delivered frame, so
    # it must fit inside the capture strip (the two rectangles meet here).
    cx, cy, cw, ch = REFERENCE_CAPTURE
    bx, by, bw, bh = REFERENCE_BAND
    assert bx >= 0 and by >= 0 and bx + bw <= cw and by + bh <= ch


def test_the_gate_logic_passes_a_healthy_measurement():
    healthy = Measurement(
        seconds=3.0, frames=360, fps=120.0, frame_bytes=FRAME_BYTES,
        throughput_mb_s=207.0, dropped_pct=0.0, sdk_drops=0, queue_drops=0,
        sequence_gaps=0, latency_p95_ms=20.0, capture_start_s=1.0,
        queue_high_water_mb=64.0, disk_mb_s=207.0,
        disk_capability_mb_s=1400.0, recording=True,
    )
    assert violations(healthy) == []
    verdicts = {name: verdict for name, _, _, verdict in checks(healthy)}
    assert set(verdicts.values()) == {"pass"}


@pytest.mark.parametrize(
    "field,value,metric",
    [
        ("fps", TARGET_FPS - 1.0, "fps"),
        ("throughput_mb_s", MIN_THROUGHPUT_MB_S - 1.0, "throughput"),
        ("dropped_pct", MAX_DROPPED_PCT + 0.5, "dropped"),
        ("sequence_gaps", 1, "sequence gaps"),
        ("latency_p95_ms", MAX_LATENCY_MS + 1.0, "viewer latency (p95)"),
        ("queue_high_water_mb", QUEUE_BUDGET_MB + 1.0, "queue high water"),
        ("disk_mb_s", 0.0, "disk writer"),
        ("disk_capability_mb_s", MIN_DISK_MB_S - 1.0, "disk capability"),
    ],
)
def test_the_gate_logic_fails_with_the_number(field, value, metric):
    values = dict(
        seconds=3.0, frames=360, fps=120.0, frame_bytes=FRAME_BYTES,
        throughput_mb_s=207.0, dropped_pct=0.0, sdk_drops=0, queue_drops=0,
        sequence_gaps=0, latency_p95_ms=20.0, capture_start_s=1.0,
        queue_high_water_mb=64.0, disk_mb_s=207.0,
        disk_capability_mb_s=1400.0, recording=True,
    )
    values[field] = value
    failures = violations(Measurement(**values))
    assert any(metric in failure for failure in failures), (
        f"{field}={value} did not fail {metric}: {failures}"
    )


def test_unmeasured_metrics_are_unverified_not_a_pass():
    # Without a working SER writer there is no queue figure and no disk figure;
    # the bench must say so instead of reporting a green gate.
    result = Measurement(
        seconds=3.0, frames=360, fps=120.0, frame_bytes=FRAME_BYTES,
        throughput_mb_s=207.0, sequence_gaps=0, latency_p95_ms=20.0,
        capture_start_s=1.0, recording=False,
    )
    verdicts = {name: verdict for name, _, _, verdict in checks(result)}
    assert verdicts["queue high water"] == "unverified"
    assert verdicts["disk writer"] == "unverified"
    assert verdicts["disk capability"] == "unverified"
    assert violations(result) == []


def test_report_lists_every_metric_and_the_measurement_trail():
    result = Measurement(
        seconds=3.0, frames=360, fps=120.0, frame_bytes=FRAME_BYTES,
        throughput_mb_s=207.0, sequence_gaps=0, latency_p95_ms=20.0,
        capture_start_s=1.0, recording=False,
        notes=("SER recording unavailable: example",),
    )
    report = report_markdown(result)
    for name in ("fps", "throughput", "dropped", "viewer latency", "disk"):
        assert name in report
    assert "frames: 360" in report
    assert "NOTE: SER recording unavailable" in report
