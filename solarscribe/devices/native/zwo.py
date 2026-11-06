############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native zwo module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# ZWO ASI native driver (libASICamera2, ADR-002).
#
# The ASI SDK does not return a handle: every call carries the camera index, so
# there is no pointer to truncate. The crash risk here is the opposite one: the
# camera-info struct is filled by the SDK and a wrong field order or width is a
# heap overflow. The layout below is the published ASI_CAMERA_INFO: 64-byte
# name, four ints, sixteen ints of binning, eight ints of formats, a double and
# six more ints. `long` is kept as the SDK declares it, because on Windows it
# is 4 bytes and on Linux 8; hardcoding c_int would shift every field after it.
#
# Contract mapping: exposure/gain/offset/bandwidth are ASI controls in
# microseconds and SDK units; the stream is pull mode with ASIGetVideoData and
# a 200 ms timeout, and ASIGetDroppedFrames is the SDK drop counter (ADR-013).
#
# Hardware validation: the signatures are exercised with a mocked library in
# the unit suite. A real ASI camera was not attached to the validation machine,
# so the hardware test enumerates and skips when none is present; the report
# must say so.

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

__all__ = ["AsiCamera", "AsiSdk", "LIBRARIES", "SIGNATURES", "backend"]

NAME = "native/asi"
VENDOR = "ZWO"
LIBRARIES = ("libASICamera2.so", "libASICamera2.dylib", "ASICamera2.dll")

ASI_SUCCESS = 0
ASI_ERROR_TIMEOUT = 11

# ASI_CONTROL_TYPE values used by the driver.
ASI_GAIN = 0
ASI_EXPOSURE = 1
ASI_OFFSET = 5
ASI_BANDWIDTH = 6
ASI_TEMPERATURE = 8

# ASI_IMG_TYPE. The SHG works on RAW16: the SER contract is 16 bit, and RAW
# avoids the SDK's debayer (we want the plane, not a colour image).
ASI_IMG_RAW16 = 2

# ASI ROI rules: width multiple of 8, height multiple of 2. Start position is
# free. These are the published limits; a wrong rectangle is refused by
# ASISetROIFormat and the ROI step validates before calling.
WIDTH_MULTIPLE = 8
HEIGHT_MULTIPLE = 2
MIN_SIZE = 8


class _AsiCameraInfo(ctypes.Structure):
    _fields_ = [
        ("Name", ctypes.c_char * 64),
        ("CameraID", ctypes.c_int),
        ("MaxHeight", ctypes.c_long),
        ("MaxWidth", ctypes.c_long),
        ("IsColorCam", ctypes.c_int),
        ("BayerPattern", ctypes.c_int),
        ("SupportedBins", ctypes.c_int * 16),
        ("SupportedVideoFormat", ctypes.c_int * 8),
        ("PixelSize", ctypes.c_double),
        ("MechanicalShutter", ctypes.c_int),
        ("ST4Port", ctypes.c_int),
        ("IsCoolerCam", ctypes.c_int),
        ("IsUSB3Host", ctypes.c_int),
        ("IsUSB3Camera", ctypes.c_int),
        ("ElecPerADU", ctypes.c_float),
        ("BitDepth", ctypes.c_int),
        ("IsTriggerCam", ctypes.c_int),
        ("Unused", ctypes.c_char * 16),
    ]


class _AsiControlCaps(ctypes.Structure):
    _fields_ = [
        ("Name", ctypes.c_char * 64),
        ("Description", ctypes.c_char * 128),
        ("MaxValue", ctypes.c_long),
        ("MinValue", ctypes.c_long),
        ("DefaultValue", ctypes.c_long),
        ("IsAutoSupported", ctypes.c_int),
        ("IsWritable", ctypes.c_int),
        ("ControlType", ctypes.c_int),
        ("Unused", ctypes.c_char * 32),
    ]


