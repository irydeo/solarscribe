############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native qhy module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# QHY native driver (libqhyccd, ADR-002).
#
# QHY has two quirks that decide the shape of this module:
#   1. The SDK is process-global: InitQHYCCDResource/ReleaseQHYCCDResource are
#      counted here, so discovery and a camera can coexist without releasing
#      the resource under each other's feet.
#   2. Opening and closing a camera during discovery corrupts the SDK's USB
#      state until the camera is replugged. Discovery therefore lists the ids
#      and reports no sensor size; the first open() reads the real chip and
#      corrects info(). That is why the discovery caps are nominal 1x1: better
#      an honest "unknown" than an invented geometry the ROI step would trust.
#
# Signatures follow qhyccdcamdef.h: every function returns uint32 (0 = success)
# except OpenQHYCCD, which returns a void* handle. That handle is the reason the
# table exists: with the ctypes default c_int restype it is truncated on a
# 64-bit machine and the first call with it segfaults.
#
# Hardware validation: the signatures and the command order are exercised with
# a mocked library. A real QHY camera was not attached to the validation
# machine; the hardware test enumerates and skips when none is present, so the
# report must state that the QHY path is unverified on hardware.

from __future__ import annotations

import ctypes
import threading
import time

import numpy as np

from solarscribe.devices.abc import (
    ROI, CameraCaps, CameraInfo, DeviceError, Param, ParamRange, RoiConstraints,
)
from solarscribe.devices.native.frame import SdkFrame
from solarscribe.devices.native.signatures import apply_signatures

__all__ = ["LIBRARIES", "QhyCamera", "QhySdk", "SIGNATURES", "backend"]

NAME = "native/qhy"
VENDOR = "QHY"
LIBRARIES = ("libqhyccd.so", "libqhyccd.dylib", "qhyccd.dll")

QHY_SUCCESS = 0

# QHYCCD control ids (qhyccdcamdef.h) used by the driver.
QHY_GAIN = 6
QHY_OFFSET = 7
QHY_EXPOSURE = 8
QHY_SPEED = 9

# Stream mode: 0 single frame, 1 live.
QHY_LIVE = 1

# ROI: the SDK accepts any rectangle inside the chip. Minimum 1 px; the scan
# uses 3480x248 anyway and the digest of a too small ROI is a slow readout, not
# an SDK error.
WIDTH_MULTIPLE = 1
HEIGHT_MULTIPLE = 1
MIN_SIZE = 1

# Discovery cannot know the chip without opening it (see the module comment).
# These caps are replaced by the real ones on open(); they exist so a camera
# still appears in the list.
NOMINAL_WIDTH = 1
NOMINAL_HEIGHT = 1


