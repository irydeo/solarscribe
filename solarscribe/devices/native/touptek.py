############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native touptek module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Touptek native driver (libtoupcam), the reference camera of the MVP: the
# G3M678M mono sensor, ROI 3480x248, 16 bit, no temperature control (DESIGN 5.1).
#
# Two layers, on purpose:
#   - CtypesToupcamSdk is the thin ctypes wrapper. It owns the handle, the
#     ctypes buffers and the SDK callback. It copies the image out of the SDK
#     buffer into a fresh numpy array before returning it: the SDK reuses its
#     buffers, so anything that escapes this module must be owned by Python
#     (ADR-001, ARCHITECTURE 4).
#   - TouptekCamera implements the devices.Camera contract on top of it. The
#     SDK callback only sets an Event; a Python thread does the copy and calls
#     the user callback, so no Python work runs inside the C callback.
#
# The SDK is loaded dynamically by the backend (loader.py). This module never
# imports a vendor library at import time, so the module exists on a machine
# without Touptek and the backend simply reports SDK_MISSING (ADR-014).
#
# Hardware validation: the ctypes signatures and the ROI multiples below follow
# the published toupcam.h. They are exercised with a mocked library in the unit
# suite and MUST be re-checked against a real G3M678M before the release.

from __future__ import annotations

import ctypes
import threading
import time

import numpy as np

from solarscribe.devices.abc import (
    ROI, CameraCaps, CameraInfo, DeviceError, Param, ParamRange, RoiConstraints,
)

__all__ = ["LIBRARIES", "SdkDevice", "TouptekCamera", "CtypesToupcamSdk"]

BACKEND = "native/touptek"

# The vendor ships different names per platform. Loading by name first lets the
# user place the DLL/so next to the executable; the loader then falls back to
# the system path.
LIBRARIES = (
    "libtoupcam.so",
    "libtoupcam.dylib",
    "toupcam.dll",
    "Toupcam.dll",
)

# Event the SDK sends when a new image is ready. Values from toupcam.h.
TOUPCAM_EVENT_IMAGE = 0x0010
TOUPCAM_EVENT_ERROR = 0x0001
TOUPCAM_EVENT_DISCONNECTED = 0x0002

# SDK options used by the driver. RAW selects the un-debayered plane (mono) and
# BITDEPTH selects the output word size. SPEED is the readout/USB traffic index.
TOUPCAM_OPTION_RAW = 0x04
TOUPCAM_OPTION_SPEED = 0x10
TOUPCAM_OPTION_BITDEPTH = 0x13

# Conservative ROI alignment. The SDK documents that ROI origin and width must
# be aligned; the exact multiple varies by model, so the driver declares the
# strictest common case and the validation step refuses a ROI the SDK would
# reject. VERIFY ON HARDWARE.
WIDTH_MULTIPLE = 4
HEIGHT_MULTIPLE = 2
OFFSET_MULTIPLE = 4

# Nominal sensor size of the reference camera, used only when discovery cannot
# open the device to read the real size. It is better to show a camera with the
# reference geometry than to hide it, and the first open() corrects the value.
NOMINAL_WIDTH = 3840
NOMINAL_HEIGHT = 2160


class SdkDevice:
    # One entry of the SDK enumeration.

    # @args: device_id - stable SDK id
    #        display_name - what the vendor calls it
    #        model - numeric model code
    #        index - position in the enumeration, used by OpenByIndex
    def __init__(self, device_id: str, display_name: str, model: int, index: int) -> None:
        self.device_id = device_id
        self.display_name = display_name
        self.model = int(model)
        self.index = int(index)


class _DeviceV2(ctypes.Structure):
    _fields_ = [
        ("displayname", ctypes.c_wchar_p),
        ("id", ctypes.c_char_p),
        ("model", ctypes.c_uint),
    ]


