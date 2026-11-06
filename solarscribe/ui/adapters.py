############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui adapters module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The two small pieces that join the engines to Qt without either knowing about
# the other (ARCHITECTURE 2.3 and 4).
#
#   - DisplayBridge: a one-frame mailbox. The capture thread calls push(); the
#     GUI timer calls take(). A slow repaint therefore drops video frames
#     instead of queueing them, which is exactly the rule of the pipeline: the
#     display must never grow a backlog and start lagging behind the Sun.
#   - RowRecorderAdapter: the RowRecorder port shg declares, wired to
#     CaptureEngine.start_recording/stop_recording/counters. shg never imports
#     capture; this adapter copies the numbers and is the only place that knows
#     both contracts.
#
# There is no business logic here: no measuring, no deciding, only translation
# between two contracts that must not know each other.

from __future__ import annotations

import threading
from pathlib import Path

from solarscribe.capture.abc import (
    CaptureEngine,
    RoiModel,
    SerHeader,
    StreamCounters,
    WriterCounters,
)
from solarscribe.shg.abc import RowCounters

__all__ = ["DisplayBridge", "RowRecorderAdapter"]


class DisplayBridge:
    # The mailbox the capture thread writes and the GUI reads. It holds the last
    # frame only: if the GUI is busy, the next frame replaces it. That is the
    # documented trade (ARCHITECTURE 4): dropping video is correct, queueing it
    # is how the display ends up seconds behind.

    # @args: none
    # @return: a bridge with no frame yet
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame = None
        self.pushed = 0
        self.taken = 0
        self.replaced = 0

    # @args: frame - the frame just captured. Called on the capture thread and
    #              returns immediately: it only swaps a reference
    def push(self, frame) -> None:
        with self._lock:
            if self._frame is not None:
                self.replaced += 1
            self._frame = frame
            self.pushed += 1

    # @args: none. Called from the GUI timer
    # @return: the newest frame, or None when no new frame arrived
    def take(self):
        with self._lock:
            frame, self._frame = self._frame, None
            if frame is not None:
                self.taken += 1
            return frame

    # @args: frame - a frame from CaptureEngine.on_frame
    # This makes the bridge itself the callback, so the wiring is one line
    def __call__(self, frame) -> None:
        self.push(frame)


class RowRecorderAdapter:
    # The RowRecorder shg sees, over the capture engine. One row is one SER.

    # @args: engine - the capture engine; roi - the applied model;
    #        bit_depth - the SER depth, 16 by contract (ADR-018)
    # @return: an adapter ready for one run
    def __init__(self, engine: CaptureEngine, roi: RoiModel,
                 bit_depth: int = 16) -> None:
        self.engine = engine
        self.roi = roi
        self.bit_depth = int(bit_depth)
        self._writer = WriterCounters()
        self._stream = StreamCounters()

    # @args: path - the SER file for this row, named by config/store.py
    def start_row(self, path: Path) -> None:
        width = int(self.roi.capture[2])
        height = int(self.roi.capture[3])
        header = SerHeader(width=width, height=height,
                           bit_depth=self.bit_depth, roi=self.roi.capture)
        self.engine.start_recording(Path(path), header)

    # @return: the accounting of the row that just closed, in shg's own type
    def stop_row(self) -> RowCounters:
        self._writer = self.engine.stop_recording()
        self._stream = self.engine.counters()
        return RowCounters(
            frames_written=int(self._writer.frames_written),
            frames_dropped_queue=int(self._writer.frames_dropped_queue),
            frames_dropped_sdk=int(self._stream.frames_dropped_sdk),
            sequence_gaps=int(self._stream.sequence_gaps),
            queue_high_water_mb=float(self._writer.queue_high_water_mb),
        )