class QhySdk:
    # Thin ctypes wrapper. One instance serves discovery and every camera; the
    # QHY API is handle based, but the resource is global.

    # @args: library - loaded CDLL (or a test double)
    def __init__(self, library) -> None:
        self._lib = library
        apply_signatures(library, SIGNATURES)

    # @args: none
    # @return: none. Raises DeviceError when the SDK refuses to start
    def init_resource(self) -> None:
        self._check("InitQHYCCDResource", self._lib.InitQHYCCDResource())

    # @args: none
    # @return: none
    def release_resource(self) -> None:
        try:
            self._lib.ReleaseQHYCCDResource()
        except Exception:  # noqa: BLE001 - releasing twice is harmless
            pass

    # @args: none
    # @return: the number of cameras the SDK sees, or 0 when the scan failed.
    #          ScanQHYCCD returns 0xFFFFFFFF on error, and the old code fed
    #          that straight into range(): 4.29 billion GetQHYCCDId calls that
    #          froze "Find cameras" forever.
    def scan(self) -> int:
        count = int(self._lib.ScanQHYCCD())
        if count == 0xFFFFFFFF or count > 64:
            return 0
        return count

    # @args: index - position in the scan
    # @return: the camera id string
    def get_id(self, index: int) -> str:
        buffer = ctypes.create_string_buffer(64)
        status = self._lib.GetQHYCCDId(index, buffer)
        self._check("GetQHYCCDId", status)
        return buffer.value.decode("ascii", "replace")

    # @args: camera_id - id from get_id()
    # @return: the handle (void*)
    def open(self, camera_id: str) -> int:
        handle = self._lib.OpenQHYCCD(camera_id.encode("ascii"))
        if not handle:
            raise DeviceError(f"OpenQHYCCD({camera_id!r}) returned no handle",
                              code="device_lost")
        return handle

    # @args: handle - camera handle
    # @return: none
    def close(self, handle) -> None:
        self._check("CloseQHYCCD", self._lib.CloseQHYCCD(handle))

    # @args: handle, mode - stream mode
    # @return: none
    def set_stream_mode(self, handle, mode: int) -> None:
        self._check(
            "SetQHYCCDStreamMode",
            self._lib.SetQHYCCDStreamMode(handle, mode),
        )

    # @args: handle - camera handle
    # @return: none
    def init_camera(self, handle) -> None:
        self._check("InitQHYCCD", self._lib.InitQHYCCD(handle))

    # @args: handle - camera handle
    # @return: (image_width, image_height, bits_per_pixel)
    def chip_info(self, handle) -> tuple[int, int, int]:
        chip_w, chip_h = ctypes.c_double(0), ctypes.c_double(0)
        width, height = ctypes.c_uint32(0), ctypes.c_uint32(0)
        pixel_w, pixel_h = ctypes.c_double(0), ctypes.c_double(0)
        bits = ctypes.c_uint32(0)
        status = self._lib.GetQHYCCDChipInfo(
            handle, ctypes.byref(chip_w), ctypes.byref(chip_h),
            ctypes.byref(width), ctypes.byref(height),
            ctypes.byref(pixel_w), ctypes.byref(pixel_h),
            ctypes.byref(bits),
        )
        self._check("GetQHYCCDChipInfo", status)
        return int(width.value), int(height.value), int(bits.value)

    # @args: handle, x, y, width, height - SENSOR pixels
    # @return: none
    def set_resolution(self, handle, roi: ROI) -> None:
        x, y, width, height = roi
        self._check(
            "SetQHYCCDResolution",
            self._lib.SetQHYCCDResolution(handle, x, y, width, height),
        )

    # @args: handle, bits - 8 or 16
    # @return: none
    def set_bits_mode(self, handle, bits: int) -> None:
        self._check(
            "SetQHYCCDBitsMode", self._lib.SetQHYCCDBitsMode(handle, bits),
        )

    # @args: handle, control - QHY control id; value - SDK units
    # @return: none
    def set_param(self, handle, control: int, value: float) -> None:
        self._check(
            f"SetQHYCCDParam({control})",
            self._lib.SetQHYCCDParam(handle, control, float(value)),
        )

    # @args: handle, control - QHY control id
    # @return: its value in SDK units
    def get_param(self, handle, control: int) -> float:
        return float(self._lib.GetQHYCCDParam(handle, control))

    # @args: handle, control - QHY control id
    # @return: (min, max, step)
    def param_range(self, handle, control: int) -> ParamRange:
        minimum, maximum, step = (ctypes.c_double(0) for _ in range(3))
        status = self._lib.GetQHYCCDParamMinMaxStep(
            handle, control, ctypes.byref(minimum), ctypes.byref(maximum),
            ctypes.byref(step),
        )
        if status != QHY_SUCCESS:
            raise DeviceError(
                f"GetQHYCCDParamMinMaxStep({control}) failed",
                code="not_supported",
            )
        return ParamRange(minimum.value, maximum.value, step.value)

    # @args: handle - camera handle
    # @return: bytes the SDK needs for one frame
    def mem_length(self, handle) -> int:
        return int(self._lib.GetQHYCCDMemLength(handle))

    # @args: handle - camera handle
    # @return: none
    def begin_live(self, handle) -> None:
        self._check("BeginQHYCCDLive", self._lib.BeginQHYCCDLive(handle))

    # @args: handle, buffer - destination
    # @return: (width, height, bits) or None when no frame was ready
    def read_live(self, handle, buffer):
        width, height = ctypes.c_uint32(0), ctypes.c_uint32(0)
        bits, channels = ctypes.c_uint32(0), ctypes.c_uint32(0)
        status = self._lib.GetQHYCCDLiveFrame(
            handle, ctypes.byref(width), ctypes.byref(height),
            ctypes.byref(bits), ctypes.byref(channels),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint8)),
        )
        if status != QHY_SUCCESS:
            return None
        return int(width.value), int(height.value), int(bits.value)

    # @args: handle - camera handle
    # @return: none
    def stop_live(self, handle) -> None:
        try:
            self._lib.StopQHYCCDLive(handle)
        except Exception:  # noqa: BLE001 - stopping a dead camera is harmless
            pass

    # @args: handle - camera handle
    # @return: none
    def cancel(self, handle) -> None:
        try:
            self._lib.CancelQHYCCDExposingAndReadout(handle)
        except Exception:  # noqa: BLE001
            pass

    # @args: name - SDK call; status - its return code
    # @return: none
    def _check(self, name: str, status: int) -> None:
        if status != QHY_SUCCESS:
            raise DeviceError(f"{name} failed with QHY code 0x{status:08X}",
                              code="sdk_error")


