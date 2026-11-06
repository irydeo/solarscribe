############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - performance harness self-test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# A bench that has never run is not a bench. Until solarscribe.capture.engine
# exists, this test drives the real harness with a minimal engine that satisfies
# the CaptureEngine contract and the real camera simulator at a small ROI. It
# checks the measurement path itself (frames, rate, throughput, latency, start,
# RSS and the graceful "unverified" recording path), NOT the ADR-013 budget: the
# product gate is test_capture_bench.py at the reference strip.
#
# The engine double is not a product module: it lives here, it implements only
# the contract methods the harness calls, and it deliberately has no SER writer
# so the recording metrics must come out unverified instead of invented.

import time

import pytest

from solarscribe.capture.abc import CaptureEngine, StreamCounters
from solarscribe.devices.abc import Camera
from tests.perf.budget import report_markdown
from tests.perf.harness import Rig, measure
from tests.support import find_camera

pytestmark = [pytest.mark.perf, pytest.mark.sim]

SMALL_CAPTURE = (0, 0, 640, 64)
SMALL_BAND = (0, 4, 640, 16)


class _HarnessEngine:
    # A CaptureEngine that forwards the stream and counts, with no writer.

    def __init__(self):
        self._camera = None
        self._callback = None
        self._stats_callback = None
        self._frames = 0
        self._first = None
        self._last = None
        self._previous_sequence = None
        self._gaps = 0
        self._running = False

    def configure(self, camera, roi, params):
        self._camera = camera

    def on_frame(self, cb):
        self._callback = cb

    def on_stats(self, cb):
        self._stats_callback = cb

    def start(self):
        self._camera.start_stream(self._dispatch)
        self._running = True

    def stop(self):
        if self._camera is not None:
            self._camera.stop_stream()
        self._running = False

    def is_running(self):
        return self._running

    def start_recording(self, path, header):
        # No writer on purpose: the harness must report the budget unverified.
        raise NotImplementedError("the self-test engine has no SER writer")

    def stop_recording(self):
        raise NotImplementedError

    def is_recording(self):
        return False

    def counters(self):
        fps = 0.0
        if self._first is not None and self._last is not None:
            span = self._last - self._first
            if span > 0:
                fps = self._frames / span
        return StreamCounters(
            frames_received=self._frames,
            frames_dropped_sdk=self._camera.dropped_frames(),
            sequence_gaps=self._gaps,
            fps=fps,
        )

    def _dispatch(self, frame):
        now = time.monotonic()
        if self._first is None:
            self._first = now
        self._last = now
        self._frames += 1
        if (
            self._previous_sequence is not None
            and frame.sequence != self._previous_sequence + 1
        ):
            self._gaps += 1
        self._previous_sequence = frame.sequence
        if self._callback is not None:
            self._callback(frame)


def test_harness_measures_a_known_source(tmp_path):
    camera, label = find_camera(width=SMALL_CAPTURE[2], height=SMALL_CAPTURE[3],
                                fps=120.0)
    if camera is None:
        pytest.skip("the camera simulator is not available")

    engine = _HarnessEngine()
    assert isinstance(camera, Camera), f"{label} does not satisfy Camera"
    assert isinstance(engine, CaptureEngine)

    rig = Rig(camera=camera, engine=engine, camera_label=label,
              engine_label="tests.perf.fake")
    result = measure(rig, 1.0, tmp_path, capture=SMALL_CAPTURE, band=SMALL_BAND)
    print("\n" + report_markdown(result))

    assert result.frames > 10
    assert result.fps > 0.0
    assert result.throughput_mb_s > 0.0
    assert result.capture_start_s <= 5.0
    assert result.latency_p95_ms is not None
    assert result.rss_end_mb > 0.0

    # No writer was offered, so the recording half must be unverified and say
    # why: that is the same path the product bench takes while the engine is
    # still being written.
    assert result.recording is False
    assert any("SER recording unavailable" in note for note in result.notes)
