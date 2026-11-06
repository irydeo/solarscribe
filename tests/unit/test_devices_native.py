############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - native SDK test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The native camera path (ADR-001, ADR-002): dynamic loading, graceful absence
# and one real driver (Touptek) tested against a mocked library. No hardware is
# touched here; the real-G3M678M numbers belong to the hardware report.

import threading
import time

import numpy as np
import pytest

from solarscribe.devices.abc import (
    BackendReason, Camera, DeviceError, Param, RoiConstraints,
)
from solarscribe.devices.native import native_camera_backends
from solarscribe.devices.native.backend import NativeCameraBackend
from solarscribe.devices.native.loader import load_library
from solarscribe.devices.native.touptek import (
    TOUPCAM_EVENT_IMAGE, CtypesToupcamSdk, TouptekCamera,
)


class FakeSdk:
    # Stands in for CtypesToupcamSdk. It keeps the state a mocked library would
    # keep, so the driver contract can be tested without ctypes trampolines.

    def __init__(self, width=64, height=32, payload=7):
        self.width = width
        self.height = height
        self.payload = payload
        self.opened = False
        self.roi = (0, 0, width, height)
        self.exposure = 1000.0
        self.gain = 0.0
        self.options = {}
        self.callback = None
        self.dropped = 0
        self.fail_next = 0
        self.pull_calls = 0
        self.pulled = threading.Event()

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def size(self):
        return self.width, self.height

    def set_option(self, option, value):
        self.options[option] = value

    def get_option(self, option):
        return self.options.get(option, 0)

    def get_roi(self):
        return self.roi

    def set_roi(self, roi):
        self.roi = roi

    def get_exposure(self):
        return self.exposure

    def set_exposure(self, value):
        self.exposure = float(value)

    def exposure_range(self):
        from solarscribe.devices.abc import ParamRange
        return ParamRange(1.0, 1_000_000.0, 1.0)

    def get_gain(self):
        return self.gain

    def set_gain(self, value):
        self.gain = float(value)

    def gain_range(self):
        from solarscribe.devices.abc import ParamRange
        return ParamRange(0.0, 1000.0, 1.0)

    def start(self, callback):
        self.callback = callback

    def stop(self):
        self.callback = None

    def trigger(self):
        assert self.callback is not None
        self.callback(TOUPCAM_EVENT_IMAGE, None)

    def pull(self):
        self.pull_calls += 1
        self.pulled.set()
        if self.fail_next > 0:
            self.fail_next -= 1
            self.dropped += 1
            return None
        _, _, width, height = self.roi
        return np.full((height, width), self.payload, dtype=np.uint16)

    def dropped_frames(self):
        return self.dropped


class FakeLibrary:
    # Minimal libtoupcam surface: just what discovery uses.

    def __init__(self, devices=((b"cam-1", "ToupTek G3M678M", 678),), size=(64, 32)):
        self._devices = devices
        self._size = size
        self.closed = []

    def Toupcam_EnumV2(self, array):
        for i, (device_id, display, model) in enumerate(self._devices):
            array[i].id = device_id
            array[i].displayname = display
            array[i].model = model
        return len(self._devices)

    def Toupcam_OpenByIndex(self, index):
        return index + 1

    def Toupcam_get_Size(self, handle, width, height):
        width._obj.value = self._size[0]
        height._obj.value = self._size[1]
        return 0

    def Toupcam_Close(self, handle):
        self.closed.append(handle)


def test_loader_returns_none_for_a_missing_sdk():
    assert load_library(("solarscribe-definitely-not-installed",)) is None


def test_missing_sdk_is_an_absent_backend_not_an_exception():
    backend = NativeCameraBackend(
        "native/test", "Test", ("libtest.so",),
        driver=object, loader=lambda names: None,
    )
    reason, detail = backend.probe()
    assert reason is BackendReason.SDK_MISSING
    assert "libtest.so" in detail
    assert backend.cameras() == []
    with pytest.raises(DeviceError) as exc:
        backend.create("native/test:0")
    assert exc.value.code == "backend_unavailable"


def test_skeleton_backend_reports_the_missing_wrapper():
    # The SDK is there but the driver is not written yet: ERROR with a stable
    # detail, so diagnostics can explain it instead of hiding the device.
    backend = NativeCameraBackend(
        "native/x", "X", ("libx.so",), driver=None,
        loader=lambda names: object(),
    )
    reason, detail = backend.probe()
    assert reason is BackendReason.ERROR
    assert "driver_not_implemented" in detail


