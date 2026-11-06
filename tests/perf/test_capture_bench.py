############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - capture performance gate test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The G3 gate of ADR-013 on the reference strip: sustained fps, throughput,
# dropped frames, sequence holes, viewer latency, queue high-water mark, disk
# rate, start time and RSS.
#
# Everything here is black box: the bench only speaks the devices and capture
# contracts, so these numbers describe the boundary the app uses. The whole
# module skips while the simulator or the capture engine is still missing; it
# never invents a pass for an absent implementation.

import pytest

from tests.perf.budget import (
    MAX_CAPTURE_START_S, MIN_DISK_MB_S, QUEUE_BUDGET_MB, report_markdown,
    violations,
)

pytestmark = [pytest.mark.perf, pytest.mark.sim]


def test_capture_meets_the_adr013_budget(measurement):
    # One assert with every failed metric at once: a blocked gate must show the
    # whole picture, not stop at the first number.
    report = report_markdown(measurement)
    print("\n" + report)
    failures = violations(measurement)
    assert not failures, (
        "ADR-013 budget not met:\n" + "\n".join(failures) + "\n\n" + report
    )


def test_the_start_and_rate_sources_are_sane(measurement):
    # A pass on numbers that came from nowhere is not a pass: the run must have
    # frames, the start budget must be inside the ADR figure, and the engine's
    # own fps counter must agree with the black-box count when it reports one.
    assert measurement.frames > 0
    assert measurement.capture_start_s <= MAX_CAPTURE_START_S

    engine_fps = measurement.extra("engine_fps")
    if engine_fps > 0.0:
        assert abs(engine_fps - measurement.fps) <= max(5.0, 0.05 * measurement.fps), (
            f"engine fps {engine_fps:.2f} disagrees with the measured "
            f"{measurement.fps:.2f}"
        )

    # The reference strip is what makes the throughput target meaningful.
    assert measurement.frame_bytes == 3480 * 248 * 2


def test_recording_path_is_measurable(measurement):
    # Without a working writer the queue and disk budgets are unverified, and
    # so is the dropped-frame figure under real I/O. Skipping here says so in
    # the test report instead of hiding it under a green budget test.
    if not measurement.recording:
        pytest.skip(
            "the capture engine exposed no working SER writer in this change: "
            "queue and disk budgets are unverified"
        )
    assert measurement.queue_high_water_mb <= QUEUE_BUDGET_MB
    assert measurement.disk_mb_s >= 0.98 * measurement.throughput_mb_s, (
        f"the writer did {measurement.disk_mb_s:.1f} MB/s while the stream "
        f"produced {measurement.throughput_mb_s:.1f} MB/s"
    )


def test_disk_capability_meets_the_adr013_budget(measurement):
    # The 250 MB/s of ADR-013 is what the storage must sustain, not what the
    # writer achieves on a slower stream. It is a raw fsync probe.
    if measurement.disk_capability_mb_s is None:
        pytest.skip("the platform refused the raw disk probe: unverified")
    assert measurement.disk_capability_mb_s >= MIN_DISK_MB_S


def test_viewer_latency_was_measured(measurement):
    # The DisplayBridge adds one hop after the inline consumer; this measures
    # the lower bound (frame timestamp to callback). If no frame carried a
    # usable timestamp the budget is unverified, not met.
    if measurement.latency_p95_ms is None:
        pytest.skip("no frame carried a usable timestamp: latency is unverified")
    assert measurement.latency_p95_ms <= 150.0


def test_rss_stays_bounded(measurement):
    # ADR-013 has no separate RSS figure, only "stable". The bounded queue is
    # 512 MB, so a growth beyond that over a single run can only be a leak.
    growth = measurement.rss_end_mb - measurement.rss_start_mb
    assert growth <= QUEUE_BUDGET_MB, (
        f"RSS grew {growth:.1f} MB over {measurement.seconds:.1f} s; the "
        f"bounded queue budget is {QUEUE_BUDGET_MB:.0f} MB"
    )