SIGNATURES = {
    "ASIGetNumOfConnectedCameras": (ctypes.c_int, []),
    "ASIGetCameraProperty": (
        ctypes.c_int, [ctypes.POINTER(_AsiCameraInfo), ctypes.c_int],
    ),
    "ASIOpenCamera": (ctypes.c_int, [ctypes.c_int]),
    "ASIInitCamera": (ctypes.c_int, [ctypes.c_int]),
    "ASICloseCamera": (ctypes.c_int, [ctypes.c_int]),
    "ASISetROIFormat": (
        ctypes.c_int, [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.c_int, ctypes.c_int],
    ),
    "ASIGetROIFormat": (
        ctypes.c_int,
        [ctypes.c_int, ctypes.POINTER(ctypes.c_int),
         ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
         ctypes.POINTER(ctypes.c_int)],
    ),
    "ASISetStartPos": (ctypes.c_int, [ctypes.c_int, ctypes.c_int, ctypes.c_int]),
    "ASIGetStartPos": (
        ctypes.c_int,
        [ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)],
    ),
    "ASIGetNumOfControls": (
        ctypes.c_int, [ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
    ),
    "ASIGetControlCaps": (
        ctypes.c_int,
        [ctypes.c_int, ctypes.c_int, ctypes.POINTER(_AsiControlCaps)],
    ),
    "ASIGetControlValue": (
        ctypes.c_int,
        [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_long),
         ctypes.POINTER(ctypes.c_int)],
    ),
    "ASISetControlValue": (
        ctypes.c_int,
        [ctypes.c_int, ctypes.c_int, ctypes.c_long, ctypes.c_int],
    ),
    "ASIStartVideoCapture": (ctypes.c_int, [ctypes.c_int]),
    "ASIStopVideoCapture": (ctypes.c_int, [ctypes.c_int]),
    "ASIGetVideoData": (
        ctypes.c_int,
        [ctypes.c_int, ctypes.POINTER(ctypes.c_uint8), ctypes.c_long,
         ctypes.c_int],
    ),
    "ASIGetDroppedFrames": (
        ctypes.c_int, [ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
    ),
}


class AsiSdk:
    # One ctypes wrapper for the whole SDK; the ASI API is index based, so one
    # object serves discovery and every camera instance.

    # @args: library - loaded CDLL (or a test double)
    def __init__(self, library) -> None:
        self._lib = library
        apply_signatures(library, SIGNATURES)

    # @return: the cameras the SDK reports, read without opening them
    def camera_infos(self) -> list[_AsiCameraInfo]:
        count = int(self._lib.ASIGetNumOfConnectedCameras())
        infos = []
        for index in range(max(0, count)):
            info = _AsiCameraInfo()
            status = self._lib.ASIGetCameraProperty(
                ctypes.byref(info), index,
            )
            if status != ASI_SUCCESS:
                continue
            infos.append(info)
        return infos

    # @args: index - camera index
    # @return: open + init, ready for ROI and streaming
    def open(self, index: int) -> None:
        self._check("ASIOpenCamera", self._lib.ASIOpenCamera(index))
        try:
            self._check("ASIInitCamera", self._lib.ASIInitCamera(index))
        except DeviceError:
            self._lib.ASICloseCamera(index)
            raise

    # @args: index - camera index
    # @return: none
    def close(self, index: int) -> None:
        self._lib.ASICloseCamera(index)

    # @args: index, x, y, width, height - SENSOR pixels
    # @return: none
    def set_roi(self, index: int, roi: ROI) -> None:
        x, y, width, height = roi
        # Format first, then the start position: the SDK validates the origin
        # against the current format, so the other order can clamp it.
        self._check(
            "ASISetROIFormat",
            self._lib.ASISetROIFormat(
                index, width, height, 1, ASI_IMG_RAW16,
            ),
        )
        self._check("ASISetStartPos", self._lib.ASISetStartPos(index, x, y))

    # @args: index - camera index
    # @return: the ROI the SDK reports
    def get_roi(self, index: int) -> ROI:
        width, height, _bin, _img = (ctypes.c_int(0) for _ in range(4))
        status = self._lib.ASIGetROIFormat(
            index, ctypes.byref(width), ctypes.byref(height),
            ctypes.byref(_bin), ctypes.byref(_img),
        )
        self._check("ASIGetROIFormat", status)
        x, y = ctypes.c_int(0), ctypes.c_int(0)
        status = self._lib.ASIGetStartPos(
            index, ctypes.byref(x), ctypes.byref(y),
        )
        self._check("ASIGetStartPos", status)
        return (int(x.value), int(y.value),
                int(width.value), int(height.value))

    # @args: index, control - ASI control id; value - SDK units
    # @return: none
    def set_control(self, index: int, control: int, value: int) -> None:
        status = self._lib.ASISetControlValue(
            index, control, int(value), 0,
        )
        self._check(f"ASISetControlValue({control})", status)

    # @args: index, control - ASI control id
    # @return: the value in SDK units and whether the SDK says it is auto
    def get_control(self, index: int, control: int) -> tuple[int, bool]:
        value = ctypes.c_long(0)
        auto = ctypes.c_int(0)
        status = self._lib.ASIGetControlValue(
            index, control, ctypes.byref(value), ctypes.byref(auto),
        )
        self._check(f"ASIGetControlValue({control})", status)
        return int(value.value), bool(auto.value)

    # @args: index, control - ASI control id
    # @return: (min, max, step); step 1 because ASI controls are integral
    def control_range(self, index: int, control: int) -> ParamRange:
        count = ctypes.c_int(0)
        status = self._lib.ASIGetNumOfControls(index, ctypes.byref(count))
        self._check("ASIGetNumOfControls", status)
        for position in range(max(0, count.value)):
            caps = _AsiControlCaps()
            status = self._lib.ASIGetControlCaps(
                index, position, ctypes.byref(caps),
            )
            if status != ASI_SUCCESS:
                continue
            if int(caps.ControlType) == control:
                return ParamRange(
                    float(caps.MinValue), float(caps.MaxValue), 1.0,
                )
        raise DeviceError(
            f"ASI does not expose control {control}", code="not_supported",
        )

    # @args: index - camera index
    # @return: none. Starts the video stream
    def start_video(self, index: int) -> None:
        self._check(
            "ASIStartVideoCapture", self._lib.ASIStartVideoCapture(index),
        )

    # @args: index - camera index
    # @return: none
    def stop_video(self, index: int) -> None:
        self._lib.ASIStopVideoCapture(index)

    # @args: index - camera index
    # @return: the SDK drop counter
    def dropped(self, index: int) -> int:
        value = ctypes.c_int(0)
        status = self._lib.ASIGetDroppedFrames(
            index, ctypes.byref(value),
        )
        self._check("ASIGetDroppedFrames", status)
        return int(value.value)

    # @args: index, buffer - destination; timeout_ms - wait for a frame
    # @return: True when a frame was copied, False on timeout
    def read(self, index: int, buffer, nbytes: int,
             timeout_ms: int = 200) -> bool:
        status = self._lib.ASIGetVideoData(
            index, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint8)),
            nbytes, timeout_ms,
        )
        if status == ASI_ERROR_TIMEOUT:
            # No frame was due: a timeout is not a dropped frame and must not
            # inflate the health panel (ADR-013 counts drops, not idle polls).
            return False
        self._check("ASIGetVideoData", status)
        return True

    # @args: name - SDK call; status - its return code
    # @return: none. Raises DeviceError with a stable code
    def _check(self, name: str, status: int) -> None:
        if status != ASI_SUCCESS:
            raise DeviceError(f"{name} failed with ASI code {status}",
                              code="sdk_error")