SIGNATURES = {
    "InitQHYCCDResource": (ctypes.c_uint32, []),
    "ReleaseQHYCCDResource": (ctypes.c_uint32, []),
    "ScanQHYCCD": (ctypes.c_uint32, []),
    "GetQHYCCDId": (ctypes.c_uint32, [ctypes.c_int, ctypes.c_char_p]),
    # The handle is a pointer. restype c_void_p is what stops the 32-bit
    # truncation that segfaults the next call.
    "OpenQHYCCD": (ctypes.c_void_p, [ctypes.c_char_p]),
    "CloseQHYCCD": (ctypes.c_uint32, [ctypes.c_void_p]),
    "SetQHYCCDStreamMode": (ctypes.c_uint32, [ctypes.c_void_p, ctypes.c_uint8]),
    "InitQHYCCD": (ctypes.c_uint32, [ctypes.c_void_p]),
    "GetQHYCCDChipInfo": (
        ctypes.c_uint32,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double),
         ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_uint32),
         ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_double),
         ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_uint32)],
    ),
    "SetQHYCCDResolution": (
        ctypes.c_uint32,
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
         ctypes.c_uint32, ctypes.c_uint32],
    ),
    "SetQHYCCDBitsMode": (ctypes.c_uint32, [ctypes.c_void_p, ctypes.c_uint32]),
    "SetQHYCCDParam": (
        ctypes.c_uint32, [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_double],
    ),
    "GetQHYCCDParam": (ctypes.c_double, [ctypes.c_void_p, ctypes.c_uint32]),
    "GetQHYCCDParamMinMaxStep": (
        ctypes.c_uint32,
        [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_double),
         ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double)],
    ),
    "GetQHYCCDMemLength": (ctypes.c_uint32, [ctypes.c_void_p]),
    "BeginQHYCCDLive": (ctypes.c_uint32, [ctypes.c_void_p]),
    "GetQHYCCDLiveFrame": (
        ctypes.c_uint32,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
         ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
         ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint8)],
    ),
    "StopQHYCCDLive": (ctypes.c_uint32, [ctypes.c_void_p]),
    "CancelQHYCCDExposingAndReadout": (ctypes.c_uint32, [ctypes.c_void_p]),
}


# The SDK resource is process-wide; count users so two managers (or discovery
# plus an open camera) do not release it under each other.
_resource_lock = threading.Lock()
_resource_users = 0


# @args: sdk - QhySdk
# @return: none. Initializes the resource on the first user only
def _acquire_resource(sdk: QhySdk) -> None:
    global _resource_users
    with _resource_lock:
        if _resource_users == 0:
            sdk.init_resource()
        _resource_users += 1


# @args: sdk - QhySdk
# @return: none. Releases the resource when the last user is gone
def _release_resource(sdk: QhySdk) -> None:
    global _resource_users
    with _resource_lock:
        if _resource_users > 0:
            _resource_users -= 1
        if _resource_users == 0:
            sdk.release_resource()


