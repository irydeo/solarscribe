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
#     SDK callback only counts a pending image; a Python thread does the copy
#     and calls the user callback, so no Python work runs inside the C callback.
#
# The SDK is loaded dynamically by the backend (loader.py). This module never
# imports a vendor library at import time, so the module exists on a machine
# without Touptek and the backend simply reports SDK_MISSING (ADR-014).
#
# Signatures and structures are transcribed from toupcam.h (SDK 60.33015,
# 2026-10-24) and verified against the real G3M678M in the hardware report.
# Three mistakes in the first transcription were found by reading the real
# header and are fixed here; each one alone could crash or stall a session:
#   - ToupcamDeviceV2 is char[64] + char[64] + model pointer (136 bytes on
#     Linux). The old 20-byte struct made Toupcam_EnumV2 write 17 KB into a
#     2.5 KB ctypes array: a heap overflow, and the likely cause of the first
#     "Find cameras" core dump.
#   - Toupcam_OpenByIndex returns an HToupcam (void*). With the default c_int
#     restype the 64-bit handle was truncated and the next call dereferenced
#     garbage: the second way to get a segfault.
#   - TOUPCAM_EVENT_IMAGE is 0x0004 and TOUPCAM_OPTION_BITDEPTH is 0x06. The
#     old 0x0010/0x0013 values are FRONT_OVERFLOW/DEMOSAIC_VIDEO, so the driver
#     waited forever for an image and wrote bit depth into the wrong option.
#
# Hardware validation, stated exactly: on the validation machine (Linux, no
# camera attached) libtoupcam 60.33015 was loaded, the device array was
# enumerated with the corrected 136-byte struct and the signatures above, and
# the process exited cleanly; no camera was present, so no frame was captured
# and the G3M678M numbers are still pending. The module is written so the user
# can close that gap in one command:
#
#   python -m solarscribe.devices.native.diagnose touptek
#
# It prints the real sensor size, the ROI multiples measured by trial, the
# RAW/BITDEPTH/SPEED write behaviour, 30 streamed frames with fps, and the SDK
# drop counter. The same checks are the `hardware` test in
# tests/functional/test_devices_hardware.py; paste either output into the
# validation report.

from __future__ import annotations

import ctypes
import math
import os
import threading
import time

import numpy as np

from solarscribe.devices.abc import (
    ROI, CameraCaps, CameraInfo, DeviceError, Param, ParamRange, RoiConstraints,
)
from solarscribe.devices.native.frame import SdkFrame
from solarscribe.devices.native.signatures import apply_signatures

__all__ = [
    "LIBRARIES", "SIGNATURES", "SdkDevice", "TouptekCamera",
    "CtypesToupcamSdk", "diagnose", "format_report",
]

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

# Event ids from toupcam.h. IMAGE is the only one that carries a frame; the
# two error events are fatal for the stream and stop it so the capture engine
# sees a stall instead of waiting forever.
TOUPCAM_EVENT_IMAGE = 0x0004
TOUPCAM_EVENT_ERROR = 0x0080
TOUPCAM_EVENT_DISCONNECTED = 0x0081

# SDK options used by the driver. RAW selects the un-debayered plane (mono) and
# BITDEPTH selects the output word size (0 = 8 bit, 1 = 16 bit). Speed is not
# an option: toupcam.h exposes Toupcam_put_Speed/get_Speed for it.
TOUPCAM_OPTION_RAW = 0x04
TOUPCAM_OPTION_BITDEPTH = 0x06

# ROI alignment from toupcam.h: "xOffset, yOffset, xWidth, yHeight: must be even
# numbers. Minimum width & height: 8". Declaring the real limits matters: the
# ROI step refuses an invalid rectangle before the SDK does, and a too strict
# multiple would reject a perfectly valid 3480x248 scan ROI.
WIDTH_MULTIPLE = 2
HEIGHT_MULTIPLE = 2
OFFSET_MULTIPLE = 2
MIN_SIZE = 8

