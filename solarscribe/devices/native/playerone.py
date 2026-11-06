############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native playerone module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Player One native driver (libPlayerOneCamera, ADR-002).
#
# The SDK is index based (cameraID int), so no opaque handle is returned. The
# risk is the same as in the ASI backend: POACameraProperties is a 300+ byte
# struct the SDK fills in place, and a wrong layout is a heap overflow. The
# layout below is transcribed field by field from PlayerOneCamera.h (SDK 3.3,
# `reserved[248]`), including the arrays the SDK memcpy's.
#
# The stream is pull mode: POAStartExposure starts continuous exposure and
# POAGetImageData blocks up to the timeout for the next frame. POA_RAW16 is the
# SER contract; a colour camera still delivers its Bayer plane, so the driver
# reports is_color and the caller knows it must not debayer on capture.
#
# Hardware validation: a mocked library covers the signatures and the command
# sequence. No Player One camera was attached to the validation machine, so the
# hardware test enumerates and skips when none is present; the report must say
# the path is unverified on hardware.

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

__all__ = [
    "LIBRARIES", "PlayerOneCamera", "PlayerOneSdk", "SIGNATURES", "backend",
]

NAME = "native/playerone"
VENDOR = "Player One"
LIBRARIES = (
    "libPlayerOneCamera.so",
    "libPlayerOneCamera.dylib",
    "PlayerOneCamera.dll",
)

POA_SUCCESS = 0

# POAConfig ids used by the driver.
POA_EXPOSURE = 0
POA_GAIN = 1
POA_TEMPERATURE = 3
POA_OFFSET = 7
POA_USB_BANDWIDTH = 28

# POAImgFormat. RAW16 is what the SER writer needs.
POA_RAW16 = 1

# POAValueType, for reading the config attributes union correctly.
POA_VALUE_INT = 0
POA_VALUE_FLOAT = 1
POA_VALUE_BOOL = 2

# ROI: Player One takes an arbitrary start position and size inside the sensor.
WIDTH_MULTIPLE = 1
HEIGHT_MULTIPLE = 1
MIN_SIZE = 1

_MAX_BINS = 8
_MAX_FORMATS = 8


class _PoaCameraProperties(ctypes.Structure):
    # Field order and sizes follow PlayerOneCamera.h; a short or reordered
    # layout corrupts the heap the moment POAGetCameraProperties fills it.
    _fields_ = [
        ("cameraModelName", ctypes.c_char * 256),
        ("userCustomID", ctypes.c_char * 16),
        ("cameraID", ctypes.c_int),
        ("maxWidth", ctypes.c_int),
        ("maxHeight", ctypes.c_int),
        ("bitDepth", ctypes.c_int),
        ("isColorCamera", ctypes.c_int),
        ("isHasST4Port", ctypes.c_int),
        ("isHasCooler", ctypes.c_int),
        ("isUSB3Speed", ctypes.c_int),
        ("bayerPattern", ctypes.c_int),
        ("pixelSize", ctypes.c_double),
        ("SN", ctypes.c_char * 64),
        ("sensorModelName", ctypes.c_char * 32),
        ("localPath", ctypes.c_char * 256),
        ("bins", ctypes.c_int * _MAX_BINS),
        ("imgFormats", ctypes.c_int * _MAX_FORMATS),
        ("isSupportHardBin", ctypes.c_int),
        ("pID", ctypes.c_int),
        ("reserved", ctypes.c_char * 248),
    ]


class _PoaConfigValue(ctypes.Union):
    _fields_ = [
        ("intValue", ctypes.c_long),
        ("floatValue", ctypes.c_double),
        ("boolValue", ctypes.c_int),
    ]


class _PoaConfigAttributes(ctypes.Structure):
    _fields_ = [
        ("isSupportAuto", ctypes.c_int),
        ("isWritable", ctypes.c_int),
        ("isReadable", ctypes.c_int),
        ("configID", ctypes.c_int),
        ("valueType", ctypes.c_int),
        ("maxValue", _PoaConfigValue),
        ("minValue", _PoaConfigValue),
        ("defaultValue", _PoaConfigValue),
        ("szConfName", ctypes.c_char * 64),
        ("szDescription", ctypes.c_char * 128),
        ("reserved", ctypes.c_char * 64),
    ]