def test_native_backends_all_degrade_when_the_loader_finds_nothing():
    backends = native_camera_backends(loader=lambda names: None)
    names = [b.name for b in backends]
    assert names == ["native/touptek", "native/asi", "native/qhy",
                     "native/playerone"]
    for backend in backends:
        reason, _ = backend.probe()
        assert reason is BackendReason.SDK_MISSING


def test_ctypes_wrapper_enumerates_and_reads_the_sensor_size():
    library = FakeLibrary()
    devices = CtypesToupcamSdk.enumerate(library)
    assert len(devices) == 1
    assert devices[0].device_id == "cam-1"
    assert devices[0].index == 0

    sdk = CtypesToupcamSdk(library, 0)
    sdk.open()
    assert sdk.size() == (64, 32)
    sdk.close()
    assert library.closed == [1]


def test_touptek_discovery_uses_the_real_sensor_size():
    infos = TouptekCamera.discover(FakeLibrary(size=(640, 480)))
    assert len(infos) == 1
    info = infos[0]
    assert info.camera_id == "native/touptek:0"
    assert info.backend == "native/touptek"
    assert info.caps.roi.max_width == 640
    assert info.caps.roi.max_height == 480
    assert info.caps.roi.width_multiple == 4
    assert info.caps.roi.height_multiple == 2


def test_touptek_camera_satisfies_the_contract_and_streams_owned_frames():
    sdk = FakeSdk(width=64, height=32, payload=11)
    cam = TouptekCamera("native/touptek:0", sdk=sdk)
    assert isinstance(cam, Camera)
    cam.open()
    assert cam.is_open()
    assert cam.info().caps.roi == RoiConstraints(
        max_width=64, max_height=32, width_multiple=4,
        height_multiple=2, offset_multiple=4,
    )

    cam.set_roi((0, 0, 32, 16))
    assert cam.get_roi() == (0, 0, 32, 16)
    cam.set_param(Param.EXPOSURE, 5000)
    assert cam.get_param(Param.EXPOSURE) == pytest.approx(5000.0)
    cam.set_param(Param.GAIN, 120)
    assert cam.get_param(Param.GAIN) == pytest.approx(120.0)
    assert cam.param_range(Param.EXPOSURE).maximum >= 5000.0

    frames = []
    arrived = threading.Event()

    def on_frame(frame):
        frames.append(frame)
        arrived.set()

    cam.start_stream(on_frame)
    sdk.trigger()
    assert arrived.wait(2.0)
    cam.stop_stream()

    frame = frames[0]
    assert frame.width == 32 and frame.height == 16
    assert frame.sequence == 0
    array = np.frombuffer(frame.data, dtype=frame.dtype).reshape(16, 32)
    assert np.all(array == 11)
    assert frame.stats().mean == pytest.approx(11.0)
    cam.close()
    assert not cam.is_open()


def test_touptek_rejects_a_roi_the_sdk_constraints_would_refuse():
    cam = TouptekCamera("native/touptek:0", sdk=FakeSdk(width=64, height=32))
    cam.open()
    with pytest.raises(DeviceError) as exc:
        cam.set_roi((1, 0, 32, 16))   # x is not a multiple of 4
    assert exc.value.code == "roi_rejected"
    with pytest.raises(DeviceError):
        cam.set_roi((0, 0, 42, 16))   # width is not a multiple of 4
    cam.close()


def test_touptek_counts_a_dropped_image_as_a_sequence_hole():
    sdk = FakeSdk(width=64, height=32)
    sdk.fail_next = 1
    cam = TouptekCamera("native/touptek:0", sdk=sdk)
    cam.open()
    frames = []
    arrived = threading.Event()

    def on_frame(frame):
        frames.append(frame)
        arrived.set()

    cam.start_stream(on_frame)
    sdk.trigger()            # image event, pull returns None: drop
    assert sdk.pulled.wait(2.0)
    sdk.pulled.clear()
    sdk.trigger()            # next image arrives
    assert arrived.wait(2.0)
    cam.stop_stream()

    assert len(frames) == 1
    assert frames[0].sequence == 1      # 0 was the hole
    assert cam.dropped_frames() == 1
    cam.close()