class CtypesToupcamSdk:
    # Per-device ctypes wrapper. One instance owns one camera handle.

    # @args: library - loaded CDLL (or a mock with the same method names)
    #        index - device index from enumerate()
    def __init__(self, library, index: int) -> None:
        self._lib = library
        self._index = int(index)
        self._handle = None
        self._width = 0
        self._height = 0
        self._bit_depth = 16
        self._dropped = 0
        self._callback = None
        # Reused across frames: allocating 1.7 MB per frame on the capture path
        # is waste. The numpy copy below is still per frame because the frame
        # must own its pixels (the SDK buffer is about to be overwritten).
        self._buffer = None
        self._buffer_nbytes = 0

    # @args: library - loaded CDLL
    # @return: the devices the SDK reports, with their stable ids and indexes
    @staticmethod
    def enumerate(library) -> list[SdkDevice]:
        if not hasattr(library, "Toupcam_EnumV2"):
            return []
        array = (_DeviceV2 * 128)()
        try:
            count = int(library.Toupcam_EnumV2(array))
        except Exception:      # noqa: BLE001 - a broken SDK must not crash start
            return []
        devices = []
        for i in range(max(0, min(count, 128))):
            raw_id = array[i].id or b""
            if isinstance(raw_id, bytes):
                raw_id = raw_id.decode("utf-8", "replace")
            devices.append(SdkDevice(
                device_id=raw_id,
                display_name=array[i].displayname or f"Toupcam {i}",
                model=array[i].model,
                index=i,
            ))
        return devices

    # @args: none. Raises DeviceError when the SDK refuses the handle
    # @return: none
    def open(self) -> None:
        try:
            if hasattr(self._lib, "Toupcam_OpenByIndex"):
                handle = self._lib.Toupcam_OpenByIndex(self._index)
            else:
                raise DeviceError("the SDK has no Toupcam_OpenByIndex",
                                  code="sdk_error")
        except DeviceError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DeviceError(f"Toupcam_OpenByIndex failed: {exc}",
                              code="sdk_error") from exc
        if not handle:
            raise DeviceError("Toupcam_OpenByIndex returned no handle",
                              code="device_lost")
        self._handle = handle

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        if self._handle is not None:
            try:
                self._lib.Toupcam_Close(self._handle)
            finally:
                self._handle = None

    # @args: none
    # @return: (width, height) of the sensor at the current ROI settings
    def size(self) -> tuple[int, int]:
        width = ctypes.c_int(0)
        height = ctypes.c_int(0)
        status = self._lib.Toupcam_get_Size(
            self._handle, ctypes.byref(width), ctypes.byref(height),
        )
        if status != 0:
            raise DeviceError("Toupcam_get_Size failed", code="sdk_error")
        self._width, self._height = int(width.value), int(height.value)
        return self._width, self._height

    # @args: roi - sensor ROI
    # @return: none
    def set_roi(self, roi: ROI) -> None:
        x, y, width, height = roi
        status = self._lib.Toupcam_put_Roi(
            self._handle, x, y, width, height,
        )
        if status != 0:
            raise DeviceError(f"Toupcam_put_Roi{roi} failed", code="roi_rejected")

    # @return: the ROI the SDK reports
    def get_roi(self) -> ROI:
        x, y, width, height = (ctypes.c_uint(0) for _ in range(4))
        status = self._lib.Toupcam_get_Roi(
            self._handle, ctypes.byref(x), ctypes.byref(y),
            ctypes.byref(width), ctypes.byref(height),
        )
        if status != 0:
            raise DeviceError("Toupcam_get_Roi failed", code="sdk_error")
        return (int(x.value), int(y.value), int(width.value), int(height.value))

    # @return: exposure in microseconds
    def get_exposure(self) -> float:
        value = ctypes.c_uint(0)
        status = self._lib.Toupcam_get_ExpoTime(self._handle, ctypes.byref(value))
        if status != 0:
            raise DeviceError("Toupcam_get_ExpoTime failed", code="sdk_error")
        return float(value.value)

    # @args: value - microseconds
    # @return: none
    def set_exposure(self, value: float) -> None:
        status = self._lib.Toupcam_put_ExpoTime(self._handle, int(value))
        if status != 0:
            raise DeviceError("Toupcam_put_ExpoTime failed",
                              code="param_rejected")

    # @return: the exposure interval the SDK accepts, in microseconds
    def exposure_range(self) -> ParamRange:
        lo, hi, default = (ctypes.c_uint(0) for _ in range(3))
        status = self._lib.Toupcam_get_ExpTimeRange(
            self._handle, ctypes.byref(lo), ctypes.byref(hi),
            ctypes.byref(default),
        )
        if status != 0:
            raise DeviceError("Toupcam_get_ExpTimeRange failed",
                              code="sdk_error")
        return ParamRange(float(lo.value), float(hi.value), 1.0)

    # @return: gain in SDK units
    def get_gain(self) -> float:
        value = ctypes.c_ushort(0)
        status = self._lib.Toupcam_get_ExpoAGain(
            self._handle, ctypes.byref(value),
        )
        if status != 0:
            raise DeviceError("Toupcam_get_ExpoAGain failed", code="sdk_error")
        return float(value.value)

    # @args: value - SDK gain units
    # @return: none
    def set_gain(self, value: float) -> None:
        status = self._lib.Toupcam_put_ExpoAGain(self._handle, int(value))
        if status != 0:
            raise DeviceError("Toupcam_put_ExpoAGain failed",
                              code="param_rejected")

    # @return: the gain interval the SDK accepts
    def gain_range(self) -> ParamRange:
        lo, hi, default = (ctypes.c_ushort(0) for _ in range(3))
        status = self._lib.Toupcam_get_ExpoAGainRange(
            self._handle, ctypes.byref(lo), ctypes.byref(hi),
            ctypes.byref(default),
        )
        if status != 0:
            # Not every model exposes the range; a sensible fallback keeps the
            # UI usable instead of hiding gain altogether.
            return ParamRange(0.0, 1000.0, 1.0)
        return ParamRange(float(lo.value), float(hi.value), 1.0)

    # @args: option - SDK option id; value - integer value
    # @return: none
    def set_option(self, option: int, value: int) -> None:
        status = self._lib.Toupcam_put_Option(
            self._handle, int(option), int(value),
        )
        if status != 0:
            raise DeviceError(
                f"Toupcam_put_Option({option:#x}, {value}) failed",
                code="param_rejected",
            )

    # @args: option - SDK option id
    # @return: its current integer value
    def get_option(self, option: int) -> int:
        value = ctypes.c_int(0)
        status = self._lib.Toupcam_get_Option(
            self._handle, int(option), ctypes.byref(value),
        )
        if status != 0:
            raise DeviceError(
                f"Toupcam_get_Option({option:#x}) failed", code="sdk_error",
            )
        return int(value.value)

    # @args: callback - called on the SDK thread with (event, context)
    # @return: none
    def start(self, callback) -> None:
        # The CFUNCTYPE object must stay alive for as long as the SDK holds it;
        # a collected trampoline would crash the C thread.
        signature = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.c_void_p)
        self._callback = signature(callback)
        status = self._lib.Toupcam_StartPullModeWithCallback(
            self._handle, self._callback, None,
        )
        if status != 0:
            raise DeviceError("Toupcam_StartPullModeWithCallback failed",
                              code="sdk_error")

    # @args: none
    # @return: none
    def stop(self) -> None:
        try:
            self._lib.Toupcam_Stop(self._handle)
        except Exception:  # noqa: BLE001 - stopping a dead handle is harmless
            pass
        self._callback = None

    # @args: none
    # @return: a fresh uint8/uint16 array owned by Python, or None when the SDK
    #          signalled an image but could not deliver it (counted as a drop)
    def pull(self) -> np.ndarray | None:
        dtype = np.uint8 if self._bit_depth == 8 else np.uint16
        nbytes = self._width * self._height * dtype().itemsize
        if self._buffer is None or self._buffer_nbytes != nbytes:
            self._buffer = ctypes.create_string_buffer(nbytes)
            self._buffer_nbytes = nbytes
        buffer = self._buffer
        if hasattr(self._lib, "Toupcam_PullImageV4"):
            status = self._lib.Toupcam_PullImageV4(
                self._handle, buffer, 0, self._bit_depth, 0, None,
            )
        else:
            width = ctypes.c_int(self._width)
            height = ctypes.c_int(self._height)
            status = self._lib.Toupcam_PullImage(
                self._handle, buffer, self._bit_depth,
                ctypes.byref(width), ctypes.byref(height),
            )
        if status != 0:
            self._dropped += 1
            return None
        # The copy is the ownership boundary: frombuffer alone would leave a
        # view into the reusable ctypes buffer, and the next PullImage would
        # overwrite the frame a consumer still holds.
        array = np.frombuffer(buffer, dtype=dtype).reshape(
            self._height, self._width,
        )
        return array.copy()

    # @return: images the SDK failed to deliver since the stream started
    def dropped_frames(self) -> int:
        return self._dropped