SIGNATURES = {
    "POAGetCameraCount": (ctypes.c_int, []),
    "POAGetCameraProperties": (
        ctypes.c_int, [ctypes.c_int, ctypes.POINTER(_PoaCameraProperties)],
    ),
    "POAOpenCamera": (ctypes.c_int, [ctypes.c_int]),
    "POAInitCamera": (ctypes.c_int, [ctypes.c_int]),
    "POACloseCamera": (ctypes.c_int, [ctypes.c_int]),
    "POASetImageSize": (ctypes.c_int, [ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int]),
    "POASetImageStartPos": (ctypes.c_int, [ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int]),
    "POASetImageFormat": (ctypes.c_int, [ctypes.c_int, ctypes.c_int]),
    "POASetImageBin": (ctypes.c_int, [ctypes.c_int, ctypes.c_int]),
    "POAGetImageBin": (
        ctypes.c_int, [ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
    ),
    "POAStartExposure": (ctypes.c_int, [ctypes.c_int, ctypes.c_int]),
    "POAStopExposure": (ctypes.c_int, [ctypes.c_int]),
    "POAGetImageData": (
        ctypes.c_int,
        [ctypes.c_int, ctypes.POINTER(ctypes.c_uint8), ctypes.c_long,
         ctypes.c_int],
    ),
    "POAGetConfigAttributesByConfigID": (
        ctypes.c_int,
        [ctypes.c_int, ctypes.c_int,
         ctypes.POINTER(_PoaConfigAttributes)],
    ),
    "POASetConfig": (
        ctypes.c_int,
        [ctypes.c_int, ctypes.c_int, _PoaConfigValue, ctypes.c_int],
    ),
    "POAGetConfig": (
        ctypes.c_int,
        [ctypes.c_int, ctypes.c_int, ctypes.POINTER(_PoaConfigValue),
         ctypes.POINTER(ctypes.c_int)],
    ),
    # Optional in old SDK builds; the table entry is skipped when the symbol
    # is absent and dropped_frames() then reports 0.
    "POAGetDroppedImagesCount": (
        ctypes.c_int, [ctypes.c_int, ctypes.POINTER(ctypes.c_int)],
    ),
}


class PlayerOneSdk:
    # Thin ctypes wrapper for the Player One SDK.

    # @args: library - loaded CDLL (or a test double)
    def __init__(self, library) -> None:
        self._lib = library
        apply_signatures(library, SIGNATURES)

    # @return: the cameras the SDK reports, read without opening them
    def camera_properties(self) -> list[_PoaCameraProperties]:
        count = int(self._lib.POAGetCameraCount())
        props = []
        for index in range(max(0, count)):
            info = _PoaCameraProperties()
            status = self._lib.POAGetCameraProperties(
                index, ctypes.byref(info),
            )
            if status != POA_SUCCESS:
                continue
            props.append(info)
        return props

    # @args: camera_id - integer cameraID
    # @return: none
    def open(self, camera_id: int) -> None:
        self._check("POAOpenCamera", self._lib.POAOpenCamera(camera_id))
        try:
            self._check("POAInitCamera", self._lib.POAInitCamera(camera_id))
        except DeviceError:
            self._lib.POACloseCamera(camera_id)
            raise

    # @args: camera_id - integer cameraID
    # @return: none
    def close(self, camera_id: int) -> None:
        self._lib.POACloseCamera(camera_id)

    # @args: camera_id, roi - SENSOR pixels
    # @return: none
    def set_roi(self, camera_id: int, roi: ROI) -> None:
        x, y, width, height = roi
        self._check(
            "POASetImageSize",
            self._lib.POASetImageSize(camera_id, width, height),
        )
        self._check(
            "POASetImageStartPos",
            self._lib.POASetImageStartPos(camera_id, x, y),
        )

    # @args: camera_id - integer cameraID
    # @return: none. Sets the 16-bit raw format
    def set_raw16(self, camera_id: int) -> None:
        self._check(
            "POASetImageFormat",
            self._lib.POASetImageFormat(camera_id, POA_RAW16),
        )

    # @args: camera_id, config - POAConfig id; value - SDK units
    # @return: none
    def set_config(self, camera_id: int, config: int, value: int) -> None:
        conf_value = _PoaConfigValue()
        conf_value.intValue = int(value)
        self._check(
            f"POASetConfig({config})",
            self._lib.POASetConfig(camera_id, config, conf_value, 0),
        )

    # @args: camera_id, config - POAConfig id
    # @return: (value, is_auto) in SDK units
    def get_config(self, camera_id: int, config: int) -> tuple[int, bool]:
        conf_value = _PoaConfigValue()
        is_auto = ctypes.c_int(0)
        status = self._lib.POAGetConfig(
            camera_id, config, ctypes.byref(conf_value),
            ctypes.byref(is_auto),
        )
        self._check(f"POAGetConfig({config})", status)
        return int(conf_value.intValue), bool(is_auto.value)

    # @args: camera_id, config - a POAConfig whose valueType is VAL_FLOAT
    # @return: the float value in SDK units (temperature is degrees C)
    def get_config_float(self, camera_id: int, config: int) -> float:
        conf_value = _PoaConfigValue()
        is_auto = ctypes.c_int(0)
        status = self._lib.POAGetConfig(
            camera_id, config, ctypes.byref(conf_value),
            ctypes.byref(is_auto),
        )
        self._check(f"POAGetConfig({config})", status)
        return float(conf_value.floatValue)

    # @args: camera_id, config - POAConfig id
    # @return: the interval the SDK accepts
    def config_range(self, camera_id: int, config: int) -> ParamRange:
        attributes = _PoaConfigAttributes()
        status = self._lib.POAGetConfigAttributesByConfigID(
            camera_id, config, ctypes.byref(attributes),
        )
        self._check(f"POAGetConfigAttributesByConfigID({config})", status)
        minimum = _conf_number(attributes.minValue, attributes.valueType)
        maximum = _conf_number(attributes.maxValue, attributes.valueType)
        return ParamRange(minimum, maximum, 1.0)

    # @args: camera_id - integer cameraID
    # @return: the SDK drop counter, or 0 when this build lacks it
    def dropped(self, camera_id: int) -> int:
        function = getattr(self._lib, "POAGetDroppedImagesCount", None)
        if function is None:
            return 0
        value = ctypes.c_int(0)
        status = function(camera_id, ctypes.byref(value))
        if status != POA_SUCCESS:
            return 0
        return int(value.value)

    # @args: camera_id - integer cameraID; single - one frame or continuous
    # @return: none
    def start_exposure(self, camera_id: int, single: bool = False) -> None:
        self._check(
            "POAStartExposure",
            self._lib.POAStartExposure(camera_id, int(bool(single))),
        )

    # @args: camera_id - integer cameraID
    # @return: none
    def stop_exposure(self, camera_id: int) -> None:
        try:
            self._lib.POAStopExposure(camera_id)
        except Exception:  # noqa: BLE001 - stopping a dead camera is harmless
            pass

    # @args: camera_id, buffer, nbytes - destination and size; timeout_ms
    # @return: True when a frame was copied, False on timeout
    def read(self, camera_id: int, buffer, nbytes: int,
             timeout_ms: int = 200) -> bool:
        status = self._lib.POAGetImageData(
            camera_id, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint8)),
            nbytes, timeout_ms,
        )
        # POA_ERROR_TIMEOUT is 9, not 17: 17 is OPERATION_FAILED (a disconnect)
        # and must surface, never be mistaken for an idle poll.
        if status == 9:
            return False
        self._check("POAGetImageData", status)
        return True

    # @args: name - SDK call; status - its return code
    # @return: none
    def _check(self, name: str, status: int) -> None:
        if status != POA_SUCCESS:
            raise DeviceError(f"{name} failed with Player One code {status}",
                              code="sdk_error")