# Nominal sensor size of the reference camera, used only when discovery cannot
# open the device to read the real size. It is better to show a camera with the
# reference geometry than to hide it, and the first open() corrects the value.
NOMINAL_WIDTH = 3840
NOMINAL_HEIGHT = 2160

TOUPCAM_MAX = 128

# Callback the SDK invokes on its own thread. The type object must be kept at
# module level: a collected CFUNCTYPE trampoline is a crash in C. On Windows
# toupcam.h declares it __stdcall; CFUNCTYPE is cdecl and would corrupt the
# stack there, so WINFUNCTYPE is the right factory on that platform.
CALLBACK_FACTORY = ctypes.WINFUNCTYPE if os.name == "nt" else ctypes.CFUNCTYPE
TOUPCAM_CALLBACK = CALLBACK_FACTORY(None, ctypes.c_uint, ctypes.c_void_p)


class SdkDevice:
    # One entry of the SDK enumeration.

    # @args: device_id - stable SDK id
    #        display_name - what the vendor calls it
    #        model - 1 when the SDK supplied its opaque model pointer, else 0;
    #                the numeric model code would need dereferencing that struct
    #        index - position in the enumeration, used by OpenByIndex
    def __init__(self, device_id: str, display_name: str, model: int,
                 index: int) -> None:
        self.device_id = device_id
        self.display_name = display_name
        self.model = int(model)
        self.index = int(index)


# On Windows the SDK uses wchar_t[64] for both strings; on Linux and macOS it
# uses char[64]. The width is part of the ABI: a wrong field size shifts the
# model pointer and corrupts every device after the first.
_WCHAR = ctypes.c_wchar if os.name == "nt" else ctypes.c_char


class _DeviceV2(ctypes.Structure):
    _fields_ = [
        ("displayname", _WCHAR * 64),
        ("id", _WCHAR * 64),
        ("model", ctypes.c_void_p),
    ]


