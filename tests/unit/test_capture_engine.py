############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - capture engine test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The threaded pipeline of ARCHITECTURE 4. The manual simulator (fps=0) makes
# every frame deterministic and lets the test drive the capture thread itself,
# so these tests are not a timing lottery. The real-rate thread is exercised by
# tests/functional/test_capture_sim.py.

import struct
import threading
import time
from dataclasses import replace

import pytest

from solarscribe.capture.abc import (
    CaptureEngine, CaptureParams, RoiModel, SerHeader, WriterCounters,
)
from solarscribe.capture.engine import CaptureEngineImpl
from solarscribe.devices.abc import DeviceError, Param
from solarscribe.devices.sim import SimCamera


def _make(camera=None, **param_overrides):
    camera = camera or SimCamera(width=64, height=32, fps=0.0)
    engine = CaptureEngineImpl(start_timeout_s=0.0)
    area = camera.effective_area()
    roi = RoiModel(
        capture=area,
        band=(0, 8, area[2], 16),
        constraints=camera.info().caps.roi,
    )
    params = CaptureParams(auto_exposure=False, queue_budget_mb=1.0)
    params = replace(params, **param_overrides)
    engine.configure(camera, roi, params)
    return engine, camera


def _header(camera):
    area = camera.effective_area()
    return SerHeader(width=area[2], height=area[3], bit_depth=16, roi=area)


class RecordingSim(SimCamera):
    # SimCamera that remembers the parameters the engine writes.

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.calls = []

    def set_param(self, p, value):
        self.calls.append((p, value))
        super().set_param(p, value)


class BlockingWriter:
    # Writes only when released, so the bounded queue can be driven to overflow
    # deterministically instead of hoping the disk is slow.

    def __init__(self):
        self.release = threading.Event()
        self.frames = 0
        self.opened = False

    def open(self, path, header):
        self.opened = True

    def write(self, frame):
        self.release.wait(5.0)
        self.frames += 1

    def close(self):
        self.opened = False

    def counters(self):
        return WriterCounters(frames_written=self.frames)


def test_engine_satisfies_the_contract():
    engine, _ = _make()
    assert isinstance(engine, CaptureEngine)


def test_start_stop_and_counters_with_the_manual_simulator():
    engine, camera = _make()
    assert not engine.is_running()
    engine.start()
    assert engine.is_running()
    camera.emit(3)

    counters = engine.counters()
    assert counters.frames_received == 3
    assert counters.sequence_gaps == 0
    assert counters.fps > 0.0

    engine.stop()
    assert not engine.is_running()


def test_inline_consumers_receive_frames_and_stats():
    engine, camera = _make()
    frames = []
    stats = []
    engine.on_frame(frames.append)
    engine.on_stats(stats.append)
    engine.start()
    camera.emit(2)
    engine.stop()
    assert [f.sequence for f in frames] == [0, 1]
    assert len(stats) == 2
    assert stats[0].mean == pytest.approx(frames[0].stats().mean)


def test_sequence_holes_and_sdk_drops_are_counted():
    camera = SimCamera(width=64, height=32, fps=0.0, drop_every=2)
    engine, _ = _make(camera)
    engine.start()
    camera.emit(6)
    counters = engine.counters()
    engine.stop()
    assert counters.frames_received == 3          # 0, 2, 4
    assert counters.frames_dropped_sdk == 3       # 1, 3, 5
    # Only holes followed by a delivered frame are visible on the host: the
    # drop at 5 has no next sequence, so the host counts 2 and the SDK counter
    # accounts for the trailing one. This is why both counters exist.
    assert counters.sequence_gaps == 2


def test_recording_writes_a_readable_ser_and_counts():
    engine, camera = _make()
    import tempfile
    from pathlib import Path
    path = Path(tempfile.mkdtemp()) / "run.ser"
    engine.start()
    engine.start_recording(path, _header(camera))
    assert engine.is_recording()
    camera.emit(4)
    counters = engine.stop_recording()
    engine.stop()

    assert counters.frames_written == 4
    assert counters.frames_dropped_queue == 0
    raw = path.read_bytes()
    assert struct.unpack_from("<i", raw, 38)[0] == 4
    assert len(raw) == 178 + 4 * 64 * 32 * 2
    assert not engine.is_recording()