class AsiCamera:
    # Camera contract over the ASI SDK (ADR-002, ADR-012).

    # @args: camera_id - "native/asi:<index>"
    #        library - loaded CDLL; ignored when sdk is given
    #        sdk - injectable wrapper, for the unit tests
    def __init__(self, camera_id: str, library=None, sdk=None) -> None:
        self._camera_id = camera_id
        self._index = _index_of(camera_id)
        self._sdk = sdk if sdk is not None else AsiSdk(library)
        self._open = False
        self._width = 0
        self._height = 0
        self._roi: ROI = (0, 0, 0, 0)
        self._bit_depth = 16
        self._is_color = False
        self._has_cooler = False
        self._sequence = 0
        self._buffer = None
        self._buffer_nbytes = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._on_frame = None

    # @args: library - loaded CDLL
    # @return: the cameras the SDK reports
    @classmethod
    def discover(cls, library) -> list[CameraInfo]:
        sdk = AsiSdk(library)
        return [_info(sdk, index, info)
                for index, info in enumerate(sdk.camera_infos())]

    # @args: none. Raises DeviceError when the SDK refuses the camera
    # @return: none
    def open(self) -> None:
        try:
            self._sdk.open(self._index)
            info = self._sdk.camera_infos()
            if self._index >= len(info):
                raise DeviceError("ASI camera disappeared during open",
                                  code="device_lost",
                                  device_id=self._camera_id)
            raw = info[self._index]
            self._width = int(raw.MaxWidth)
            self._height = int(raw.MaxHeight)
            self._bit_depth = 16 if int(raw.BitDepth) >= 16 else 8
            self._is_color = bool(raw.IsColorCam)
            self._has_cooler = bool(raw.IsCoolerCam)
            self._roi = self._sdk.get_roi(self._index)
            self._open = True
        except DeviceError:
            if not self._open:
                self._safe_close()
            raise
        except Exception as exc:  # noqa: BLE001
            self._safe_close()
            raise DeviceError(f"could not open {self._camera_id}: {exc}",
                              code="device_lost",
                              device_id=self._camera_id) from exc

    # @args: none
    # @return: none. Best-effort close used when open() fails half way
    def _safe_close(self) -> None:
        try:
            self._sdk.close(self._index)
        except Exception:  # noqa: BLE001 - the camera may never have opened
            pass

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        self.stop_stream()
        if self._open:
            self._sdk.close(self._index)
        self._open = False

    # @return: whether the camera is open
    def is_open(self) -> bool:
        return self._open

    # @return: identity and sensor limits
    def info(self) -> CameraInfo:
        return CameraInfo(
            camera_id=self._camera_id,
            vendor=VENDOR,
            model=f"ASI camera {self._index}",
            backend=NAME,
            caps=CameraCaps(
                roi=RoiConstraints(
                    max_width=self._width or 1,
                    max_height=self._height or 1,
                    min_width=MIN_SIZE, min_height=MIN_SIZE,
                    width_multiple=WIDTH_MULTIPLE,
                    height_multiple=HEIGHT_MULTIPLE,
                    offset_multiple=1,
                ),
                is_color=self._is_color,
                bit_depths=(self._bit_depth,),
                binnings=(1,),
                has_cooler=self._has_cooler,
                reports_temperature=self._has_cooler,
            ),
        )

    # @return: the current hardware ROI in SENSOR pixels
    def get_roi(self) -> ROI:
        return self._roi

    # @args: roi - SENSOR pixels
    # @return: none
    def set_roi(self, roi: ROI) -> None:
        x, y, width, height = roi
        max_w, max_h = self._width, self._height
        if (
            x < 0 or y < 0 or width < MIN_SIZE or height < MIN_SIZE
            or x + width > max_w or y + height > max_h
            or width % WIDTH_MULTIPLE or height % HEIGHT_MULTIPLE
        ):
            raise DeviceError(f"ROI {roi!r} rejected by the ASI constraints",
                              code="roi_rejected",
                              device_id=self._camera_id)
        self._sdk.set_roi(self._index, roi)
        self._roi = roi
        self._buffer = None

    # @return: the biggest ROI at binning 1
    def effective_area(self) -> ROI:
        return (0, 0, self._width, self._height)

    # @args: p - property to read
    # @return: its value in the unit fixed by Param
    def get_param(self, p: Param) -> float:
        if p == Param.EXPOSURE:
            return float(self._sdk.get_control(self._index, ASI_EXPOSURE)[0])
        if p == Param.GAIN:
            return float(self._sdk.get_control(self._index, ASI_GAIN)[0])
        if p == Param.OFFSET:
            return float(self._sdk.get_control(self._index, ASI_OFFSET)[0])
        if p == Param.READOUT:
            return float(self._sdk.get_control(self._index, ASI_BANDWIDTH)[0])
        if p == Param.TEMPERATURE:
            return (float(self._sdk.get_control(self._index, ASI_TEMPERATURE)[0])
                    / 10.0)
        if p == Param.BIT_DEPTH:
            return float(self._bit_depth)
        if p == Param.BINNING:
            return 1.0
        raise _unsupported(p, self._camera_id)

    # @args: p - property; value - in the unit fixed by Param
    # @return: none
    def set_param(self, p: Param, value: float) -> None:
        if p == Param.EXPOSURE:
            self._sdk.set_control(self._index, ASI_EXPOSURE, int(value))
        elif p == Param.GAIN:
            self._sdk.set_control(self._index, ASI_GAIN, int(value))
        elif p == Param.OFFSET:
            self._sdk.set_control(self._index, ASI_OFFSET, int(value))
        elif p == Param.READOUT:
            self._sdk.set_control(self._index, ASI_BANDWIDTH, int(value))
        else:
            raise _unsupported(p, self._camera_id)

    # @args: p - property
    # @return: the interval the SDK accepts
    def param_range(self, p: Param) -> ParamRange:
        control = {
            Param.EXPOSURE: ASI_EXPOSURE,
            Param.GAIN: ASI_GAIN,
            Param.OFFSET: ASI_OFFSET,
            Param.READOUT: ASI_BANDWIDTH,
        }.get(p)
        if control is None:
            raise _unsupported(p, self._camera_id)
        try:
            return self._sdk.control_range(self._index, control)
        except DeviceError:
            raise _unsupported(p, self._camera_id)

    # @return: frames the ASI SDK reports as lost since start_stream()
    def dropped_frames(self) -> int:
        if not self._open:
            return 0
        return self._sdk.dropped(self._index)

    # @args: on_frame - called on the driver thread with each owned frame
    # @return: none
    def start_stream(self, on_frame) -> None:
        if not self._open:
            raise DeviceError("camera is not open", code="not_open",
                              device_id=self._camera_id)
        if self._thread is not None and self._thread.is_alive():
            raise DeviceError("stream already running", code="already_streaming",
                              device_id=self._camera_id)
        self._sdk.start_video(self._index)
        self._on_frame = on_frame
        self._sequence = 0
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="asi-capture", daemon=True,
        )
        self._thread.start()

    # @args: none. Stops the stream and joins the driver thread
    # @return: none
    def stop_stream(self) -> None:
        self._stop.set()
        if self._open:
            try:
                self._sdk.stop_video(self._index)
            except Exception:  # noqa: BLE001 - stopping a dead camera is harmless
                pass
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._on_frame = None

    # @args: none
    # @return: none. Pulls owned frames and calls the user callback
    def _run(self) -> None:
        _, _, width, height = self._roi
        dtype = np.uint16 if self._bit_depth >= 16 else np.uint8
        nbytes = width * height * dtype().itemsize
        if self._buffer is None or self._buffer_nbytes != nbytes:
            self._buffer = ctypes.create_string_buffer(nbytes)
            self._buffer_nbytes = nbytes
        while not self._stop.is_set():
            try:
                got = self._sdk.read(self._index, self._buffer, nbytes)
            except Exception:  # noqa: BLE001 - a dead camera ends the stream
                break
            if not got:
                continue
            sequence = self._sequence
            self._sequence += 1
            array = np.frombuffer(self._buffer, dtype=dtype).reshape(
                height, width,
            ).copy()
            callback = self._on_frame
            if callback is not None:
                callback(SdkFrame(array, self._roi, sequence,
                                  time.monotonic()))


