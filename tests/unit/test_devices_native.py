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

# The native camera path (ADR-001, ADR-002): dynamic loading, graceful absence,
# the ctypes signature tables that stop a 64-bit handle from being truncated,
# and the Touptek driver tested against a mocked library. No hardware is
# touched here; the real-camera numbers belong to the hardware report.

import ast
import ctypes
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from solarscribe.devices.abc import (
    BackendReason, Camera, DeviceError, Param, RoiConstraints,
)
from solarscribe.devices.native import (
    native_camera_backends, playerone as playerone_module,
    qhy as qhy_module, touptek as touptek_module, zwo as zwo_module,
)
from solarscribe.devices.native.backend import NativeCameraBackend
from solarscribe.devices.native.loader import load_library
from solarscribe.devices.native.signatures import apply_signatures
from solarscribe.devices.native.touptek import (
    TOUPCAM_EVENT_IMAGE, TOUPCAM_EVENT_ERROR, TOUPCAM_OPTION_BITDEPTH,
    TOUPCAM_OPTION_RAW, CtypesToupcamSdk, TouptekCamera,
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
    # Minimal libtoupcam surface: just what discovery uses. The strings are
    # bytes because the Linux struct field is char[64]; on Windows it would be
    # wchar_t[64] and the driver decodes whichever the ABI hands it.
    #
    # The attributes here are plain Python methods, so apply_signatures() cannot
    # set restype/argtypes on them (a bound method has no __dict__). That is
    # fine: this fake exercises the driver logic, and the signature coverage
    # test uses a settable double.

    def __init__(self, devices=((b"cam-1", b"ToupTek G3M678M", 678),),
                 size=(64, 32)):
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
    assert info.caps.roi.width_multiple == 2
    assert info.caps.roi.height_multiple == 2
    assert info.caps.roi.min_width == 8


def test_touptek_camera_satisfies_the_contract_and_streams_owned_frames():
    sdk = FakeSdk(width=64, height=32, payload=11)
    cam = TouptekCamera("native/touptek:0", sdk=sdk)
    assert isinstance(cam, Camera)
    cam.open()
    assert cam.is_open()
    assert cam.info().caps.roi == RoiConstraints(
        max_width=64, max_height=32, min_width=8, min_height=8,
        width_multiple=2, height_multiple=2, offset_multiple=2,
    )
    # The option is a selector: 1 means 16 bit. Writing 16 (the bit count) is
    # one of the silent mistakes that yields 8-bit frames.
    assert sdk.options[TOUPCAM_OPTION_BITDEPTH] == 1

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
        cam.set_roi((1, 0, 32, 16))   # x is not a multiple of 2
    assert exc.value.code == "roi_rejected"
    with pytest.raises(DeviceError):
        cam.set_roi((0, 0, 41, 16))   # width is not even
    with pytest.raises(DeviceError):
        cam.set_roi((0, 0, 4, 16))    # below the SDK minimum of 8
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


# --- Signature coverage: the fix that stops the "Find cameras" core dump ---
#
# ctypes defaults every restype to c_int. The SDK Open calls return 64-bit
# pointers, so an undeclared signature truncates the handle and the next call
# segfaults with no traceback. These tests fail on any symbol the wrappers call
# without a declaration, and on any handle opener whose restype is not void*.


NATIVE_DIR = Path(touptek_module.__file__).parent

MODULES = {
    "touptek.py": touptek_module,
    "zwo.py": zwo_module,
    "qhy.py": qhy_module,
    "playerone.py": playerone_module,
}

# The functions that return an opaque handle. Their restype must be c_void_p;
# anything else truncates the pointer on a 64-bit machine.
HANDLE_OPENERS = {
    "touptek.py": {"Toupcam_OpenByIndex"},
    "zwo.py": set(),
    "qhy.py": {"OpenQHYCCD"},
    "playerone.py": set(),
}


class _RecordedFunction:
    # Settable function double: records what apply_signatures writes.

    def __init__(self):
        self.restype = None
        self.argtypes = None


class _RecordingLibrary:
    # A CDLL-like object whose every symbol accepts the two ctypes attributes.

    def __init__(self, names):
        self._functions = {name: _RecordedFunction() for name in names}

    def __getattr__(self, name):
        try:
            return self._functions[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _used_symbols(path: Path) -> set:
    # Walk the source instead of the object: a conditional call (hasattr) or a
    # symbol inside a helper still has to be declared, and an import of the
    # module would need the SDK to exist.
    tree = ast.parse(path.read_text(encoding="utf-8"))
    used = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        owner = node.value
        # self._lib.<symbol> is an SDK call by definition. self._sdk.<method>
        # is a Python helper and must not be treated as a symbol.
        if isinstance(owner, ast.Attribute) and owner.attr == "_lib":
            used.add(node.attr)
        elif isinstance(owner, ast.Name) and owner.id == "library":
            used.add(node.attr)
    return used


@pytest.mark.parametrize("filename,module", MODULES.items())
def test_every_sdk_symbol_the_wrapper_calls_has_a_signature(filename, module):
    used = _used_symbols(NATIVE_DIR / filename)
    missing = used - set(module.SIGNATURES)
    assert not missing, f"{filename} calls undeclared SDK symbols: {sorted(missing)}"


@pytest.mark.parametrize("filename,module", MODULES.items())
def test_signatures_are_applied_to_every_declared_symbol(filename, module):
    names = set(module.SIGNATURES)
    library = _RecordingLibrary(names)
    configured = apply_signatures(library, module.SIGNATURES)
    assert configured == names
    for symbol in names:
        function = getattr(library, symbol)
        assert function.argtypes is not None, f"{filename}: {symbol} has no argtypes"
        restype, argtypes = module.SIGNATURES[symbol]
        assert function.restype is restype
        assert function.argtypes == list(argtypes)


@pytest.mark.parametrize("filename,module", MODULES.items())
def test_handle_openers_return_a_pointer(filename, module):
    for symbol in HANDLE_OPENERS[filename]:
        restype, _argtypes = module.SIGNATURES[symbol]
        assert restype is ctypes.c_void_p, (
            f"{filename}: {symbol} returns a handle; a c_int restype truncates "
            "it on a 64-bit machine"
        )


def test_toupcam_device_struct_matches_the_vendor_abi():
    # ToupcamDeviceV2 is: wchar_t/char displayname[64], id[64], model pointer.
    # The old 20-byte struct made Toupcam_EnumV2 write 17 KB into a 2.5 KB
    # array, which is a heap overflow and the likely original core dump.
    fields = [name for name, _type in touptek_module._DeviceV2._fields_]
    assert fields == ["displayname", "id", "model"]
    char = ctypes.sizeof(touptek_module._WCHAR)
    assert ctypes.sizeof(touptek_module._DeviceV2) == 2 * 64 * char + ctypes.sizeof(
        ctypes.c_void_p
    )
    assert touptek_module.TOUPCAM_MAX == 128


def test_touptek_event_and_option_constants_match_the_header():
    # These were wrong in the first transcription: 0x0010 is FRONT_OVERFLOW,
    # not IMAGE, and 0x0013 is DEMOSAIC_VIDEO, not BITDEPTH.
    assert TOUPCAM_EVENT_IMAGE == 0x0004
    assert TOUPCAM_EVENT_ERROR == 0x0080
    assert TOUPCAM_OPTION_BITDEPTH == 0x06
    assert TOUPCAM_OPTION_RAW == 0x04


def test_touptek_report_explains_every_measured_number():
    # The observer pastes this text into the hardware report; a bare number is
    # not acceptable, so every line must carry its unit and its meaning.
    from solarscribe.devices.native.touptek import format_report

    report = {
        "backend": "native/touptek",
        "index": 0,
        "sensor": {"width": 3840, "height": 2160},
        "roi": {"width_multiple": 2, "height_multiple": 2,
                "offset_multiple": 2, "min_width": 8, "min_height": 8},
        "reference_roi": {"roi": (0, 0, 3480, 248), "accepted": True},
        "options": {
            "raw": {"before": 0, "written": 1, "after": 1, "stuck": True},
            "bitdepth": {"before": 0, "written": 1, "after": 1, "stuck": True},
            "speed": {"before": 3, "written": 0, "after": 0, "stuck": True},
        },
        "exposure_range_us": {"min": 10, "max": 1000000},
        "gain_range_percent": {"min": 100, "max": 1000},
        "stream": {"roi": (0, 0, 3480, 248), "requested_frames": 30,
                   "frames": 30, "exposure_us": 1000, "fps": 120.5,
                   "dropped_sdk": 0, "last_mean_adu": 1234.0,
                   "pixel_bits": 16},
        "errors": [],
    }
    text = format_report(report)
    assert "sensor size: 3840 x 2160" in text
    assert "width multiple 2" in text
    assert "3480 x 248" in text
    assert "120.50 fps" in text
    assert "dropped frames: 0" in text
    assert "ADU" in text
    assert "all checks completed" in text


def test_touptek_refuses_sdk_calls_before_open_instead_of_dereferencing_null():
    # Every libtoupcam call takes the handle; with NULL the C side is undefined
    # behaviour. The wrapper turns that into a stable error.
    from solarscribe.devices.native.touptek import CtypesToupcamSdk

    sdk = CtypesToupcamSdk(FakeLibrary(), 0)
    with pytest.raises(DeviceError) as exc:
        sdk.size()
    assert exc.value.code == "not_open"
    sdk.stop()          # stopping an unopened camera must be a no-op
    assert sdk.dropped_frames() == 0


def test_touptek_diagnostic_reports_a_missing_camera_without_a_traceback():
    from solarscribe.devices.native.touptek import diagnose, format_report

    class NoCameraLibrary(FakeLibrary):
        def Toupcam_OpenByIndex(self, index):
            return 0

    report = diagnose(NoCameraLibrary(), index=0, frames=1)
    assert report["errors"]
    text = format_report(report)
    assert "FAILURES" in text
    assert "device_lost" in text