class PlayerOneCamera:
    # Camera contract over the Player One SDK (ADR-002, ADR-012).

    # @args: camera_id - "native/playerone:<cameraID>"
    #        library - loaded CDLL; ignored when sdk is given
    #        sdk - injectable wrapper, for the unit tests
    def __init__(self, camera_id: str, library=None, sdk=None) -> None:
        self._camera_id = camera_id
        self._id = _id_of(camera_id)
        self._sdk = sdk if sdk is not None else PlayerOneSdk(library)
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
        sdk = PlayerOneSdk(library)
        return [_info(prop) for prop in sdk.camera_properties()]

    # @args: none. Raises DeviceError when the SDK refuses the camera
    # @return: none
    def open(self) -> None:
        try:
            self._sdk.open(self._id)
            props = [prop for prop in self._sdk.camera_properties()
                     if int(prop.cameraID) == self._id]
            if not props:
                raise DeviceError("Player One camera disappeared during open",
                                  code="device_lost",
                                  device_id=self._camera_id)
            prop = props[0]
            self._width = int(prop.maxWidth)
            self._height = int(prop.maxHeight)
            self._bit_depth = 16
            self._is_color = bool(prop.isColorCamera)
            self._has_cooler = bool(prop.isHasCooler)
            self._sdk.set_raw16(self._id)
            self._sdk.set_roi(self._id, (0, 0, self._width, self._height))
            self._roi = (0, 0, self._width, self._height)
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
            self._sdk.close(self._id)
        except Exception:  # noqa: BLE001 - the camera may never have opened
            pass

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        self.stop_stream()
        if self._open:
            self._sdk.close(self._id)
        self._open = False

    # @return: whether the camera is open
    def is_open(self) -> bool:
        return self._open

    # @return: identity and sensor limits
    def info(self) -> CameraInfo:
        return CameraInfo(
            camera_id=self._camera_id,
            vendor=VENDOR,
            model=f"Player One camera {self._id}",
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
        if (
            x < 0 or y < 0 or width < MIN_SIZE or height < MIN_SIZE
            or x + width > self._width or y + height > self._height
        ):
            raise DeviceError(
                f"ROI {roi!r} rejected by the Player One constraints",
                code="roi_rejected", device_id=self._camera_id,
            )
        self._sdk.set_roi(self._id, roi)
        self._roi = roi
        self._buffer = None

    # @return: the biggest ROI
    def effective_area(self) -> ROI:
        return (0, 0, self._width, self._height)

    # @args: p - property to read
    # @return: its value in the unit fixed by Param
    def get_param(self, p: Param) -> float:
        if p == Param.BIT_DEPTH:
            return float(self._bit_depth)
        if p == Param.BINNING:
            return 1.0
        if p == Param.TEMPERATURE:
            # POA_TEMPERATURE is VAL_FLOAT and already in degrees C; reading
            # the int field of the union would return garbage.
            return self._sdk.get_config_float(self._id, POA_TEMPERATURE)
        control = _config_of(p)
        if control is None:
            raise _unsupported(p, self._camera_id)
        return float(self._sdk.get_config(self._id, control)[0])

    # @args: p - property; value - in the unit fixed by Param
    # @return: none
    def set_param(self, p: Param, value: float) -> None:
        if p == Param.TEMPERATURE:
            raise _unsupported(p, self._camera_id)
        control = _config_of(p)
        if control is None:
            raise _unsupported(p, self._camera_id)
        self._sdk.set_config(self._id, control, int(value))

    # @args: p - property
    # @return: the interval the SDK accepts
    def param_range(self, p: Param) -> ParamRange:
        if p == Param.BIT_DEPTH:
            return ParamRange(16.0, 16.0, 0.0)
        if p == Param.BINNING:
            return ParamRange(1.0, 1.0, 0.0)
        control = _config_of(p)
        if control is None:
            raise _unsupported(p, self._camera_id)
        return self._sdk.config_range(self._id, control)

    # @return: frames the SDK reports as lost since start_stream()
    def dropped_frames(self) -> int:
        if not self._open:
            return 0
        return self._sdk.dropped(self._id)

    # @args: on_frame - called on the driver thread with each owned frame
    # @return: none
    def start_stream(self, on_frame) -> None:
        if not self._open:
            raise DeviceError("camera is not open", code="not_open",
                              device_id=self._camera_id)
        if self._thread is not None and self._thread.is_alive():
            raise DeviceError("stream already running", code="already_streaming",
                              device_id=self._camera_id)
        self._sdk.start_exposure(self._id, single=False)
        self._on_frame = on_frame
        self._sequence = 0
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="playerone-capture", daemon=True,
        )
        self._thread.start()

    # @args: none. Stops the stream and joins the driver thread
    # @return: none
    def stop_stream(self) -> None:
        self._stop.set()
        self._sdk.stop_exposure(self._id)
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._on_frame = None

    # @args: none
    # @return: none. Pulls owned frames and calls the user callback
    def _run(self) -> None:
        _, _, width, height = self._roi
        nbytes = width * height * 2
        if self._buffer is None or self._buffer_nbytes != nbytes:
            self._buffer = ctypes.create_string_buffer(nbytes)
            self._buffer_nbytes = nbytes
        while not self._stop.is_set():
            try:
                got = self._sdk.read(self._id, self._buffer, nbytes)
            except Exception:  # noqa: BLE001 - a dead camera ends the stream
                break
            if not got:
                continue
            sequence = self._sequence
            self._sequence += 1
            array = np.frombuffer(self._buffer, dtype=np.uint16).reshape(
                height, width,
            ).copy()
            callback = self._on_frame
            if callback is not None:
                callback(SdkFrame(array, self._roi, sequence,
                                  time.monotonic()))