class TouptekCamera:
    # Camera contract on top of the Touptek SDK (ADR-002, ADR-012).

    # @args: camera_id - "<backend>:<index>" as built by discover()
    #        library - loaded CDLL; the backend passes the one it probed with
    #        sdk - injectable per-device wrapper, for the unit tests
    def __init__(self, camera_id: str, library=None, sdk=None) -> None:
        self._camera_id = camera_id
        self._library = library
        self._sdk = sdk
        self._open = False
        self._width = NOMINAL_WIDTH
        self._height = NOMINAL_HEIGHT
        self._roi: ROI = (0, 0, NOMINAL_WIDTH, NOMINAL_HEIGHT)
        self._bit_depth = 16
        self._binning = 1
        self._sequence = 0
        self._stream_thread: threading.Thread | None = None
        self._stream_stop = threading.Event()
        self._image_event = threading.Event()
        self._on_frame = None
        self._sdk_error = ""

    # @args: library - loaded CDLL
    # @return: the cameras the SDK reports, with their sensor size read by a
    #          short open/close during discovery
    @classmethod
    def discover(cls, library) -> list[CameraInfo]:
        infos = []
        for device in CtypesToupcamSdk.enumerate(library):
            width, height = NOMINAL_WIDTH, NOMINAL_HEIGHT
            try:
                sdk = CtypesToupcamSdk(library, device.index)
                sdk.open()
                try:
                    width, height = sdk.size()
                finally:
                    sdk.close()
            except Exception:  # noqa: BLE001 - one bad device must not hide the rest
                pass
            camera_id = f"{BACKEND}:{device.index}"
            infos.append(_make_info(camera_id, device.display_name, width, height))
        return infos

    # @args: none. Raises DeviceError if the SDK refuses to open
    # @return: none
    def open(self) -> None:
        self._ensure_sdk()
        try:
            self._sdk.open()
            self._width, self._height = self._sdk.size()
            # RAW keeps the mono plane; BITDEPTH 16 is the SER contract. If the
            # model refuses an option the driver keeps going: the UI can still
            # show the camera and the first frames tell what it delivers.
            for option, value in (
                (TOUPCAM_OPTION_RAW, 1),
                (TOUPCAM_OPTION_BITDEPTH, 16),
            ):
                try:
                    self._sdk.set_option(option, value)
                except DeviceError:
                    pass
            try:
                self._roi = self._sdk.get_roi()
            except DeviceError:
                self._roi = (0, 0, self._width, self._height)
            self._open = True
        except DeviceError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DeviceError(f"could not open {self._camera_id}: {exc}",
                              code="device_lost",
                              device_id=self._camera_id) from exc

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        self.stop_stream()
        if self._sdk is not None:
            self._sdk.close()
        self._open = False

    # @return: whether the device is open
    def is_open(self) -> bool:
        return self._open

    # @return: identity and sensor limits
    def info(self) -> CameraInfo:
        return _make_info(self._camera_id, "Touptek", self._width, self._height)

    # @return: the current hardware ROI in SENSOR pixels
    def get_roi(self) -> ROI:
        return self._roi

    # @args: roi - SENSOR pixels, binned
    # @return: none
    def set_roi(self, roi: ROI) -> None:
        x, y, width, height = roi
        max_w = self._width // self._binning
        max_h = self._height // self._binning
        if (
            x < 0 or y < 0 or width <= 0 or height <= 0
            or x + width > max_w or y + height > max_h
            or x % OFFSET_MULTIPLE or y % OFFSET_MULTIPLE
            or width % WIDTH_MULTIPLE or height % HEIGHT_MULTIPLE
        ):
            raise DeviceError(
                f"ROI {roi!r} rejected by the Touptek constraints",
                code="roi_rejected", device_id=self._camera_id,
            )
        self._ensure_sdk()
        self._sdk.set_roi(roi)
        self._roi = roi

    # @return: the biggest ROI at the current binning
    def effective_area(self) -> ROI:
        return (0, 0, self._width // self._binning,
                self._height // self._binning)

    # @args: p - property to read
    # @return: its value in the unit fixed by Param
    def get_param(self, p: Param) -> float:
        self._ensure_sdk()
        if p == Param.EXPOSURE:
            return self._sdk.get_exposure()
        if p == Param.GAIN:
            return self._sdk.get_gain()
        if p == Param.BIT_DEPTH:
            return float(self._bit_depth)
        if p == Param.BINNING:
            return float(self._binning)
        if p == Param.READOUT:
            return float(self._sdk.get_option(TOUPCAM_OPTION_SPEED))
        raise DeviceError(
            f"Touptek does not expose {p.value}", code="not_supported",
            device_id=self._camera_id,
        )

    # @args: p - property; value - in the unit fixed by Param
    # @return: none
    def set_param(self, p: Param, value: float) -> None:
        self._ensure_sdk()
        if p == Param.EXPOSURE:
            self._sdk.set_exposure(value)
        elif p == Param.GAIN:
            self._sdk.set_gain(value)
        elif p == Param.READOUT:
            self._sdk.set_option(TOUPCAM_OPTION_SPEED, int(value))
        elif p == Param.BIT_DEPTH:
            raise DeviceError("Touptek bit depth is read-only",
                              code="not_supported",
                              device_id=self._camera_id)
        elif p == Param.BINNING:
            if int(value) != 1:
                raise DeviceError("Touptek binning > 1 is not wired yet",
                                  code="not_supported",
                                  device_id=self._camera_id)
        else:
            raise DeviceError(
                f"Touptek does not expose {p.value}", code="not_supported",
                device_id=self._camera_id,
            )

    # @args: p - property
    # @return: the interval the SDK accepts
    def param_range(self, p: Param) -> ParamRange:
        self._ensure_sdk()
        if p == Param.EXPOSURE:
            return self._sdk.exposure_range()
        if p == Param.GAIN:
            return self._sdk.gain_range()
        if p == Param.READOUT:
            return ParamRange(0.0, 100.0, 1.0)
        if p == Param.BIT_DEPTH:
            return ParamRange(16.0, 16.0, 0.0)
        if p == Param.BINNING:
            return ParamRange(1.0, 1.0, 1.0)
        raise DeviceError(
            f"Touptek does not expose {p.value}", code="not_supported",
            device_id=self._camera_id,
        )

    # @return: images the SDK failed to deliver since start_stream()
    def dropped_frames(self) -> int:
        return 0 if self._sdk is None else self._sdk.dropped_frames()

    # @args: on_frame - called on the driver thread with each owned frame
    # @return: none
    def start_stream(self, on_frame) -> None:
        if not self._open:
            raise DeviceError("camera is not open", code="not_open",
                              device_id=self._camera_id)
        if self._stream_thread is not None and self._stream_thread.is_alive():
            raise DeviceError("stream already running", code="already_streaming",
                              device_id=self._camera_id)
        self._on_frame = on_frame
        self._sequence = 0
        self._stream_stop.clear()
        self._image_event.clear()
        self._sdk.start(self._on_sdk_event)
        self._stream_thread = threading.Thread(
            target=self._run, name="touptek-capture", daemon=True,
        )
        self._stream_thread.start()

    # @args: none. Stops the stream and joins the driver thread
    # @return: none
    def stop_stream(self) -> None:
        self._stream_stop.set()
        self._image_event.set()
        if self._sdk is not None:
            self._sdk.stop()
        thread = self._stream_thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._stream_thread = None
        self._on_frame = None

    # @args: event - SDK event id; _context - unused
    # @return: none. Runs on the SDK thread: only signals, never copies
    def _on_sdk_event(self, event: int, _context) -> None:
        if event == TOUPCAM_EVENT_IMAGE:
            self._image_event.set()
        elif event in (TOUPCAM_EVENT_ERROR, TOUPCAM_EVENT_DISCONNECTED):
            self._sdk_error = "sdk_reported_error"
            self._stream_stop.set()
            self._image_event.set()

    # @args: none
    # @return: none. Pulls owned frames and calls the user callback
    def _run(self) -> None:
        while not self._stream_stop.is_set():
            if not self._image_event.wait(0.1):
                continue
            self._image_event.clear()
            if self._stream_stop.is_set():
                # stop_stream() sets the event only to wake this wait; pulling
                # here would deliver one frame after close, which a recording
                # must never contain.
                break
            try:
                array = self._sdk.pull()
            except Exception as exc:  # noqa: BLE001
                self._sdk_error = str(exc)
                continue
            sequence = self._sequence
            self._sequence += 1
            if array is None:
                # The SDK said "image" but delivered nothing: the sequence
                # still advances so the host sees the hole (ADR-013).
                continue
            frame = _ToupcamFrame(
                array, self._roi, sequence, time.monotonic(),
            )
            callback = self._on_frame
            if callback is not None:
                callback(frame)

    # @args: none
    # @return: none. Builds the ctypes wrapper on first use
    def _ensure_sdk(self) -> None:
        if self._sdk is not None:
            return
        if self._library is None:
            raise DeviceError("Touptek SDK library is not loaded",
                              code="sdk_missing",
                              device_id=self._camera_id)
        try:
            index = int(self._camera_id.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            index = 0
        self._sdk = CtypesToupcamSdk(self._library, index)


# @args: camera_id, model_name, width, height
# @return: CameraInfo with the Touptek constraints for that sensor
def _make_info(camera_id: str, model_name: str, width: int, height: int) -> CameraInfo:
    caps = CameraCaps(
        roi=RoiConstraints(
            max_width=width,
            max_height=height,
            width_multiple=WIDTH_MULTIPLE,
            height_multiple=HEIGHT_MULTIPLE,
            offset_multiple=OFFSET_MULTIPLE,
        ),
        is_color=False,
        bit_depths=(16,),
        binnings=(1,),
        has_cooler=False,
        reports_temperature=False,
    )
    return CameraInfo(
        camera_id=camera_id,
        vendor="Touptek",
        model=model_name,
        backend=BACKEND,
        caps=caps,
    )


class _ToupcamFrame:
    # Owned frame on the devices.Frame contract. Same copy-on-cut rule as the
    # simulator: a full-width strip is a view, anything narrower is copied.

    # @args: array - C-contiguous image the SDK wrapper already copied
    #        roi - sensor ROI; sequence - driver counter; timestamp - receipt
    def __init__(self, array: np.ndarray, roi: ROI, sequence: int,
                 timestamp: float) -> None:
        self._array = np.ascontiguousarray(array)
        self.data = memoryview(self._array)
        self.height, self.width = self._array.shape
        self.dtype = self._array.dtype
        self.roi = roi
        self.sequence = sequence
        self.timestamp = timestamp
        self._stats_cache = None

    # @return: mean and standard deviation of the frame
    def stats(self):
        if self._stats_cache is None:
            self._stats_cache = (float(self._array.mean()),
                                 float(self._array.std()))
        return _Stats(*self._stats_cache)

    # @args: roi - sub-region in FRAME pixels
    # @return: the sub-region as an owned frame
    def cut_roi(self, roi: ROI):
        x, y, width, height = roi
        if x == 0 and width == self.width:
            sub = self._array[y:y + height, :]
        else:
            sub = np.ascontiguousarray(self._array[y:y + height, x:x + width])
        return _ToupcamFrame(sub, self.roi, self.sequence, self.timestamp)


class _Stats:
    # @args: mean, std - the two FrameStats numbers
    # @return: none
    def __init__(self, mean: float, std: float) -> None:
        self.mean = mean
        self.std = std
