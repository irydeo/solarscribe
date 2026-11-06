############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - capture engine module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# CaptureEngine implementation (design/ARCHITECTURE.md 4 and 5, ADR-013).
#
# Threading is the whole point of this module, so the rule is repeated where it
# matters: the capture thread (the camera's callback) only gets a frame and
# hands it to cheap consumers. It never waits for disk, never waits for Qt and
# never waits for a lock held by someone doing I/O.
#
#   capture thread: callback(frame)
#      +--> inline consumers: on_frame (DisplayBridge, shg), on_stats
#      +--> auto-exposure: a multiplicative correction, no sleep
#      +--> bounded recording queue (bytes, not items)
#                 |
#                 v writer thread
#           SerWriter (buffered file)
#
# The queue is bounded by BYTES because a frame size depends on the ROI and the
# bit depth; counting frames would either waste the 512 MB budget or exceed it.
# The budget is enforced before enqueue: if the new frame does not fit, it is
# dropped and counted. `queue.Queue` is unbounded underneath and only used as a
# thread-safe handoff; our own byte counter is the real limit, so put() never
# blocks.
#
# Dropped frames are counted in the three places ADR-013 requires:
#   - camera.dropped_frames(): the SDK's own counter
#   - WriterCounters.frames_dropped_queue: this queue
#   - StreamCounters.sequence_gaps: holes in Frame.sequence
#
# Stall: a watchdog thread watches the receipt time. After stall_timeout_s with
# no frame it marks the stream stalled, stops the camera and closes the
# recording cleanly, so the SER already written is preserved (ADR-014). The UI
# sees is_running() false and stalled() true.

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from pathlib import Path

from solarscribe.capture.abc import (
    CaptureParams, RoiModel, SerHeader, StreamCounters, WriterCounters,
)
from solarscribe.capture.auto_exposure import AutoExposureConfig, AutoExposureLoop
from solarscribe.capture.ser import SerWriterImpl
from solarscribe.devices.abc import DeviceError, Frame, Param

__all__ = ["CaptureEngineImpl"]


