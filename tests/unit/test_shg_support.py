############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg test support module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Shared fakes for the shg unit tests: a frame, a frame source, a mount and a
# row recorder. They implement the contracts structurally, exactly as the
# simulators of ADR-005 do, and they are deliberately deterministic: the clock
# and the sleep are owned by the test, so a scan that would take a minute runs
# in milliseconds.

from __future__ import annotations

import math

import numpy as np

from solarscribe.devices.abc import Axis, FrameStats, MountCaps, MountStatus
from solarscribe.shg.abc import RowCounters


class FakeStats:
    # FrameStats has two numbers only (ARCHITECTURE 2.1).
    def __init__(self, mean: float, std: float) -> None:
        self.mean = float(mean)
        self.std = float(std)


class FakeFrame:
    # A frame with a numpy buffer. stats() returns the injected values when
    # given, otherwise the real mean and population std of the data.
    def __init__(self, data, roi=None, sequence: int = 0,
                 timestamp: float = 0.0, std: float | None = None,
                 mean: float | None = None) -> None:
        self.data = np.ascontiguousarray(data)
        self.height, self.width = self.data.shape
        self.dtype = self.data.dtype
        self.roi = roi or (0, 0, self.width, self.height)
        self.sequence = int(sequence)
        self.timestamp = float(timestamp)
        self._std = std
        self._mean = mean

    # @args: none
    # @return: mean and std of the frame, injected or measured
    def stats(self) -> FrameStats:
        if self._std is not None:
            return FakeStats(self._mean if self._mean is not None else 0.0,
                             self._std)
        return FakeStats(float(np.mean(self.data)), float(np.std(self.data)))

    # @args: roi - sub-region in FRAME pixels
    # @return: a copied sub-frame
    def cut_roi(self, roi) -> "FakeFrame":
        x, y, w, h = roi
        return FakeFrame(self.data[y:y + h, x:x + w].copy(),
                         roi=self.roi, sequence=self.sequence,
                         timestamp=self.timestamp,
                         std=self._std, mean=self._mean)


class FakeFrames:
    # The FrameSource port. on_frame() stores the callback; emit() calls it.
    def __init__(self) -> None:
        self.callback = None
        self.emitted = 0

    # @args: cb - the engine's consumer
    # @return: none
    def on_frame(self, cb) -> None:
        self.callback = cb

    # @args: frame - the frame to deliver
    # @return: none
    def emit(self, frame) -> None:
        self.emitted += 1
        if self.callback is not None:
            self.callback(frame)


class FakeMount:
    # A deterministic mount. It does not move on its own: advance(dt) applies
    # the current rates, so the test owns time.
    def __init__(self, ra: float = 12.0, dec: float = 20.0,
                 arcsec_per_unit: float = 15.04) -> None:
        self.ra = float(ra)
        self.dec = float(dec)
        self.rate_ra = 0.0
        self.rate_dec = 0.0
        self.arcsec_per_unit = float(arcsec_per_unit)
        self.stopped = 0
        self.moves = []
        self._tracking = True

    # @return: whether the mount is connected
    def is_connected(self) -> bool:
        return True

    # @args: none
    def connect(self) -> None:
        pass

    # @args: none
    def close(self) -> None:
        pass

    # @return: (ra_hours, dec_degrees)
    def position(self):
        return self.ra, self.dec

    # @args: axis - RA or DEC; rate - arcsec/s
    # @return: none
    def move_axis(self, axis, rate: float) -> None:
        self.moves.append((axis, rate))
        if axis == Axis.RA:
            self.rate_ra = float(rate)
        else:
            self.rate_dec = float(rate)

    # @args: none
    def stop(self) -> None:
        self.stopped += 1
        self.rate_ra = 0.0
        self.rate_dec = 0.0

    # @args: ra - hours; dec - degrees
    def slew(self, ra: float, dec: float) -> None:
        self.ra, self.dec = float(ra), float(dec)

    # @args: ra - hours; dec - degrees
    def sync(self, ra: float, dec: float) -> None:
        self.ra, self.dec = float(ra), float(dec)

    # @args: on - tracking flag
    def set_tracking(self, on: bool) -> None:
        self._tracking = bool(on)

    # @args: none
    def park(self) -> None:
        pass

    # @args: none
    def unpark(self) -> None:
        pass

    # @args: none
    def abort_slew(self) -> None:
        self.stop()

    # @return: live state
    def status(self) -> MountStatus:
        return MountStatus(tracking=self._tracking)

    # @return: what this fake supports
    def capabilities(self) -> MountCaps:
        return MountCaps(supports_axis_rates=True,
                         reports_position_while_moving=True,
                         min_rate_arcsec_s=0.0, max_rate_arcsec_s=10000.0)

    # @args: dt - seconds of simulated time
    # @return: none
    def advance(self, dt: float) -> None:
        if dt <= 0:
            return
        self.ra = (self.ra + self.rate_ra * dt / 54000.0) % 24.0
        self.dec += self.rate_dec * dt / 3600.0


class FakeClock:
    # Monotonic clock owned by the test.
    def __init__(self) -> None:
        self.t = 0.0

    # @return: the current simulated time
    def time(self) -> float:
        return self.t

    # @args: dt - seconds to advance
    def sleep(self, dt: float) -> None:
        self.t += max(0.0, dt)


class FakeRecorder:
    # RowRecorder port. It records the paths and returns the counters the test
    # sets, so the engine's log arithmetic is exercised without a SER writer.
    def __init__(self, counters: RowCounters | None = None) -> None:
        self.counters = counters or RowCounters(frames_written=100)
        self.paths = []
        self.active = False

    # @args: path - the row file
    def start_row(self, path) -> None:
        self.paths.append(path)
        self.active = True

    # @return: the counters of the row that just closed
    def stop_row(self) -> RowCounters:
        self.active = False
        return self.counters


# @args: width, height - frame size; value - fill value; std - injected std
# @return: a uniform FakeFrame
def uniform_frame(width: int = 64, height: int = 32, value: int = 0,
                  std: float | None = None) -> FakeFrame:
    data = np.full((height, width), value, dtype=np.uint16)
    return FakeFrame(data, std=std, mean=float(value))


# @args: width, height - frame size; centre_px - centre of the bright block;
#        block_px - block width; band_y, band_h - vertical extent
# @return: a frame with a bright block along the slit axis, for the centroid
def block_frame(width: int = 64, height: int = 32, centre_px: float = 32.0,
                block_px: int = 8, band_y: int = 4,
                band_h: int = 24) -> FakeFrame:
    data = np.zeros((height, width), dtype=np.uint16)
    start = int(round(centre_px - block_px / 2.0))
    stop = start + block_px
    start = max(0, start)
    stop = min(width, stop)
    data[band_y:band_y + band_h, start:stop] = 1000
    return FakeFrame(data)


# @args: width, height, slope_px_per_px - vertical edge slope
# @return: a frame with a straight horizontal edge at y = h/2 + slope*x
def edge_frame(width: int = 200, height: int = 40,
               slope_px_per_px: float = 0.0) -> FakeFrame:
    data = np.zeros((height, width), dtype=np.uint16)
    for x in range(width):
        edge = int(round(height / 2.0 + slope_px_per_px * x))
        edge = max(0, min(height, edge))
        data[edge:, x] = 1000
    return FakeFrame(data)
