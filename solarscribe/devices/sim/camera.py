############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices sim camera module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# First-class camera simulator (ADR-005).
#
# It is not a test double bolted on afterwards: the whole application can run
# against it. What makes it useful for the capture pipeline is that it can be
# driven two ways:
#   - fps > 0: a daemon thread emits frames at a fixed rate, like an SDK.
#   - fps == 0: nothing runs on its own; a test calls emit(n) and gets exactly n
#     frames on the calling thread, so threading never makes a unit test flaky.
#
# Drops are injectable because they are the behaviour the pipeline must count
# (ADR-013): drop_every skips every Nth frame and inject_drop() schedules one.
# A skipped frame still consumes a sequence number, so the host sees the hole.

from __future__ import annotations

import threading
import time
from dataclasses import replace

from solarscribe.devices.abc import (
    ROI, CameraCaps, CameraInfo, DeviceError, Param, ParamRange, RoiConstraints,
)
from solarscribe.devices.sim.frame import (
    PATTERNS, SimFrame, SolarPattern, make_pattern, make_solar_pattern,
)

__all__ = ["SimCamera"]

# Default sensor of the simulator. Small on purpose: the functional pipeline
# tests run it at hundreds of fps, and 3480x248 would spend the budget on numpy
# instead of on what the test is checking.
DEFAULT_WIDTH = 320
DEFAULT_HEIGHT = 64
DEFAULT_FPS = 120.0

# The solar pattern is meant to reproduce the reference ROI, so when it is
# selected and the caller does not override the size, it uses the G3M678M strip
# instead of the small generic default. This keeps SimCamera() (the "test"
# pattern) cheap while SimCamera(pattern="solar") is the physical fixture.
SOLAR_WIDTH = 3480
SOLAR_HEIGHT = 248

# The simulator does not control temperature (the MVP does not either, DESIGN
# 5.1): those parameters exist so the UI can exercise the "not supported" path.
_UNSUPPORTED = {
    Param.TEMPERATURE: "temperature",
    Param.COOLER: "cooler",
}