def test_queue_budget_drops_are_counted_and_never_block_capture():
    camera = SimCamera(width=64, height=32, fps=0.0)
    engine = CaptureEngineImpl(start_timeout_s=0.0, writer_factory=BlockingWriter)
    roi = RoiModel(capture=(0, 0, 64, 32), band=(0, 8, 64, 16),
                   constraints=camera.info().caps.roi)
    # 10 kB budget, 4 kB frames: two fit in the queue (one may be in flight),
    # the rest are dropped while the writer is held.
    params = CaptureParams(auto_exposure=False, queue_budget_mb=0.01)
    engine.configure(camera, roi, params)
    engine.start()
    engine.start_recording("/tmp/never.ser", _header(camera))
    started = time.monotonic()
    camera.emit(6)
    elapsed = time.monotonic() - started
    # The capture path must return immediately even with a blocked writer.
    assert elapsed < 0.5

    active_writer = engine._writer
    active_writer.release.set()
    counters = engine.stop_recording()
    engine.stop()
    assert counters.frames_written == 2
    assert counters.frames_dropped_queue == 4
    assert counters.queue_high_water_mb > 0.0


def test_configure_while_running_restarts_with_the_new_roi():
    engine, camera = _make()
    engine.start()
    new_area = (0, 0, 32, 16)
    roi = RoiModel(capture=new_area, band=(0, 4, 32, 8),
                   constraints=camera.info().caps.roi)
    engine.configure(camera, roi, CaptureParams(auto_exposure=False))
    assert engine.is_running()
    assert camera.get_roi() == new_area
    camera.emit(1)
    assert engine.counters().frames_received == 1
    engine.stop()


def test_configure_while_recording_closes_the_ser_cleanly():
    engine, camera = _make()
    engine.start()
    import tempfile
    from pathlib import Path
    path = Path(tempfile.mkdtemp()) / "partial.ser"
    engine.start_recording(path, _header(camera))
    camera.emit(2)
    engine.configure(camera, RoiModel(
        capture=(0, 0, 64, 32), band=(0, 8, 64, 16),
        constraints=camera.info().caps.roi,
    ), CaptureParams(auto_exposure=False))
    assert not engine.is_recording()
    raw = path.read_bytes()
    assert struct.unpack_from("<i", raw, 38)[0] == 2
    engine.stop()


def test_disk_rate_is_reported_while_recording():
    engine, camera = _make()
    import tempfile
    from pathlib import Path
    path = Path(tempfile.mkdtemp()) / "rate.ser"
    engine.start()
    engine.start_recording(path, _header(camera))
    camera.emit(1)
    time.sleep(0.02)
    camera.emit(1)
    time.sleep(0.05)
    assert engine.counters().disk_mb_s >= 0.0
    engine.stop_recording()
    engine.stop()


def test_auto_exposure_writes_the_exposure_through_the_camera():
    camera = RecordingSim(width=64, height=32, fps=0.0)
    engine, _ = _make(camera)
    engine.configure(
        camera,
        RoiModel(capture=(0, 0, 64, 32), band=(0, 8, 64, 16),
                 constraints=camera.info().caps.roi),
        CaptureParams(auto_exposure=True, exposure_us=1000.0),
    )
    engine.start()
    camera.calls.clear()          # ignore the settings applied by start()
    camera.emit(2)
    engine.stop()
    exposures = [value for param, value in camera.calls
                 if param is Param.EXPOSURE]
    assert exposures, "the auto-exposure loop did not correct anything"
    assert exposures[-1] != pytest.approx(1000.0)


def test_start_without_configure_raises():
    engine = CaptureEngineImpl(start_timeout_s=0.0)
    with pytest.raises(DeviceError) as exc:
        engine.start()
    assert exc.value.code == "not_configured"


def test_start_timeout_is_reported_when_no_frame_arrives():
    engine = CaptureEngineImpl(start_timeout_s=0.1)
    camera = SimCamera(width=64, height=32, fps=0.0)
    roi = RoiModel(capture=(0, 0, 64, 32), band=(0, 8, 64, 16),
                   constraints=camera.info().caps.roi)
    engine.configure(camera, roi, CaptureParams(auto_exposure=False))
    with pytest.raises(DeviceError) as exc:
        engine.start()
    assert exc.value.code == "start_timeout"
    assert not engine.is_running()


def test_watchdog_aborts_a_stalled_stream():
    engine, camera = _make(stall_timeout_s=0.2)
    engine.start()
    time.sleep(0.5)
    assert engine.stalled()
    assert not engine.is_running()
    engine.stop()


def test_recording_requires_a_running_stream():
    engine, camera = _make()
    with pytest.raises(DeviceError) as exc:
        engine.start_recording("/tmp/nope.ser", _header(camera))
    assert exc.value.code == "not_running"