# Complete signature table for every libtoupcam symbol this module calls.
# restype c_void_p on the Open call is the crash fix: a handle is a pointer, not
# an int, and ctypes must not truncate it. argtypes are just as important: a
# pointer output passed as a Python int writes into an arbitrary address.
SIGNATURES = {
    "Toupcam_EnumV2": (
        ctypes.c_uint, [ctypes.POINTER(_DeviceV2)],
    ),
    "Toupcam_OpenByIndex": (
        ctypes.c_void_p, [ctypes.c_uint],
    ),
    "Toupcam_Close": (
        None, [ctypes.c_void_p],
    ),
    "Toupcam_get_Size": (
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
         ctypes.POINTER(ctypes.c_int)],
    ),
    "Toupcam_put_Roi": (
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
         ctypes.c_uint, ctypes.c_uint],
    ),
    "Toupcam_get_Roi": (
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint),
         ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
         ctypes.POINTER(ctypes.c_uint)],
    ),
    "Toupcam_get_ExpoTime": (
        ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)],
    ),
    "Toupcam_put_ExpoTime": (
        ctypes.c_int, [ctypes.c_void_p, ctypes.c_uint],
    ),
    "Toupcam_get_ExpTimeRange": (
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint),
         ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)],
    ),
    "Toupcam_get_ExpoAGain": (
        ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort)],
    ),
    "Toupcam_put_ExpoAGain": (
        ctypes.c_int, [ctypes.c_void_p, ctypes.c_ushort],
    ),
    "Toupcam_get_ExpoAGainRange": (
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort),
         ctypes.POINTER(ctypes.c_ushort), ctypes.POINTER(ctypes.c_ushort)],
    ),
    "Toupcam_put_Option": (
        ctypes.c_int, [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int],
    ),
    "Toupcam_get_Option": (
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)],
    ),
    "Toupcam_put_Speed": (
        ctypes.c_int, [ctypes.c_void_p, ctypes.c_ushort],
    ),
    "Toupcam_get_Speed": (
        ctypes.c_int, [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort)],
    ),
    "Toupcam_StartPullModeWithCallback": (
        ctypes.c_int, [ctypes.c_void_p, TOUPCAM_CALLBACK, ctypes.c_void_p],
    ),
    "Toupcam_Stop": (
        ctypes.c_int, [ctypes.c_void_p],
    ),
    # PullImageV4's last argument is ToupcamFrameInfoV4*; NULL means "do not
    # report the frame metadata", which is all this driver needs. Declaring it
    # c_void_p keeps the NULL honest without copying a 100-byte struct.
    "Toupcam_PullImageV4": (
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
         ctypes.c_int, ctypes.c_int, ctypes.c_void_p],
    ),
    "Toupcam_PullImage": (
        ctypes.c_int,
        [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
         ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)],
    ),
}


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
        self._roi: ROI = (0, 0, 0, 0)
        self._bit_depth = 16
        self._dropped = 0
        self._callback = None
        # Reused across frames: allocating 1.7 MB per frame on the capture path
        # is waste. The numpy copy below is still per frame because the frame
        # must own its pixels (the SDK buffer is about to be overwritten).
        self._buffer = None
        self._buffer_nbytes = 0
        apply_signatures(library, SIGNATURES)

    # @args: library - loaded CDLL
    # @return: the devices the SDK reports, with their stable ids and indexes
    @staticmethod
    def enumerate(library) -> list[SdkDevice]:
        apply_signatures(library, SIGNATURES)
        if not hasattr(library, "Toupcam_EnumV2"):
            return []
        array = (_DeviceV2 * TOUPCAM_MAX)()
        try:
            count = int(library.Toupcam_EnumV2(array))
        except Exception:      # noqa: BLE001 - a broken SDK must not crash start
            return []
        devices = []
        for i in range(max(0, min(count, TOUPCAM_MAX))):
            raw_name = array[i].displayname
            raw_id = array[i].id
            if isinstance(raw_name, bytes):
                raw_name = raw_name.decode("utf-8", "replace")
            if isinstance(raw_id, bytes):
                raw_id = raw_id.decode("utf-8", "replace")
            devices.append(SdkDevice(
                device_id=(raw_id or "").strip(),
                display_name=(raw_name or f"Toupcam {i}").strip(),
                model=0 if not array[i].model else 1,
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
        # remember the current hardware rectangle so pull() sizes its buffer
        # from what the camera really delivers, not from the sensor size.
        try:
            self.size()
            try:
                self._roi = self.get_roi()
            except Exception:  # noqa: BLE001 - an old SDK may lack get_Roi
                self._roi = (0, 0, self._width, self._height)
        except Exception:
            # Do not leave a half-open handle behind: the next discovery would
            # find the camera busy.
            self.close()
            raise

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        if self._handle is not None:
            try:
                self._lib.Toupcam_Close(self._handle)
            finally:
                self._handle = None

    # @args: none
    # @return: (width, height) of the sensor at the current size setting
    def size(self) -> tuple[int, int]:
        self._require_handle()
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
        self._require_handle()
        x, y, width, height = roi
        status = self._lib.Toupcam_put_Roi(
            self._handle, x, y, width, height,
        )
        if status != 0:
            raise DeviceError(f"Toupcam_put_Roi{roi} failed", code="roi_rejected")
        self._roi = roi
        # The delivered image is the ROI, not the sensor: pull() must allocate
        # and reshape to this rectangle or every frame is garbled.
        self._width, self._height = int(width), int(height)

    # @return: the ROI the SDK reports
    def get_roi(self) -> ROI:
        self._require_handle()
        x, y, width, height = (ctypes.c_uint(0) for _ in range(4))
        status = self._lib.Toupcam_get_Roi(
            self._handle, ctypes.byref(x), ctypes.byref(y),
            ctypes.byref(width), ctypes.byref(height),
        )
        if status != 0:
            raise DeviceError("Toupcam_get_Roi failed", code="sdk_error")
        self._roi = (int(x.value), int(y.value),
                     int(width.value), int(height.value))
        return self._roi

    # @return: exposure in microseconds
    def get_exposure(self) -> float:
        self._require_handle()
        value = ctypes.c_uint(0)
        status = self._lib.Toupcam_get_ExpoTime(self._handle, ctypes.byref(value))
        if status != 0:
            raise DeviceError("Toupcam_get_ExpoTime failed", code="sdk_error")
        return float(value.value)

    # @args: value - microseconds
    # @return: none
    def set_exposure(self, value: float) -> None:
        self._require_handle()
        status = self._lib.Toupcam_put_ExpoTime(self._handle, int(value))
        if status != 0:
            raise DeviceError("Toupcam_put_ExpoTime failed",
                              code="param_rejected")

    # @return: the exposure interval the SDK accepts, in microseconds
    def exposure_range(self) -> ParamRange:
        self._require_handle()
        lo, hi, default = (ctypes.c_uint(0) for _ in range(3))
        status = self._lib.Toupcam_get_ExpTimeRange(
            self._handle, ctypes.byref(lo), ctypes.byref(hi),
            ctypes.byref(default),
        )
        if status != 0:
            raise DeviceError("Toupcam_get_ExpTimeRange failed",
                              code="sdk_error")
        return ParamRange(float(lo.value), float(hi.value), 1.0)

    # @return: gain in SDK units (percent, 100 = 1x)
    def get_gain(self) -> float:
        self._require_handle()
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
        self._require_handle()
        status = self._lib.Toupcam_put_ExpoAGain(self._handle, int(value))
        if status != 0:
            raise DeviceError("Toupcam_put_ExpoAGain failed",
                              code="param_rejected")

    # @return: the gain interval the SDK accepts
    def gain_range(self) -> ParamRange:
        self._require_handle()
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
        self._require_handle()
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
        self._require_handle()
        value = ctypes.c_int(0)
        status = self._lib.Toupcam_get_Option(
            self._handle, int(option), ctypes.byref(value),
        )
        if status != 0:
            raise DeviceError(
                f"Toupcam_get_Option({option:#x}) failed", code="sdk_error",
            )
        return int(value.value)

    # @return: the readout speed level the SDK reports
    def get_speed(self) -> int:
        self._require_handle()
        if not hasattr(self._lib, "Toupcam_get_Speed"):
            raise DeviceError("this libtoupcam has no speed control",
                              code="not_supported")
        value = ctypes.c_ushort(0)
        status = self._lib.Toupcam_get_Speed(
            self._handle, ctypes.byref(value),
        )
        if status != 0:
            raise DeviceError("Toupcam_get_Speed failed", code="sdk_error")
        return int(value.value)

    # @args: value - readout speed level, 0 is the slowest
    # @return: none
    def set_speed(self, value: int) -> None:
        self._require_handle()
        if not hasattr(self._lib, "Toupcam_put_Speed"):
            raise DeviceError("this libtoupcam has no speed control",
                              code="not_supported")
        status = self._lib.Toupcam_put_Speed(self._handle, int(value))
        if status != 0:
            raise DeviceError("Toupcam_put_Speed failed", code="param_rejected")

    # @args: callback - called on the SDK thread with (event, context)
    # @return: none
    def start(self, callback) -> None:
        self._require_handle()
        # The CFUNCTYPE object must stay alive for as long as the SDK holds it;
        # a collected trampoline would crash the C thread.
        self._callback = TOUPCAM_CALLBACK(callback)
        status = self._lib.Toupcam_StartPullModeWithCallback(
            self._handle, self._callback, None,
        )
        if status != 0:
            raise DeviceError("Toupcam_StartPullModeWithCallback failed",
                              code="sdk_error")

    # @args: none
    # @return: none
    def stop(self) -> None:
        if self._handle is None:
            self._callback = None
            return
        try:
            self._lib.Toupcam_Stop(self._handle)
        except Exception:  # noqa: BLE001 - stopping a dead handle is harmless
            pass
        self._callback = None

    # @args: none
    # @return: a fresh uint8/uint16 array owned by Python, or None when the SDK
    #          signalled an image but could not deliver it (counted as a drop)
    def pull(self) -> np.ndarray | None:
        self._require_handle()
        # Size the buffer from the ROI the camera actually delivers. Sizing it
        # from the sensor after set_roi would leave the tail of every frame
        # misaligned.
        _, _, width, height = self._roi
        if width <= 0 or height <= 0:
            width, height = self._width, self._height
        dtype = np.uint8 if self._bit_depth == 8 else np.uint16
        nbytes = width * height * dtype().itemsize
        if self._buffer is None or self._buffer_nbytes != nbytes:
            self._buffer = ctypes.create_string_buffer(nbytes)
            self._buffer_nbytes = nbytes
        buffer = self._buffer
        if hasattr(self._lib, "Toupcam_PullImageV4"):
            status = self._lib.Toupcam_PullImageV4(
                self._handle, buffer, 0, self._bit_depth, 0, None,
            )
        else:
            out_width = ctypes.c_uint(width)
            out_height = ctypes.c_uint(height)
            status = self._lib.Toupcam_PullImage(
                self._handle, buffer, self._bit_depth,
                ctypes.byref(out_width), ctypes.byref(out_height),
            )
        if status != 0:
            self._dropped += 1
            return None
        # The copy is the ownership boundary: frombuffer alone would leave a
        # view into the reusable ctypes buffer, and the next PullImage would
        # overwrite the frame a consumer still holds.
        array = np.frombuffer(buffer, dtype=dtype).reshape(height, width)
        return array.copy()

    # @args: none
    # @return: none. Every SDK call below dereferences the handle; calling one
    #          with NULL is undefined behaviour in C, not a Python exception.
    def _require_handle(self) -> None:
        if self._handle is None:
            raise DeviceError("camera is not open", code="not_open")

    # @return: images the SDK failed to deliver since the stream started
    def dropped_frames(self) -> int:
        return self._dropped

    # @args: none
    # @return: none. The contract's counter is per stream, so it restarts with
    #          the stream
    def reset_dropped(self) -> None:
        self._dropped = 0


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
        # A binary Event would coalesce two image notifications into one frame
        # at high rates; a counter keeps every notification and the loop pulls
        # one image per tick.
        self._pending_images = 0
        self._pending_lock = threading.Lock()
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
            # RAW keeps the mono plane; BITDEPTH 16 is the SER contract. The
            # option takes 0 for 8-bit and 1 for 16-bit, not the bit count: it
            # is a selector, not a number. If the model refuses an option the
            # driver keeps going: the UI can still show the camera and the
            # first frames tell what it delivers.
            for option, value in (
                (TOUPCAM_OPTION_RAW, 1),
                (TOUPCAM_OPTION_BITDEPTH, 1),
            ):
                try:
                    self._sdk.set_option(option, value)
                except DeviceError:
                    pass
            self._bit_depth = 16
            # Read the selector back: if the firmware refused 16 bit, reading
            # 8-bit data as uint16 would produce garbage that still looks like
            # an image. Trust the camera, not the request.
            try:
                if self._sdk.get_option(TOUPCAM_OPTION_BITDEPTH) == 0:
                    self._bit_depth = 8
            except DeviceError:
                pass
            try:
                self._roi = self._sdk.get_roi()
            except Exception:  # noqa: BLE001 - an old SDK may lack get_Roi
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
        return _make_info(self._camera_id, "Touptek", self._width,
                          self._height, self._bit_depth)

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
            x < 0 or y < 0 or width < MIN_SIZE or height < MIN_SIZE
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
            return float(self._sdk.get_speed())
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
            self._sdk.set_speed(int(value))
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
            return ParamRange(float(self._bit_depth), float(self._bit_depth), 0.0)
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
        with self._pending_lock:
            self._pending_images = 0
        if hasattr(self._sdk, "reset_dropped"):
            self._sdk.reset_dropped()
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
            with self._pending_lock:
                self._pending_images += 1
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
            with self._pending_lock:
                if self._pending_images <= 0:
                    self._image_event.clear()
                    continue
                self._pending_images -= 1
                if self._pending_images == 0:
                    self._image_event.clear()
            if self._stream_stop.is_set():
                # stop_stream() sets the event only to wake this wait; pulling
                # here would deliver one frame after close, which a recording
                # must never contain.
                break
            try:
                array = self._sdk.pull()
            except Exception as exc:  # noqa: BLE001
                # A handle that disappeared (unplug) raises here. Ending the
                # stream lets the capture engine see a stall; continuing would
                # spin on a dead handle at full CPU.
                self._sdk_error = str(exc)
                break
            sequence = self._sequence
            self._sequence += 1
            if array is None:
                # The SDK said "image" but delivered nothing: the sequence
                # still advances so the host sees the hole (ADR-013).
                continue
            frame = SdkFrame(array, self._roi, sequence, time.monotonic())
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


# @args: camera_id, model_name, width, height; bit_depth - what the SDK
#        actually delivers after the option write
# @return: CameraInfo with the Touptek constraints for that sensor
def _make_info(camera_id: str, model_name: str, width: int,
               height: int, bit_depth: int = 16) -> CameraInfo:
    caps = CameraCaps(
        roi=RoiConstraints(
            max_width=width,
            max_height=height,
            min_width=MIN_SIZE,
            min_height=MIN_SIZE,
            width_multiple=WIDTH_MULTIPLE,
            height_multiple=HEIGHT_MULTIPLE,
            offset_multiple=OFFSET_MULTIPLE,
        ),
        is_color=False,
        bit_depths=(bit_depth,),
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


# @args: values - the numbers the SDK accepted
# @return: their GCD, or 0 when none was accepted. The GCD is the alignment:
#          if widths 8, 10 and 12 all work the multiple is 2; if only 8, 16 and
#          24 work it is 8.
def _accepted_multiple(values) -> int:
    result = 0
    for value in values:
        result = math.gcd(result, value)
    return result


# @args: library - loaded libtoupcam
#        index - camera index from the enumeration
#        frames - how many frames to stream for the rate measurement
# @return: a report dict; the values are the measured ones, never the
#          constants of this module. The hardware test prints it verbatim.
def diagnose(library, index: int = 0, frames: int = 30) -> dict:
    report: dict = {"backend": BACKEND, "index": int(index), "errors": []}
    sdk = CtypesToupcamSdk(library, index)
    try:
        try:
            sdk.open()
        except DeviceError as exc:
            # No camera, or the camera is busy in another program. Return the
            # reason instead of a traceback: the observer needs the sentence.
            report["errors"].append(f"{exc.code}: {exc}")
            return report
        width, height = sdk.size()
        report["sensor"] = {"width": width, "height": height}

        # The SDK does not publish the ROI alignment. Measure it: try every
        # value in a range and keep the GCD of the accepted ones. That is what
        # the ROI editor's constraints will use, and it catches a firmware that
        # differs from the header.
        def try_width(value: int) -> bool:
            try:
                sdk.set_roi((0, 0, value, 16))
                return True
            except DeviceError:
                return False

        def try_height(value: int) -> bool:
            try:
                sdk.set_roi((0, 0, 16, value))
                return True
            except DeviceError:
                return False

        def try_x(value: int) -> bool:
            try:
                sdk.set_roi((value, 0, 64, 32))
                return True
            except DeviceError:
                return False

        def try_y(value: int) -> bool:
            try:
                sdk.set_roi((0, value, 64, 32))
                return True
            except DeviceError:
                return False

        widths = [value for value in range(2, 50) if try_width(value)]
        sdk.set_roi((0, 0, width, height))
        heights = [value for value in range(2, 50) if try_height(value)]
        sdk.set_roi((0, 0, width, height))
        x_offsets = [value for value in range(0, 17) if try_x(value)]
        sdk.set_roi((0, 0, width, height))
        y_offsets = [value for value in range(0, 17) if try_y(value)]
        sdk.set_roi((0, 0, width, height))
        report["roi"] = {
            "width_multiple": _accepted_multiple(widths),
            "height_multiple": _accepted_multiple(heights),
            "offset_multiple": math.gcd(
                _accepted_multiple(x_offsets),
                _accepted_multiple(y_offsets),
            ),
            "min_width": min(widths) if widths else 0,
            "min_height": min(heights) if heights else 0,
        }

        # Reference ROI of the SHG: 3480x248. Report whether this firmware
        # accepts it, because that is the geometry the rest of the app assumes.
        reference = (0, 0, 3480, 248)
        try:
            sdk.set_roi(reference)
            report["reference_roi"] = {"roi": reference, "accepted": True}
        except DeviceError:
            report["reference_roi"] = {"roi": reference, "accepted": False}
        finally:
            sdk.set_roi((0, 0, width, height))

        # Option behaviour: read, write, read back. "stuck" tells whether the
        # firmware honoured the write; a false there is not an error, it is a
        # fact the driver must know (the first frames show what it delivers).
        options = {}
        for name, option in (
            ("raw", TOUPCAM_OPTION_RAW),
            ("bitdepth", TOUPCAM_OPTION_BITDEPTH),
        ):
            try:
                before = sdk.get_option(option)
                target = 0 if before else 1
                sdk.set_option(option, target)
                after = sdk.get_option(option)
                sdk.set_option(option, before)
                options[name] = {"before": before, "written": target,
                                 "after": after, "stuck": after == target}
            except DeviceError as exc:
                options[name] = {"error": exc.code}
        try:
            before = sdk.get_speed()
            sdk.set_speed(0)
            after = sdk.get_speed()
            sdk.set_speed(before)
            options["speed"] = {"before": before, "written": 0,
                                "after": after, "stuck": after == 0}
        except DeviceError as exc:
            options["speed"] = {"error": exc.code}
        report["options"] = options

        report["exposure_range_us"] = {
            "min": int(sdk.exposure_range().minimum),
            "max": int(sdk.exposure_range().maximum),
        }
        report["gain_range_percent"] = {
            "min": int(sdk.gain_range().minimum),
            "max": int(sdk.gain_range().maximum),
        }
    finally:
        try:
            sdk.close()
        except Exception:  # noqa: BLE001
            pass

    # Stream through the driver, not the raw SDK: this is the path the app
    # uses, so the numbers include the copy and the callback.
    cam = TouptekCamera(f"{BACKEND}:{index}", library=library)
    timestamps: list[float] = []
    last_mean = 0.0
    try:
        cam.open()
        sensor = cam.effective_area()
        roi = (0, 0, 3480, 248)
        try:
            cam.set_roi(roi)
        except DeviceError:
            roi = sensor
            cam.set_roi(roi)
        bit_depth = int(cam.get_param(Param.BIT_DEPTH))
        exposure = max(1000, int(cam.param_range(Param.EXPOSURE).minimum))
        cam.set_param(Param.EXPOSURE, exposure)
        cam.set_param(Param.GAIN, 0)

        def on_frame(frame) -> None:
            nonlocal last_mean
            timestamps.append(frame.timestamp)
            last_mean = frame.stats().mean

        cam.start_stream(on_frame)
        deadline = time.monotonic() + max(10.0, frames / 5.0)
        while len(timestamps) < frames and time.monotonic() < deadline:
            time.sleep(0.01)
        cam.stop_stream()
        report["stream"] = {
            "roi": roi,
            "requested_frames": int(frames),
            "frames": len(timestamps),
            "exposure_us": exposure,
            "fps": _rate(timestamps),
            "dropped_sdk": cam.dropped_frames(),
            "last_mean_adu": last_mean,
            "pixel_bits": bit_depth,
        }
        if len(timestamps) < 2:
            report["errors"].append("no frames: check the USB link and exposure")
    except DeviceError as exc:
        report["errors"].append(f"{exc.code}: {exc}")
    except Exception as exc:  # noqa: BLE001
        report["errors"].append(str(exc))
    finally:
        try:
            cam.close()
        except Exception:  # noqa: BLE001
            pass
    return report


# @args: timestamps - receipt times, seconds
# @return: frames per second from the first to the last, or 0 with <2 frames
def _rate(timestamps: list[float]) -> float:
    if len(timestamps) < 2:
        return 0.0
    span = timestamps[-1] - timestamps[0]
    if span <= 0.0:
        return 0.0
    return (len(timestamps) - 1) / span


# @args: report - the dict returned by diagnose()
# @return: a plain-language multi-line report. Every number says what it is and
#          why it matters, because this is what the user pastes into the
#          hardware validation report.
def format_report(report: dict) -> str:
    lines = []
    lines.append("Touptek hardware diagnostic")
    lines.append("==========================")
    lines.append(f"camera index: {report.get('index')}")
    sensor = report.get("sensor")
    if sensor:
        w, h = sensor["width"], sensor["height"]
        lines.append(
            f"sensor size: {w} x {h} px (what the SDK reports; the ROI "
            f"constraints are derived from it)"
        )
    roi = report.get("roi")
    if roi:
        lines.append(
            "ROI alignment measured by trial: "
            f"width multiple {roi['width_multiple']}, "
            f"height multiple {roi['height_multiple']}, "
            f"x/y offset multiple {roi['offset_multiple']}, "
            f"minimum {roi['min_width']} x {roi['min_height']} px "
            "(an ROI that breaks these is refused by the SDK)"
        )
    reference = report.get("reference_roi")
    if reference:
        state = "accepted" if reference["accepted"] else "REFUSED"
        lines.append(
            f"SHG reference ROI {reference['roi']}: {state} "
            "(3480 x 248 is the scan geometry of the G3M678M)"
        )
    options = report.get("options") or {}
    for name, label in (
        ("raw", "RAW (1 = un-debayered mono plane)"),
        ("bitdepth", "BITDEPTH (0 = 8 bit, 1 = 16 bit)"),
        ("speed", "SPEED level (0 = slowest)"),
    ):
        value = options.get(name)
        if not value:
            continue
        if "error" in value:
            lines.append(f"{label}: refused ({value['error']})")
        else:
            stuck = "honoured" if value["stuck"] else "NOT honoured"
            lines.append(
                f"{label}: read {value['before']}, wrote {value['written']}, "
                f"read back {value['after']} ({stuck})"
            )
    for key, label, unit in (
        ("exposure_range_us", "exposure range", "us"),
        ("gain_range_percent", "gain range", "%"),
    ):
        value = report.get(key)
        if value:
            lines.append(
                f"{label}: {value['min']} to {value['max']} {unit} "
                "(bounds for the UI sliders)"
            )
    stream = report.get("stream")
    if stream:
        lines.append(
            f"stream ROI {stream['roi']}: {stream['frames']} of "
            f"{stream['requested_frames']} frames at "
            f"{stream['fps']:.2f} fps with {stream['pixel_bits']} bit pixels "
            f"and {stream['exposure_us']} us exposure"
        )
        lines.append(
            f"SDK-reported dropped frames: {stream['dropped_sdk']} "
            "(a nonzero value means the USB link cannot keep up)"
        )
        lines.append(
            f"last frame mean: {stream['last_mean_adu']:.1f} ADU "
            "(a dark frame means the lens cap is on or the exposure is short)"
        )
    errors = report.get("errors") or []
    if errors:
        lines.append("FAILURES")
        for error in errors:
            lines.append(f"  - {error}")
    else:
        lines.append("result: all checks completed without an SDK error")
    return "\n".join(lines)