class SimCamera:
    # Camera contract backed by numpy patterns (ADR-005, ADR-012).

    # @args: width, height - sensor size; None means the generic 320x64 for the
    #                      test patterns and the 3480x248 reference strip for
    #                      the solar pattern
    #        fps - 0 for manual emit(); anything else starts a stream thread
    #        bit_depth - default pixel size, 8 or 16
    #        drop_every - drop every Nth frame (0: never)
    #        pattern - "test", "ramp", "flat" or "solar"
    #        solar - parameters of the solar pattern (sun, optics, seed)
    #        camera_id - identity reported by info(); unique across backends
    #        binning - initial binning factor
    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        fps: float = DEFAULT_FPS,
        bit_depth: int = 16,
        drop_every: int = 0,
        pattern: str = "test",
        solar: SolarPattern | None = None,
        camera_id: str = "sim:0",
        binning: int = 1,
        vendor: str = "SolarScribe",
        model: str = "SimCamera",
    ) -> None:
        if pattern not in PATTERNS:
            raise ValueError(f"unknown sim pattern {pattern!r}")
        if width is None:
            width = SOLAR_WIDTH if pattern == "solar" else DEFAULT_WIDTH
        if height is None:
            height = SOLAR_HEIGHT if pattern == "solar" else DEFAULT_HEIGHT
        if width <= 0 or height <= 0:
            raise ValueError("the simulator needs a positive sensor size")
        self._sensor_width = int(width)
        self._sensor_height = int(height)
        self._fps = float(fps)
        self._bit_depth = int(bit_depth)
        self._drop_every = max(0, int(drop_every))
        self._pattern = pattern
        self._solar = solar or SolarPattern()
        self._camera_id = camera_id
        self._vendor = vendor
        self._model = model
        self._binning = 1
        self._open = False
        self._sequence = 0
        self._dropped = 0
        self._pending_drops = 0
        self._roi: ROI = (0, 0, int(width), int(height))
        self._exposure_us = self._solar.exposure_reference_us
        self._gain = 0.0
        self._offset = 0.0
        self._readout = 0.0
        # A solar frame follows the mount: binding it is what makes left/right
        # brightness and the RA chord change during a real scan. Without a
        # mount, set_sky_position() drives the same geometry by hand.
        self._mount = None
        self._sky_ra = self._solar.sun_ra_hours
        self._sky_dec = self._solar.sun_dec_deg
        self._lock = threading.Lock()
        self._stream_thread: threading.Thread | None = None
        self._stream_stop = threading.Event()
        self._on_frame = None
        self._apply_binning(binning, reset_roi=True)

    # @args: none. Idempotent
    # @return: none
    def open(self) -> None:
        self._open = True

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        self.stop_stream()
        self._open = False

    # @return: whether the camera is open
    def is_open(self) -> bool:
        return self._open

    # @return: identity and capabilities; the ROI limits are at binning 1
    def info(self) -> CameraInfo:
        constraints = RoiConstraints(
            max_width=self._sensor_width,
            max_height=self._sensor_height,
        )
        caps = CameraCaps(
            roi=constraints,
            is_color=False,
            bit_depths=(8, 16),
            binnings=(1, 2, 4),
            has_cooler=False,
            reports_temperature=False,
        )
        return CameraInfo(
            camera_id=self._camera_id,
            vendor=self._vendor,
            model=self._model,
            backend="sim",
            caps=caps,
        )

    # @return: the current ROI in SENSOR pixels, already binned
    def get_roi(self) -> ROI:
        return self._roi

    # @args: roi - SENSOR pixels, binned. Out of the sensor means DeviceError
    # @return: none
    def set_roi(self, roi: ROI) -> None:
        x, y, width, height = roi
        max_w = self._sensor_width // self._binning
        max_h = self._sensor_height // self._binning
        if (
            x < 0 or y < 0 or width <= 0 or height <= 0
            or x + width > max_w or y + height > max_h
        ):
            raise DeviceError(
                f"ROI {roi!r} does not fit {max_w}x{max_h} at binning "
                f"{self._binning}",
                code="roi_rejected",
                device_id=self._camera_id,
            )
        self._roi = (x, y, width, height)

    # @return: the biggest ROI at the current binning
    def effective_area(self) -> ROI:
        return (0, 0, self._sensor_width // self._binning,
                self._sensor_height // self._binning)

    # @args: p - property to read
    # @return: its value in the unit fixed by Param
    def get_param(self, p: Param) -> float:
        if p in _UNSUPPORTED:
            raise DeviceError(
                f"the simulator does not expose {_UNSUPPORTED[p]}",
                code="not_supported",
                device_id=self._camera_id,
            )
        return float({
            Param.EXPOSURE: self._exposure_us,
            Param.GAIN: self._gain,
            Param.OFFSET: self._offset,
            Param.BIT_DEPTH: self._bit_depth,
            Param.BINNING: self._binning,
            Param.READOUT: self._readout,
        }[p])

    # @args: p - property; value - in the unit fixed by Param
    # @return: none
    def set_param(self, p: Param, value: float) -> None:
        if p in _UNSUPPORTED:
            raise DeviceError(
                f"the simulator does not expose {_UNSUPPORTED[p]}",
                code="not_supported",
                device_id=self._camera_id,
            )
        if p == Param.EXPOSURE:
            rng = self._range(p)
            if not rng.minimum <= value <= rng.maximum:
                raise DeviceError(
                    f"exposure {value} us outside "
                    f"[{rng.minimum}, {rng.maximum}]",
                    code="param_rejected", device_id=self._camera_id,
                )
            self._exposure_us = float(value)
        elif p == Param.GAIN:
            self._gain = float(value)
        elif p == Param.OFFSET:
            self._offset = float(value)
        elif p == Param.READOUT:
            self._readout = float(value)
        elif p == Param.BIT_DEPTH:
            if int(value) not in (8, 16):
                raise DeviceError(
                    f"bit depth {value} not supported",
                    code="param_rejected", device_id=self._camera_id,
                )
            self._bit_depth = int(value)
        elif p == Param.BINNING:
            self._apply_binning(int(value))
        else:
            raise DeviceError(
                f"unknown parameter {p}", code="not_supported",
                device_id=self._camera_id,
            )

    # @args: p - property
    # @return: the accepted interval; unsupported properties raise DeviceError
    def param_range(self, p: Param) -> ParamRange:
        return self._range(p)

    # @return: frames the simulator decided to drop since the stream started
    def dropped_frames(self) -> int:
        return self._dropped

    # @args: on_frame - called on the stream thread, or on the caller's thread
    #                   when fps == 0 (manual mode)
    # @return: none
    def start_stream(self, on_frame) -> None:
        if not self._open:
            raise DeviceError("camera is not open", code="not_open",
                              device_id=self._camera_id)
        if self._stream_thread is not None and self._stream_thread.is_alive():
            raise DeviceError("stream already running", code="already_streaming",
                              device_id=self._camera_id)
        self._on_frame = on_frame
        self._stream_stop.clear()
        if self._fps <= 0:
            return  # manual mode: the caller drives emit()
        self._stream_thread = threading.Thread(
            target=self._stream_loop, name="sim-camera", daemon=True,
        )
        self._stream_thread.start()

    # @args: none. Stops the stream thread if there is one
    # @return: none
    def stop_stream(self) -> None:
        self._stream_stop.set()
        thread = self._stream_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._stream_thread = None
        self._on_frame = None

    # @args: mount - an object with position() -> (ra_hours, dec_deg); it is
    #               read on the capture thread, so it must be cheap (the
    #               SimMount is, a networked mount would not be)
    # @return: none. The solar pattern then follows the mount as it scans
    def bind_mount(self, mount) -> None:
        with self._lock:
            self._mount = mount

    # @args: ra_hours - apparent RA of the Sun; dec_deg - its Dec
    # @return: none. Changes where the simulated disk is, not where the slit is
    def set_sun(self, ra_hours: float, dec_deg: float) -> None:
        with self._lock:
            self._solar = replace(
                self._solar, sun_ra_hours=float(ra_hours) % 24.0,
                sun_dec_deg=max(-90.0, min(90.0, float(dec_deg))),
            )

    # @args: ra_hours, dec_deg - where the slit points, for manual tests
    # @return: none. Ignored while a mount is bound
    def set_sky_position(self, ra_hours: float, dec_deg: float) -> None:
        with self._lock:
            self._sky_ra = float(ra_hours) % 24.0
            self._sky_dec = max(-90.0, min(90.0, float(dec_deg)))

    # @args: fps - new rate; 0 switches to manual mode
    # @return: none
    def set_fps(self, fps: float) -> None:
        self._fps = float(fps)

    # @args: count - how many frames the simulator should skip next
    # @return: none
    def inject_drop(self, count: int = 1) -> None:
        with self._lock:
            self._pending_drops += max(0, int(count))

    # @args: count - frames to emit now, on the caller's thread (manual mode)
    # @return: none
    def emit(self, count: int = 1) -> None:
        if self._stream_thread is not None and self._stream_thread.is_alive():
            raise DeviceError(
                "emit() is for manual mode (fps=0); the stream thread is running",
                code="already_streaming", device_id=self._camera_id,
            )
        for _ in range(max(0, int(count))):
            frame = self._next_frame()
            if frame is not None and self._on_frame is not None:
                self._on_frame(frame)

    # @args: factor - 1, 2 or 4
    # @return: none
    def _apply_binning(self, factor: int, *, reset_roi: bool = True) -> None:
        if factor not in (1, 2, 4):
            raise DeviceError(
                f"binning {factor} not supported", code="param_rejected",
                device_id=self._camera_id,
            )
        self._binning = factor
        if reset_roi:
            self._roi = self.effective_area()

    # @args: p - property
    # @return: the interval the simulator accepts
    def _range(self, p: Param) -> ParamRange:
        if p == Param.EXPOSURE:
            return ParamRange(1.0, 10_000_000.0, 1.0)
        if p == Param.GAIN:
            return ParamRange(0.0, 1000.0, 1.0)
        if p == Param.OFFSET:
            return ParamRange(0.0, 1000.0, 1.0)
        if p == Param.BIT_DEPTH:
            return ParamRange(8.0, 16.0, 8.0)
        if p == Param.BINNING:
            return ParamRange(1.0, 4.0, 1.0)
        if p == Param.READOUT:
            return ParamRange(0.0, 100.0, 1.0)
        if p in _UNSUPPORTED:
            raise DeviceError(
                f"the simulator does not expose {_UNSUPPORTED[p]}",
                code="not_supported", device_id=self._camera_id,
            )
        raise DeviceError(f"unknown parameter {p}", code="not_supported",
                          device_id=self._camera_id)

    # @args: none
    # @return: one frame, or None when the simulator decides to drop it
    def _next_frame(self) -> SimFrame | None:
        with self._lock:
            sequence = self._sequence
            self._sequence += 1
            drop = False
            if self._pending_drops > 0:
                self._pending_drops -= 1
                drop = True
            elif self._drop_every and (sequence + 1) % self._drop_every == 0:
                drop = True
            if drop:
                self._dropped += 1
                return None
            roi = self._roi
            x, y, width, height = roi
            bit_depth = self._bit_depth
            pattern = self._pattern
            solar = self._solar
            exposure_us = self._exposure_us
            mount = self._mount
            sky_ra, sky_dec = self._sky_ra, self._sky_dec
        # Keep the ROI captured with the frame: if a caller changes it between
        # the lock and here, the frame still describes the pixels it holds.
        if pattern == "solar":
            # The mount is the sky. Reading it outside the camera lock keeps
            # the capture thread from holding two locks while the scan thread
            # is moving the mount.
            if mount is not None:
                slit_ra, slit_dec = mount.position()
            else:
                slit_ra, slit_dec = sky_ra, sky_dec
            array = make_solar_pattern(
                width, height,
                slit_ra_hours=slit_ra, slit_dec_deg=slit_dec,
                exposure_us=exposure_us, solar=solar, bit_depth=bit_depth,
            )
        else:
            array = make_pattern(
                width, height, x0=x, y0=y, sequence=sequence,
                bit_depth=bit_depth, kind=pattern,
            )
        return SimFrame(array, roi, sequence, time.monotonic())

    # @args: none
    # @return: none. Emits at about self._fps until stop_stream()
    def _stream_loop(self) -> None:
        interval = 1.0 / self._fps
        deadline = time.monotonic()
        while not self._stream_stop.is_set():
            deadline += interval
            wait = deadline - time.monotonic()
            if wait > 0:
                if self._stream_stop.wait(wait):
                    break
            elif -wait > 1.0:
                # We are more than a second late (the machine was suspended or
                # the process was starved): resynchronise instead of bursting
                # a second of frames at once.
                deadline = time.monotonic()
            # A small lateness is not resynchronised: keeping the absolute
            # deadline lets the next few frames catch up, which is what keeps
            # the average at the configured rate. Event.wait has ~1 ms
            # granularity, and resetting the deadline on every late frame made
            # a 120 fps simulator deliver ~114 fps (measured).
            frame = self._next_frame()
            if frame is not None and self._on_frame is not None:
                self._on_frame(frame)