# @args: prop - POACameraProperties filled by the SDK
# @return: CameraInfo with the Player One constraints
def _info(prop) -> CameraInfo:
    name = prop.cameraModelName
    if isinstance(name, bytes):
        name = name.decode("utf-8", "replace")
    formats = [int(value) for value in prop.imgFormats[:4]]
    bit_depths = (16,) if POA_RAW16 in formats else (8,)
    return CameraInfo(
        camera_id=f"{NAME}:{int(prop.cameraID)}",
        vendor=VENDOR,
        model=(name or f"Player One {int(prop.cameraID)}").strip(),
        backend=NAME,
        caps=CameraCaps(
            roi=RoiConstraints(
                max_width=int(prop.maxWidth),
                max_height=int(prop.maxHeight),
                min_width=MIN_SIZE, min_height=MIN_SIZE,
                width_multiple=WIDTH_MULTIPLE,
                height_multiple=HEIGHT_MULTIPLE,
                offset_multiple=1,
            ),
            is_color=bool(prop.isColorCamera),
            bit_depths=bit_depths,
            binnings=(1,),
            has_cooler=bool(prop.isHasCooler),
            reports_temperature=bool(prop.isHasCooler),
        ),
    )


# @args: camera_id - "native/playerone:<cameraID>"
# @return: the integer cameraID the SDK uses
def _id_of(camera_id: str) -> int:
    try:
        return int(camera_id.rsplit(":", 1)[1])
    except (IndexError, ValueError) as exc:
        raise DeviceError(f"bad Player One camera id {camera_id!r}",
                          code="unknown_camera",
                          device_id=camera_id) from exc


