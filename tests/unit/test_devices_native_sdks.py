############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - native SDK drivers test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Driver contracts of the ZWO, QHY and Player One wrappers (ADR-002).
#
# The wrappers themselves are covered by the signature test in
# test_devices_native.py; what is exercised here is the Camera contract on top
# of them: open, ROI, parameters, a streamed frame and the drop counter. Each
# SDK is injected as a fake object, so no vendor library is loaded and no
# hardware is touched. The real-camera smoke tests live in
# tests/functional/test_devices_hardware.py and are marked `hardware`.

import ctypes
import threading

import numpy as np
import pytest

from solarscribe.devices.abc import Camera, DeviceError, Param, ParamRange
from solarscribe.devices.native.playerone import PlayerOneCamera
from solarscribe.devices.native.qhy import QhyCamera
from solarscribe.devices.native.zwo import AsiCamera


class _Info:
    # Stands in for an SDK camera-info struct.

    def __init__(self, **values):
        for key, value in values.items():
            setattr(self, key, value)


class FakeAsiSdk:
    def __init__(self, width=64, height=32, payload=5):
        self.width = width
        self.height = height
        self.payload = payload
        self.opened = False
        self.closed = False
        self.roi = (0, 0, width, height)
        self.controls = {0: 100, 1: 1000, 5: 0, 6: 50, 8: 215}
        self.started = False
        self.stopped = False
        self.dropped_count = 0

    def open(self, camera_id):
        self.opened = True

    def close(self, camera_id):
        self.closed = True

    def camera_infos(self):
        return [_Info(MaxWidth=self.width, MaxHeight=self.height, BitDepth=16,
                      IsColorCam=0, IsCoolerCam=0)]

    def get_roi(self, camera_id):
        if self.started:
            return self.roi
        return self.roi

    def set_roi(self, camera_id, roi):
        self.roi = roi

    def get_control(self, camera_id, control):
        return self.controls[control], False

    def set_control(self, camera_id, control, value):
        self.controls[control] = int(value)

    def control_range(self, camera_id, control):
        return ParamRange(0.0, 10_000.0, 1.0)

    def start_video(self, camera_id):
        self.started = True

    def stop_video(self, camera_id):
        self.stopped = True

    def read(self, camera_id, buffer, nbytes, timeout_ms=200):
        _, _, width, height = self.roi
        payload = np.full((height, width), self.payload, dtype=np.uint16)
        ctypes.memmove(buffer, payload.tobytes(), nbytes)
        return True

    def dropped(self, camera_id):
        return self.dropped_count


class FakeQhySdk:
    def __init__(self, width=64, height=32, payload=7):
        self.width = width
        self.height = height
        self.payload = payload
        self.opened = False
        self.closed = False
        self.handle = 1234
        self.roi = (0, 0, width, height)
        self.controls = {6: 10, 7: 0, 8: 1000, 9: 0}
        self.resource_users = 0
        self.live = False
        self.polls = 0

    def init_resource(self):
        self.resource_users += 1

    def release_resource(self):
        self.resource_users -= 1

    def open(self, camera_id):
        self.opened = True
        return self.handle

    def close(self, handle):
        self.closed = True

    def set_stream_mode(self, handle, mode):
        pass

    def init_camera(self, handle):
        pass

    def chip_info(self, handle):
        return self.width, self.height, 16

    def set_bits_mode(self, handle, bits):
        pass

    def set_resolution(self, handle, roi):
        self.roi = roi

    def mem_length(self, handle):
        return self.width * self.height * 2

    def set_param(self, handle, control, value):
        self.controls[control] = value

    def get_param(self, handle, control):
        return self.controls[control]

    def param_range(self, handle, control):
        return ParamRange(0.0, 10_000.0, 1.0)

    def begin_live(self, handle):
        self.live = True

    def read_live(self, handle, buffer):
        self.polls += 1
        _, _, width, height = self.roi
        payload = np.full((height, width), self.payload, dtype=np.uint16)
        ctypes.memmove(buffer, payload.tobytes(), payload.nbytes)
        return width, height, 16

    def stop_live(self, handle):
        self.live = False

    def cancel(self, handle):
        pass