# @args: sdk - AsiSdk; index - camera index; raw - ASI_CAMERA_INFO
# @return: CameraInfo with the ASI constraints
def _info(sdk: AsiSdk, index: int, raw) -> CameraInfo:
    name = raw.Name
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    return CameraInfo(
        camera_id=f"{NAME}:{index}",
        vendor=VENDOR,
        model=(name or f"ASI camera {index}").strip(),
        backend=NAME,
        caps=CameraCaps(
            roi=RoiConstraints(
                max_width=int(raw.MaxWidth), max_height=int(raw.MaxHeight),
                min_width=MIN_SIZE, min_height=MIN_SIZE,
                width_multiple=WIDTH_MULTIPLE,
                height_multiple=HEIGHT_MULTIPLE,
                offset_multiple=1,
            ),
            is_color=bool(raw.IsColorCam),
            bit_depths=(16,) if int(raw.BitDepth) >= 16 else (8,),
            binnings=(1,),
            has_cooler=bool(raw.IsCoolerCam),
            reports_temperature=bool(raw.IsCoolerCam),
        ),
    )


# @args: camera_id - "native/asi:<index>"
# @return: the integer index the SDK uses
def _index_of(camera_id: str) -> int:
    try:
        return int(camera_id.rsplit(":", 1)[1])
    except (IndexError, ValueError) as exc:
        raise DeviceError(f"bad ASI camera id {camera_id!r}",
                          code="unknown_camera",
                          device_id=camera_id) from exc


# @args: param - the unsupported property; camera_id - which camera
# @return: the DeviceError to raise
def _unsupported(param: Param, camera_id: str) -> DeviceError:
    return DeviceError(f"ASI does not expose {param.value}",
                       code="not_supported", device_id=camera_id)


# @args: loader - injectable library loader, for the tests
# @return: the backend descriptor the DeviceManager probes
def backend(loader=None):
    from solarscribe.devices.native.backend import NativeCameraBackend

    kwargs = {} if loader is None else {"loader": loader}
    return NativeCameraBackend(NAME, VENDOR, LIBRARIES,
                               driver=AsiCamera, **kwargs)