# @args: p - device property
# @return: the POAConfig id, or None when the driver handles it itself
def _config_of(p: Param):
    return {
        Param.EXPOSURE: POA_EXPOSURE,
        Param.GAIN: POA_GAIN,
        Param.OFFSET: POA_OFFSET,
        Param.READOUT: POA_USB_BANDWIDTH,
        Param.TEMPERATURE: POA_TEMPERATURE,
    }.get(p)


# @args: value - POAConfigValue; value_type - POAValueType
# @return: the number in the union field the type says
def _conf_number(value, value_type: int) -> float:
    if value_type == POA_VALUE_FLOAT:
        return float(value.floatValue)
    if value_type == POA_VALUE_BOOL:
        return float(value.boolValue)
    return float(value.intValue)


# @args: param - the unsupported property; camera_id - which camera
# @return: the DeviceError to raise
def _unsupported(param: Param, camera_id: str) -> DeviceError:
    return DeviceError(f"Player One does not expose {param.value}",
                       code="not_supported", device_id=camera_id)


# @args: loader - injectable library loader, for the tests
# @return: the backend descriptor the DeviceManager probes
def backend(loader=None):
    from solarscribe.devices.native.backend import NativeCameraBackend

    kwargs = {} if loader is None else {"loader": loader}
    return NativeCameraBackend(NAME, VENDOR, LIBRARIES,
                               driver=PlayerOneCamera, **kwargs)