class QhyCamera:
    # Camera contract over the QHY SDK (ADR-002, ADR-012).

    # @args: camera_id - "native/qhy:<sdk id>"
    #        library - loaded CDLL; ignored when sdk is given
    #        sdk - injectable wrapper, for the unit tests
    def __init__(self, camera_id: str, library=None, sdk=None) -> None:
        self._camera_id = camera_id
        self._sdk_id = camera_id.split(":", 1)[1] if ":" in camera_id else camera_id
        self._sdk = sdk if sdk is not None else QhySdk(library)
        self._handle = None
        self._resource = False
        self._open = False
        self._width = NOMINAL_WIDTH
        self._height = NOMINAL_HEIGHT
        self._roi: ROI = (0, 0, NOMINAL_WIDTH, NOMINAL_HEIGHT)
        self._bit_depth = 16
        self._sequence = 0
        self._buffer = None
        self._buffer_nbytes = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._on_frame = None

    # @args: library - loaded CDLL
    # @return: the cameras the SDK reports. It does NOT open them: the QHY
    #          SDK's USB state breaks if a device is opened and closed here.
    @classmethod
    def discover(cls, library) -> list[CameraInfo]:
        sdk = QhySdk(library)
        _acquire_resource(sdk)
        try:
            count = sdk.scan()
            infos = []
            for index in range(max(0, count)):
                try:
                    camera_id = sdk.get_id(index)
                except DeviceError:
                    continue
                if not camera_id:
                    continue
                infos.append(CameraInfo(
                    camera_id=f"{NAME}:{camera_id}",
                    vendor=VENDOR,
                    model=camera_id.split("-")[0],
                    backend=NAME,
                    caps=CameraCaps(
                        roi=RoiConstraints(
                            max_width=NOMINAL_WIDTH,
                            max_height=NOMINAL_HEIGHT,
                            width_multiple=WIDTH_MULTIPLE,
                            height_multiple=HEIGHT_MULTIPLE,
                            offset_multiple=1,
                        ),
                        bit_depths=(8, 16),
                        binnings=(1,),
                    ),
                ))
            return infos
        finally:
            _release_resource(sdk)

    # @args: none. Raises DeviceError when the SDK refuses to open or init
    # @return: none
    def open(self) -> None:
        if self._open:
            return
        try:
            _acquire_resource(self._sdk)
            self._resource = True
            self._handle = self._sdk.open(self._sdk_id)
            # The order is the QHY contract: stream mode before InitQHYCCD,
            # then bits and resolution, then live. Changing it makes init fail
            # silently on several models.
            self._sdk.set_stream_mode(self._handle, QHY_LIVE)
            self._sdk.init_camera(self._handle)
            self._width, self._height, self._bit_depth = self._sdk.chip_info(
                self._handle,
            )
            self._sdk.set_bits_mode(self._handle, 16)
            self._bit_depth = 16
            self._roi = (0, 0, self._width, self._height)
            self._sdk.set_resolution(self._handle, self._roi)
            self._buffer_nbytes = max(1, self._sdk.mem_length(self._handle))
            self._buffer = None
            self._open = True
        except DeviceError:
            self._release()
            raise
        except Exception as exc:  # noqa: BLE001
            self._release()
            raise DeviceError(f"could not open {self._camera_id}: {exc}",
                              code="device_lost",
                              device_id=self._camera_id) from exc

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        self.stop_stream()
        self._release()
        self._open = False

    # @return: whether the camera is open
    def is_open(self) -> bool:
        return self._open

    # @return: identity and sensor limits
    def info(self) -> CameraInfo:
        return CameraInfo(
            camera_id=self._camera_id,
            vendor=VENDOR,
            model=self._sdk_id.split("-")[0],
            backend=NAME,
            caps=CameraCaps(
                roi=RoiConstraints(
                    max_width=self._width, max_height=self._height,
                    width_multiple=WIDTH_MULTIPLE,
                    height_multiple=HEIGHT_MULTIPLE,
                    offset_multiple=1,
                ),
                bit_depths=(16,),
                binnings=(1,),
            ),
        )

    # @return: the current hardware ROI in SENSOR pixels
    def get_roi(self) -> ROI:
        return self._roi

    # @args: roi - SENSOR pixels
    # @return: none
    def set_roi(self, roi: ROI) -> None:
        x, y, width, height = roi
        if (
            x < 0 or y < 0 or width < MIN_SIZE or height < MIN_SIZE
            or x + width > self._width or y + height > self._height
        ):
            raise DeviceError(f"ROI {roi!r} rejected by the QHY constraints",
                              code="roi_rejected",
                              device_id=self._camera_id)
        self._ensure_open()
        self._sdk.set_resolution(self._handle, roi)
        self._roi = roi

    # @return: the biggest ROI
    def effective_area(self) -> ROI:
        return (0, 0, self._width, self._height)

    # @args: p - property to read
    # @return: its value in the unit fixed by Param
    def get_param(self, p: Param) -> float:
        if p == Param.BIT_DEPTH:
            self._ensure_open()
            return float(self._bit_depth)
        if p == Param.BINNING:
            return 1.0
        control = _control_of(p)
        if control is None:
            raise _unsupported(p, self._camera_id)
        self._ensure_open()
        return self._sdk.get_param(self._handle, control)

    # @args: p - property; value - in the unit fixed by Param
    # @return: none
    def set_param(self, p: Param, value: float) -> None:
        control = _control_of(p)
        if control is None:
            raise _unsupported(p, self._camera_id)
        self._ensure_open()
        self._sdk.set_param(self._handle, control, value)

    # @args: p - property
    # @return: the interval the SDK accepts
    def param_range(self, p: Param) -> ParamRange:
        if p == Param.BIT_DEPTH:
            return ParamRange(16.0, 16.0, 0.0)
        if p == Param.BINNING:
            return ParamRange(1.0, 1.0, 0.0)
        control = _control_of(p)
        if control is None:
            raise _unsupported(p, self._camera_id)
        self._ensure_open()
        return self._sdk.param_range(self._handle, control)

    # @return: 0. The QHY SDK exposes no dropped-frame counter, so the SDK
    #          column stays at zero; the host still counts sequence gaps and
    #          queue overflows (ADR-013), and the health panel says which
    #          counter is blind.
    def dropped_frames(self) -> int:
        return 0

    # @args: on_frame - called on the driver thread with each owned frame
    # @return: none
    def start_stream(self, on_frame) -> None:
        self._ensure_open()
        if self._thread is not None and self._thread.is_alive():
            raise DeviceError("stream already running", code="already_streaming",
                              device_id=self._camera_id)
        self._sdk.begin_live(self._handle)
        self._on_frame = on_frame
        self._sequence = 0
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="qhy-capture", daemon=True,
        )
        self._thread.start()

    # @args: none. Stops the stream and joins the driver thread
    # @return: none
    def stop_stream(self) -> None:
        self._stop.set()
        if self._handle is not None:
            self._sdk.stop_live(self._handle)
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._on_frame = None

    # @args: none
    # @return: none. Polls the SDK buffer and calls the user callback
    def _run(self) -> None:
        _, _, width, height = self._roi
        nbytes = width * height * 2
        if self._buffer is None or self._buffer_nbytes < nbytes:
            self._buffer_nbytes = max(nbytes, self._buffer_nbytes or 0)
            self._buffer = ctypes.create_string_buffer(self._buffer_nbytes)
        while not self._stop.is_set():
            try:
                frame = self._sdk.read_live(self._handle, self._buffer)
            except Exception:  # noqa: BLE001 - a dead camera ends the stream
                break
            if frame is None:
                # No frame was ready. A short sleep keeps this thread from
                # spinning at 100% while the camera is still integrating.
                time.sleep(0.001)
                continue
            frame_width, frame_height, bits = frame
            sequence = self._sequence
            self._sequence += 1
            dtype = np.uint16 if bits > 8 else np.uint8
            array = np.frombuffer(
                self._buffer, dtype=dtype,
                count=frame_width * frame_height,
            ).reshape(frame_height, frame_width).copy()
            callback = self._on_frame
            if callback is not None:
                callback(SdkFrame(array, self._roi, sequence,
                                  time.monotonic()))

    # @args: none
    # @return: none. Closes the handle and releases the resource once
    def _release(self) -> None:
        if self._handle is not None:
            try:
                self._sdk.cancel(self._handle)
            finally:
                try:
                    self._sdk.close(self._handle)
                except Exception:  # noqa: BLE001 - a dead handle is harmless
                    pass
                self._handle = None
        if self._resource:
            _release_resource(self._sdk)
            self._resource = False

    # @args: none
    # @return: none. Raises DeviceError when open() was not called
    def _ensure_open(self) -> None:
        if not self._open:
            raise DeviceError("camera is not open", code="not_open",
                              device_id=self._camera_id)


# @args: p - device property
# @return: the QHY control id, or None when the driver handles it itself
def _control_of(p: Param):
    return {
        Param.EXPOSURE: QHY_EXPOSURE,
        Param.GAIN: QHY_GAIN,
        Param.OFFSET: QHY_OFFSET,
        Param.READOUT: QHY_SPEED,
    }.get(p)


# @args: param - the unsupported property; camera_id - which camera
# @return: the DeviceError to raise
def _unsupported(param: Param, camera_id: str) -> DeviceError:
    return DeviceError(f"QHY does not expose {param.value}",
                       code="not_supported", device_id=camera_id)


# @args: loader - injectable library loader, for the tests
# @return: the backend descriptor the DeviceManager probes
def backend(loader=None):
    from solarscribe.devices.native.backend import NativeCameraBackend

    kwargs = {} if loader is None else {"loader": loader}
    return NativeCameraBackend(NAME, VENDOR, LIBRARIES,
                               driver=QhyCamera, **kwargs)