class CaptureEngineImpl:
    # Stream, counters and recording on top of a devices.Camera.

    # @args: writer_factory - builds the SerWriter; injectable for the tests
    #        start_timeout_s - how long start() waits for the first frame; 0
    #                          skips the wait (manual simulators in unit tests)
    def __init__(self, *, writer_factory=SerWriterImpl,
                 start_timeout_s: float = 5.0) -> None:
        self._writer_factory = writer_factory
        self._start_timeout_s = float(start_timeout_s)
        self._lock = threading.RLock()
        self._camera = None
        self._roi: RoiModel | None = None
        self._params = CaptureParams()
        self._running = False
        self._opened_here = False
        self._stalled = False
        self._started_at = 0.0
        self._last_frame_time = 0.0
        self._first_frame = threading.Event()
        self._stall_stop = threading.Event()
        self._watchdog: threading.Thread | None = None

        self._frame_callbacks: list = []
        self._stats_callbacks: list = []

        self._frames_received = 0
        self._sequence_gaps = 0
        self._last_sequence: int | None = None
        self._frame_times: deque[float] = deque()
        self._effective_bit_depth = 16
        self._auto: AutoExposureLoop | None = None

        self._recording = False
        self._writer = None
        self._writer_thread: threading.Thread | None = None
        self._writer_stop = threading.Event()
        self._writer_error = ""
        self._queue: queue.Queue = queue.Queue()
        self._queue_bytes = 0
        self._queue_high_water = 0
        self._dropped_queue = 0
        self._queue_budget_bytes = CaptureParams().queue_budget_mb * 1_000_000.0
        self._last_writer_counters = WriterCounters()

    # @args: camera - device to stream from
    #        roi - model whose capture region is applied to the hardware
    #        params - how to run
    # @return: none. While running it restarts the stream; while recording it
    #          closes the recording cleanly first (ADR-010, ADR-014)
    def configure(self, camera, roi: RoiModel, params: CaptureParams) -> None:
        if self.is_recording():
            self.stop_recording()
        was_running = self.is_running()
        if was_running:
            self.stop()
        with self._lock:
            self._camera = camera
            self._roi = roi
            self._params = params
            self._queue_budget_bytes = max(
                0.0, float(params.queue_budget_mb) * 1_000_000.0,
            )
            self._effective_bit_depth = int(params.bit_depth)
            self._auto = (
                AutoExposureLoop(
                    AutoExposureConfig(target_fraction=params.auto_exposure_target),
                    initial_exposure_us=params.exposure_us,
                )
                if params.auto_exposure else None
            )
        if was_running:
            self.start()
        elif self._camera is not None and self._camera.is_open():
            # The caller already opened the camera: apply the new ROI and
            # parameters now instead of waiting for start(). This is what the
            # live ROI editor expects when it reconfigures a stopped stream.
            self._apply_camera_settings()

    # @args: none. Starts the stream; waits for the first frame within the
    #              ADR-013 start budget (or start_timeout_s)
    # @return: none
    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            if self._camera is None or self._roi is None:
                raise DeviceError("capture engine is not configured",
                                  code="not_configured")
            camera = self._camera
            self._opened_here = not camera.is_open()
            try:
                if self._opened_here:
                    camera.open()
                self._apply_camera_settings()
            except Exception:
                # A failed start must not leave a camera the engine opened
                # hanging open forever.
                if self._opened_here:
                    try:
                        camera.close()
                    except Exception:  # noqa: BLE001
                        pass
                self._opened_here = False
                raise
            self._frames_received = 0
            self._sequence_gaps = 0
            self._last_sequence = None
            self._frame_times.clear()
            self._stalled = False
            self._first_frame.clear()
            self._last_frame_time = time.monotonic()
            self._started_at = self._last_frame_time
            self._running = True
            self._stall_stop.clear()
        try:
            camera.start_stream(self._on_camera_frame)
        except Exception:
            with self._lock:
                self._running = False
            raise
        self._watchdog = threading.Thread(
            target=self._watchdog_loop, name="capture-watchdog", daemon=True,
        )
        self._watchdog.start()
        if self._start_timeout_s > 0.0:
            if not self._first_frame.wait(self._start_timeout_s):
                self.stop()
                raise DeviceError(
                    f"no frame within {self._start_timeout_s:.1f} s of start()",
                    code="start_timeout",
                )

    # @args: none. Stops the stream, closes the recording and joins the threads
    # @return: none
    def stop(self) -> None:
        if self.is_recording():
            self.stop_recording()
        with self._lock:
            if not self._running:
                return
            self._running = False
            camera = self._camera
            opened_here = self._opened_here
            self._opened_here = False
        self._stall_stop.set()
        if camera is not None:
            try:
                camera.stop_stream()
            finally:
                if opened_here:
                    camera.close()
        self._join_watchdog()

    # @return: whether the stream is running
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    # @return: whether a recording is open
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    # @return: whether the watchdog aborted a stalled stream
    def stalled(self) -> bool:
        with self._lock:
            return self._stalled

    # @args: cb - inline consumer; called on the capture thread
    # @return: none
    def on_frame(self, cb) -> None:
        with self._lock:
            self._frame_callbacks.append(cb)

    # @args: cb - inline stats consumer; called on the capture thread
    # @return: none
    def on_stats(self, cb) -> None:
        with self._lock:
            self._stats_callbacks.append(cb)

    # @args: path - .ser file to create; header - standard SER fields
    # @return: none. Frames go to the bounded queue from here on
    def start_recording(self, path: Path, header: SerHeader) -> None:
        if not self.is_running():
            raise DeviceError("cannot record while the stream is stopped",
                              code="not_running")
        if self.is_recording():
            self.stop_recording()
        writer = self._writer_factory()
        writer.open(Path(path), header)
        with self._lock:
            self._writer = writer
            self._queue = queue.Queue()
            self._queue_bytes = 0
            self._queue_high_water = 0
            self._dropped_queue = 0
            self._writer_error = ""
            self._writer_stop.clear()
            self._recording = True
        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="capture-writer", daemon=True,
        )
        self._writer_thread.start()

    # @return: the accounting of the recording that just closed
    def stop_recording(self) -> WriterCounters:
        with self._lock:
            if not self._recording:
                return self._last_writer_counters
            self._recording = False
            writer = self._writer
            thread = self._writer_thread
            self._writer_stop.set()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=10.0)
        if writer is not None:
            writer.close()
            base = writer.counters()
            counters = WriterCounters(
                frames_written=base.frames_written,
                frames_dropped_queue=self._dropped_queue,
                queue_high_water_mb=self._queue_high_water / 1_000_000.0,
            )
        else:
            counters = WriterCounters(
                frames_dropped_queue=self._dropped_queue,
                queue_high_water_mb=self._queue_high_water / 1_000_000.0,
            )
        with self._lock:
            self._writer = None
            self._writer_thread = None
            self._last_writer_counters = counters
        return counters

    # @return: live counters; cheap enough to poll from the GUI thread
    def counters(self) -> StreamCounters:
        with self._lock:
            fps = self._current_fps_locked()
            camera = self._camera
            recording = self._recording
            writer = self._writer
            values = StreamCounters(
                frames_received=self._frames_received,
                sequence_gaps=self._sequence_gaps,
                fps=fps,
                disk_mb_s=(
                    writer.mb_per_s()
                    if recording and writer is not None else 0.0
                ),
            )
        sdk_drops = 0
        if camera is not None:
            try:
                sdk_drops = int(camera.dropped_frames())
            except Exception:  # noqa: BLE001 - a counter must never raise
                sdk_drops = 0
        return StreamCounters(
            frames_received=values.frames_received,
            frames_dropped_sdk=sdk_drops,
            sequence_gaps=values.sequence_gaps,
            fps=values.fps,
            disk_mb_s=values.disk_mb_s,
        )

    # @args: frame - one frame from the camera, on the capture thread
    # @return: none. This is the critical path: no I/O, no blocking waits
    def _on_camera_frame(self, frame: Frame) -> None:
        now = frame.timestamp or time.monotonic()
        with self._lock:
            if not self._running:
                return
            if self._last_sequence is not None:
                if frame.sequence > self._last_sequence + 1:
                    self._sequence_gaps += frame.sequence - self._last_sequence - 1
                elif frame.sequence <= self._last_sequence:
                    # A backwards sequence is a restart or a duplicate, not a
                    # hole we can size; count one so it is never invisible.
                    self._sequence_gaps += 1
            self._last_sequence = frame.sequence
            self._frames_received += 1
            self._last_frame_time = time.monotonic()
            self._first_frame.set()
            self._stalled = False
            self._frame_times.append(now)
            while self._frame_times and self._frame_times[0] < now - 1.0:
                self._frame_times.popleft()
            frame_callbacks = list(self._frame_callbacks)
            stats_callbacks = list(self._stats_callbacks)
            auto = self._auto
            bit_depth = self._effective_bit_depth
            recording = self._recording
            if recording:
                nbytes = frame.width * frame.height * max(1, bit_depth // 8)
                if self._queue_bytes + nbytes > self._queue_budget_bytes:
                    self._dropped_queue += 1
                else:
                    self._queue_bytes += nbytes
                    if self._queue_bytes > self._queue_high_water:
                        self._queue_high_water = self._queue_bytes
                    # Enqueue under the lock: stop_recording() flips _recording
                    # under the same lock, so a frame cannot be queued after the
                    # writer has been told to finish. The queue is unbounded
                    # underneath, so put() never blocks the capture thread.
                    self._queue.put((frame, nbytes))
        # Stats are a full pass over the frame (863k pixels at the reference
        # ROI). They are only paid when someone reads them: an on_stats
        # consumer or the auto-exposure loop. With neither, a 120 fps stream
        # would spend CPU on a number nobody uses.
        if stats_callbacks or auto is not None:
            stats = frame.stats()
            for cb in stats_callbacks:
                try:
                    cb(stats)
                except Exception:  # noqa: BLE001 - a consumer must not kill capture
                    pass
            if auto is not None:
                full_scale = 255.0 if bit_depth == 8 else 65535.0
                try:
                    new_exposure = auto.observe(stats.mean, full_scale, now)
                except Exception:  # noqa: BLE001
                    new_exposure = None
                if new_exposure is not None and self._camera is not None:
                    try:
                        self._camera.set_param(Param.EXPOSURE, new_exposure)
                    except Exception:  # noqa: BLE001
                        pass
        for cb in frame_callbacks:
            try:
                cb(frame)
            except Exception:  # noqa: BLE001
                pass

    # @args: none
    # @return: none. Drains the queue into the writer; runs on its own thread
    def _writer_loop(self) -> None:
        while True:
            try:
                frame, nbytes = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._writer_stop.is_set() and self._queue.empty():
                    break
                continue
            try:
                if frame is not None:
                    self._writer.write(frame)
            except Exception as exc:  # noqa: BLE001 - disk errors are reported
                self._writer_error = str(exc)
                with self._lock:
                    self._dropped_queue += 1
            finally:
                with self._lock:
                    self._queue_bytes -= nbytes
                self._queue.task_done()

    # @args: none
    # @return: none. Aborts a stalled stream and preserves the recording
    def _watchdog_loop(self) -> None:
        while not self._stall_stop.wait(0.1):
            with self._lock:
                if not self._running:
                    return
                timeout = float(self._params.stall_timeout_s)
                if timeout <= 0.0:
                    continue
                if time.monotonic() - self._last_frame_time <= timeout:
                    continue
                self._stalled = True
                self._running = False
                camera = self._camera
                opened_here = self._opened_here
                self._opened_here = False
            # Outside the lock: stop_stream joins the capture thread and must
            # not wait for a lock the capture thread may be taking.
            if camera is not None:
                try:
                    camera.stop_stream()
                except Exception:  # noqa: BLE001
                    pass
                if opened_here:
                    try:
                        camera.close()
                    except Exception:  # noqa: BLE001
                        pass
            if self.is_recording():
                self.stop_recording()
            return

    # @args: none
    # @return: none. Joins the watchdog if it is not the current thread
    def _join_watchdog(self) -> None:
        thread = self._watchdog
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._watchdog = None

    # @args: none
    # @return: none. Applies binning, ROI, gain, offset, exposure to the camera
    def _apply_camera_settings(self) -> None:
        camera = self._camera
        params = self._params
        roi = self._roi
        try:
            current_binning = int(camera.get_param(Param.BINNING))
        except Exception:  # noqa: BLE001
            current_binning = params.binning
        if current_binning != int(params.binning):
            camera.set_param(Param.BINNING, int(params.binning))
        camera.set_roi(roi.capture)
        for param, value in ((Param.GAIN, params.gain),
                             (Param.OFFSET, params.offset),
                             (Param.EXPOSURE, params.exposure_us)):
            try:
                camera.set_param(param, value)
            except DeviceError:
                # A camera that does not expose one of them still streams; the
                # engine does not turn a missing control into a failed start.
                pass
        if params.readout > 0.0:
            try:
                camera.set_param(Param.READOUT, params.readout)
            except DeviceError:
                pass
        try:
            self._effective_bit_depth = int(camera.get_param(Param.BIT_DEPTH))
        except Exception:  # noqa: BLE001
            self._effective_bit_depth = int(params.bit_depth)
        if self._auto is not None:
            self._auto.reset(params.exposure_us)

    # @args: none
    # @return: the real rate over the last second, from the receipt timestamps
    def _current_fps_locked(self) -> float:
        if len(self._frame_times) < 2:
            return 0.0
        span = self._frame_times[-1] - self._frame_times[0]
        if span <= 0.0:
            return 0.0
        return (len(self._frame_times) - 1) / span