class FakePoaSdk:
    def __init__(self, width=64, height=32, payload=9):
        self.width = width
        self.height = height
        self.payload = payload
        self.opened = False
        self.closed = False
        self.roi = (0, 0, width, height)
        self.configs = {0: 1000, 1: 100, 7: 0, 28: 50, 3: 215}
        self.exposing = False
        self.dropped_count = 0

    def open(self, camera_id):
        self.opened = True

    def close(self, camera_id):
        self.closed = True

    def camera_properties(self):
        return [_Info(cameraID=0, maxWidth=self.width, maxHeight=self.height,
                      bitDepth=16, isColorCamera=0, isHasCooler=0,
                      imgFormats=[1, 3, -1, 0])]

    def set_raw16(self, camera_id):
        pass

    def set_roi(self, camera_id, roi):
        self.roi = roi

    def get_config(self, camera_id, config):
        return self.configs[config], False

    def get_config_float(self, camera_id, config):
        return float(self.configs[config])

    def set_config(self, camera_id, config, value):
        self.configs[config] = int(value)

    def config_range(self, camera_id, config):
        return ParamRange(0.0, 10_000.0, 1.0)

    def start_exposure(self, camera_id, single=False):
        self.exposing = True

    def stop_exposure(self, camera_id):
        self.exposing = False

    def read(self, camera_id, buffer, nbytes, timeout_ms=200):
        _, _, width, height = self.roi
        payload = np.full((height, width), self.payload, dtype=np.uint16)
        ctypes.memmove(buffer, payload.tobytes(), nbytes)
        return True

    def dropped(self, camera_id):
        return self.dropped_count


# @args: cam - opened camera with a fake SDK; payload - expected pixel value
# @return: the frame the stream delivered
def _stream_one(cam, payload):
    frames = []
    arrived = threading.Event()

    def on_frame(frame):
        frames.append(frame)
        arrived.set()

    cam.start_stream(on_frame)
    assert arrived.wait(2.0), "the fake SDK did not deliver a frame"
    cam.stop_stream()
    assert frames
    frame = frames[0]
    array = np.frombuffer(frame.data, dtype=frame.dtype).reshape(
        frame.height, frame.width,
    )
    assert np.all(array == payload)
    return frame


def test_asi_camera_contract_and_stream():
    sdk = FakeAsiSdk(payload=5)
    cam = AsiCamera("native/asi:0", sdk=sdk)
    assert isinstance(cam, Camera)
    cam.open()
    assert sdk.opened and cam.is_open()
    assert cam.info().caps.roi.max_width == 64
    cam.set_roi((0, 0, 32, 16))
    assert cam.get_roi() == (0, 0, 32, 16)
    cam.set_param(Param.EXPOSURE, 5000)
    assert cam.get_param(Param.EXPOSURE) == pytest.approx(5000.0)
    assert cam.param_range(Param.GAIN).maximum == pytest.approx(10_000.0)
    frame = _stream_one(cam, 5)
    assert frame.width == 32 and frame.height == 16
    assert sdk.started and sdk.stopped
    cam.close()
    assert sdk.closed and not cam.is_open()


def test_asi_rejects_a_roi_that_breaks_the_alignment():
    cam = AsiCamera("native/asi:0", sdk=FakeAsiSdk())
    cam.open()
    with pytest.raises(DeviceError) as exc:
        cam.set_roi((0, 0, 10, 16))     # width must be a multiple of 8
    assert exc.value.code == "roi_rejected"
    cam.close()


def test_qhy_camera_contract_and_stream():
    sdk = FakeQhySdk(payload=7)
    cam = QhyCamera("native/qhy:QHY5III585C-1234", sdk=sdk)
    assert isinstance(cam, Camera)
    cam.open()
    assert sdk.opened and cam.is_open()
    assert cam.info().caps.roi.max_width == 64
    assert sdk.resource_users == 1
    cam.set_roi((0, 0, 32, 16))
    cam.set_param(Param.EXPOSURE, 5000)
    assert cam.get_param(Param.EXPOSURE) == pytest.approx(5000.0)
    frame = _stream_one(cam, 7)
    assert frame.width == 32 and frame.height == 16
    cam.close()
    assert sdk.closed and sdk.resource_users == 0
    assert cam.dropped_frames() == 0     # the QHY SDK has no counter


def test_playerone_camera_contract_and_stream():
    sdk = FakePoaSdk(payload=9)
    cam = PlayerOneCamera("native/playerone:0", sdk=sdk)
    assert isinstance(cam, Camera)
    cam.open()
    assert sdk.opened and cam.is_open()
    assert cam.info().caps.roi.max_width == 64
    cam.set_roi((0, 0, 32, 16))
    cam.set_param(Param.EXPOSURE, 5000)
    assert cam.get_param(Param.EXPOSURE) == pytest.approx(5000.0)
    frame = _stream_one(cam, 9)
    assert frame.width == 32 and frame.height == 16
    cam.close()
    assert sdk.closed and not cam.is_open()


def test_unopened_native_cameras_refuse_to_stream():
    for cam in (
        AsiCamera("native/asi:0", sdk=FakeAsiSdk()),
        QhyCamera("native/qhy:cam", sdk=FakeQhySdk()),
        PlayerOneCamera("native/playerone:0", sdk=FakePoaSdk()),
    ):
        with pytest.raises(DeviceError) as exc:
            cam.start_stream(lambda frame: None)
        assert exc.value.code == "not_open"
