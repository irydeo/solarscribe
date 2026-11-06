############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - layer contract test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The dependency rule and the contract surface (design/ARCHITECTURE.md 1 and 2,
# ADR-012, ADR-023). QE custodies this file from here on (ADR-015).
#
# The rule is law: ui and cli depend on capture and shg; capture and shg depend
# on devices and on config; devices and config depend on nothing from the
# application. shg touches no Qt and no driver.
#
# The check parses the sources with ast instead of importing them, and that is
# deliberate: an import only proves what the machine happens to have installed.
# A missing SDK or a missing Qt would hide a violation (the import would fail
# first, or the offending line would sit behind a try), while the syntax tree
# says what the code actually asks for, on every platform and in every CI job.

from __future__ import annotations

import ast
import importlib
import inspect
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import get_args, get_type_hints

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "solarscribe"

# The six layers, bottom up. config is a support leaf: it may read the ROI alias
# from devices and nothing else (ADR-023).
LAYERS = ("devices", "config", "capture", "shg", "ui", "cli")

# What each layer may import from inside the application. Anything else is a
# violation, including the sibling edges capture <-> shg: they are two engines
# under the same roof, and shg reaches the stream through the ports it declares
# itself, not by importing capture.
ALLOWED = {
    "devices": frozenset(),
    "config": frozenset({"devices"}),
    "capture": frozenset({"devices", "config"}),
    "shg": frozenset({"devices", "config"}),
    "ui": frozenset({"devices", "capture", "shg", "config"}),
    "cli": frozenset({"devices", "capture", "shg", "config", "ui"}),
}

# Qt belongs to ui alone. cli starts the GUI by delegating to ui.app, so it never
# needs a Qt import of its own, and the four logic layers must stay headless to
# be testable without a display (ADR-005).
QT_ROOTS = frozenset({"PySide6", "shiboken6", "PyQt5", "PyQt6"})
NO_QT_LAYERS = ("devices", "config", "capture", "shg", "cli")

# ctypes and cffi are how the drivers talk to the C SDKs (ADR-001). Outside
# devices they mean a layer is touching hardware behind the contract's back.
DRIVER_ROOTS = frozenset({"ctypes", "cffi"})
NO_DRIVER_LAYERS = ("config", "capture", "shg", "ui", "cli")

# The contract surface: what every agent codes against. A name missing from this
# table means a contract was renamed or dropped, which is an ADR-level event, not
# a refactor (ADR-012).
CONTRACT_NAMES = {
    "solarscribe.devices.abc": (
        "ROI", "Frame", "FrameStats", "Param", "ParamRange", "RoiConstraints",
        "CameraCaps", "CameraInfo", "Camera", "Axis", "MountCaps", "MountStatus",
        "MountInfo", "Mount", "DeviceKind", "BackendReason", "BackendInfo",
        "DeviceManager", "DeviceError",
    ),
    "solarscribe.capture.abc": (
        "CaptureParams", "SerColorId", "SerHeader", "WriterCounters",
        "StreamCounters", "SerWriter", "CaptureEngine", "RoiIssue", "Severity",
        "RoiWarning", "RoiModel",
    ),
    "solarscribe.shg.abc": (
        "ScanMode", "DecCenterMethod", "PreparePhase", "ScanState", "ScanStatus",
        "ScanRow", "ScanConfig", "ScanPlan", "PrepareStatus", "PrepareResult",
        "ScanProgress", "ScanResult", "FrameSource", "RowCounters", "RowRecorder",
        "ScanEngine", "TiltResult", "TiltMeter", "ANALYSIS_KEYS",
        "analysis_regions", "CenteringStatus", "CenteringResult",
        "SunCenteringService", "PolarSample", "PolarProgress", "PolarResult",
        "PolarAlignmentAssistant",
    ),
    "solarscribe.config.schema": (
        "Key", "SCHEMA", "keys_of", "default_value", "TelescopeData",
        "CameraData", "RoiPreset", "Profile", "StepStatus", "SESSION_STEPS",
        "StepState", "new_steps", "SessionState", "CONFIG_FILE", "PROFILE_FILE",
        "SESSION_STATE_FILE", "PROFILE_VERSION",
    ),
}

# Protocols the test suite asserts its simulators and mocks against, so they must
# be runtime_checkable (ADR-005: everything is tested without hardware).
RUNTIME_PROTOCOLS = {
    "solarscribe.devices.abc": ("Frame", "FrameStats", "Camera", "Mount",
                                "DeviceManager"),
    "solarscribe.capture.abc": ("SerWriter", "CaptureEngine"),
    "solarscribe.shg.abc": ("FrameSource", "RowRecorder", "ScanEngine",
                            "TiltMeter", "SunCenteringService",
                            "PolarAlignmentAssistant"),
}


# @args: layer - one of LAYERS
# @return: the .py files of that layer, sorted, without the bytecode caches
def layer_files(layer: str) -> list[Path]:
    root = PACKAGE_DIR / layer
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


# @args: path - a .py file inside the package
# @return: the package that contains it, as dotted parts. An __init__.py IS its
#          package, which is what makes a relative import from it resolve to the
#          package itself instead of to its parent
def package_parts(path: Path) -> tuple[str, ...]:
    parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if parts[-1] != "__init__":
        parts = parts[:-1]
    return tuple(parts)


# @args: name - a dotted module name
# @return: (root, layer) where layer is the solarscribe subpackage, or None when
#          the import is not inside the application
def split_name(name: str) -> tuple[str, str | None]:
    bits = name.split(".")
    layer = bits[1] if bits[0] == "solarscribe" and len(bits) > 1 else None
    return bits[0], layer


# @args: path - a .py file to read
# @return: every (root, layer) the file imports, absolute and relative alike
def imported_names(path: Path) -> set[tuple[str, str | None]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = package_parts(path)
    found: set[tuple[str, str | None]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(split_name(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # level 1 is the current package, level 2 its parent, and so on
                base = package[: len(package) - (node.level - 1)]
                parts = base + ((node.module,) if node.module else ())
                name = ".".join(parts)
            else:
                name = node.module or ""
            if name:
                found.add(split_name(name))
    return found


def test_every_layer_has_sources_to_check():
    # A guard against a vacuous pass: if a layer directory is renamed or emptied,
    # the rule would look satisfied because nothing was read.
    for layer in LAYERS:
        assert layer_files(layer), f"solarscribe/{layer} has no .py file to check"


def test_layers_respect_the_dependency_rule():
    # One pass collects every violation, so a single run reports the whole mess
    # instead of failing on the first line.
    violations = []
    for layer in LAYERS:
        for path in layer_files(layer):
            # Sort with a key that tolerates the None layer: a file may import
            # both "solarscribe" (not a layer) and "solarscribe.devices", and
            # tuple ordering would compare None with a string.
            for root, imported_layer in sorted(
                imported_names(path), key=lambda item: (item[0], item[1] or "")
            ):
                if root != "solarscribe" or imported_layer is None:
                    continue
                if imported_layer == layer:
                    continue
                if imported_layer not in ALLOWED[layer]:
                    relative = path.relative_to(REPO_ROOT)
                    violations.append(
                        f"{relative}: solarscribe.{layer} imports "
                        f"solarscribe.{imported_layer}, which ARCHITECTURE.md 1 "
                        f"does not allow"
                    )
    assert not violations, "\n".join(violations)


def test_no_qt_outside_the_ui_layer():
    offenders = []
    for layer in NO_QT_LAYERS:
        for path in layer_files(layer):
            for root, _ in sorted(
                imported_names(path), key=lambda item: (item[0], item[1] or "")
            ):
                if root in QT_ROOTS:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: imports {root}")
    assert not offenders, (
        "Qt is presentation and belongs to ui alone:\n" + "\n".join(offenders)
    )


def test_no_driver_sdk_outside_the_devices_layer():
    offenders = []
    for layer in NO_DRIVER_LAYERS:
        for path in layer_files(layer):
            for root, _ in sorted(
                imported_names(path), key=lambda item: (item[0], item[1] or "")
            ):
                if root in DRIVER_ROOTS:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: imports {root}")
    assert not offenders, (
        "Only devices talks to the C SDKs (ADR-001):\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("module_name", sorted(CONTRACT_NAMES))
def test_contract_module_imports_and_keeps_its_surface(module_name):
    # Importing proves the module has no syntax or circular-import problem, and
    # the name table proves the contract did not shrink. A missing SDK or a
    # missing Qt must not be able to mask either: the contract modules import
    # numpy and the standard library only.
    module = importlib.import_module(module_name)
    missing = [name for name in CONTRACT_NAMES[module_name] if not hasattr(module, name)]
    assert not missing, f"{module_name} lost contract names: {missing}"

    # __all__ is the declared public surface: everything in it must exist, or an
    # agent will import a name that is not there.
    undeclared = [name for name in getattr(module, "__all__", ())
                  if not hasattr(module, name)]
    assert not undeclared, f"{module_name} declares names it does not define: {undeclared}"


@pytest.mark.parametrize("module_name,names", sorted(RUNTIME_PROTOCOLS.items()))
def test_protocols_are_runtime_checkable(module_name, names):
    # The simulators and the mocks assert isinstance(obj, Camera) and friends, so
    # the decorator is part of the contract, not a detail.
    module = importlib.import_module(module_name)
    for name in names:
        protocol = getattr(module, name)
        assert getattr(protocol, "_is_runtime_protocol", False), (
            f"{module_name}.{name} is not runtime_checkable"
        )


def test_capture_engine_satisfies_the_shg_frame_port():
    # The point of the ports (ADR-023): shg declares FrameSource and the capture
    # engine satisfies it structurally, so the two siblings never import each
    # other and the UI just hands one to the other.
    from solarscribe.capture.abc import CaptureEngine
    from solarscribe.shg.abc import FrameSource

    class StubEngine:
        # A stub with the surface of CaptureEngine and nothing else. isinstance
        # only checks that the names exist, which is exactly what the simulators
        # of the test suite rely on (ADR-005), so this proves the decorator and
        # the structural match at the same time.

        # @args: camera, roi, params - see CaptureEngine.configure
        def configure(self, camera, roi, params):
            pass

        # @args: none
        def start(self):
            pass

        # @args: none
        def stop(self):
            pass

        # @return: whether the stream runs
        def is_running(self):
            return False

        # @args: cb - the inline frame consumer
        def on_frame(self, cb):
            pass

        # @args: cb - the inline stats consumer
        def on_stats(self, cb):
            pass

        # @args: path, header - the SER file to open
        def start_recording(self, path, header):
            pass

        # @return: the accounting of the recording, None in the stub
        def stop_recording(self):
            return None

        # @return: whether a recording is open
        def is_recording(self):
            return False

        # @return: the live counters, None in the stub
        def counters(self):
            return None

    stub = StubEngine()
    assert isinstance(stub, CaptureEngine)
    assert isinstance(stub, FrameSource)


def test_value_types_build_with_their_defaults():
    # The value types travel between layers, so their defaults must work: a broken
    # default_factory or a wrong type would only show up in someone else's agent.
    from solarscribe.capture.abc import CaptureParams, RoiModel, SerHeader
    from solarscribe.config.schema import (
        SESSION_STEPS, Profile, SessionState, default_value,
    )
    from solarscribe.devices.abc import RoiConstraints
    from solarscribe.shg.abc import RowCounters, ScanConfig

    model = RoiModel(
        capture=(0, 0, 3480, 248),
        band=(0, 40, 3480, 160),
        constraints=RoiConstraints(max_width=3480, max_height=248),
    )
    model.set_tilt(0.4, 1.7)
    assert model.output() == model.capture      # output ROI == capture (ADR-010)
    assert (model.tilt_deg, model.tilt_px) == (0.4, 1.7)

    header = SerHeader(width=3480, height=248)
    assert header.bit_depth == 16               # the SER contract (ADR-018)

    assert CaptureParams().queue_budget_mb == 512.0     # ADR-013
    assert CaptureParams().stall_timeout_s == 3.0       # ADR-014

    config = ScanConfig(capture=(0, 0, 3480, 248), band=(0, 40, 3480, 160))
    assert config.cycles == 3                   # three cycles per session
    assert config.analysis == {}                # shg fills it, nobody else

    # The accounting shg writes into the ADR-018 logs starts at zero.
    counters = RowCounters()
    assert (counters.frames_written, counters.frames_dropped_sdk) == (0, 0)

    profile = Profile()
    assert profile.version == 2
    assert profile.preset("default") is not None
    assert profile.preset("nope") is None

    state = SessionState()
    assert set(state.steps) == set(SESSION_STEPS)
    assert default_value("roi", "capture_width") == 3480


def test_ini_schema_is_complete_and_explains_itself():
    # Every key has a default (ADR-003: a hand-edited file must still start the
    # app), a type its default matches, and a reason to show in the settings
    # dialog (AGENTS.md: no figure without an explanation).
    from solarscribe.config.schema import SCHEMA

    seen = set()
    for key in SCHEMA:
        assert (key.section, key.name) not in seen, f"duplicated key {key.section}.{key.name}"
        seen.add((key.section, key.name))
        assert key.why.strip(), f"{key.section}.{key.name} has no explanation"
        assert key.origin in ("scan", "new"), f"{key.section}.{key.name} has no origin"
        assert isinstance(key.default, key.kind), (
            f"{key.section}.{key.name} defaults to {key.default!r}, "
            f"not a {key.kind.__name__}"
        )

    # ADR-013's numbers are the budget, so the schema must not drift from them.
    from solarscribe.config.schema import default_value
    assert default_value("capture", "target_fps") == 120.0
    assert default_value("capture", "queue_budget_mb") == 512.0
    assert default_value("capture", "min_free_disk_gb") == 1.0
    assert default_value("roi", "capture_height") == 248


def test_schema_key_types_are_resolvable():
    # get_type_hints on the value types catches a forward reference that no
    # longer resolves, which a plain import would not notice.
    from solarscribe.capture.abc import RoiModel
    from solarscribe.config.schema import Profile
    from solarscribe.devices.abc import CameraInfo
    from solarscribe.shg.abc import ScanResult

    for value_type in (RoiModel, Profile, CameraInfo, ScanResult):
        assert is_dataclass(value_type)
        assert get_type_hints(value_type)
        assert fields(value_type)


# ---------------------------------------------------------------------------
# The rest of ARCHITECTURE 2, contract by contract.
#
# The tests above prove the modules exist and did not shrink. The ones below
# pin the parts of section 2 that are testable without an implementation: the
# method names and parameters of every Protocol, the fields and defaults of
# every value type, the fixed units and coordinate rules, the stable enum
# spellings and the reason-code convention. They are deliberately strict:
# changing any of them is an ADR-level event (ADR-012, ADR-023), not a refactor,
# and the failure message must say so.
# ---------------------------------------------------------------------------

# @args: module_name - a dotted contract module
# @return: the .py file that defines it, inside the package
def contract_module_path(module_name: str) -> Path:
    return PACKAGE_DIR.joinpath(*module_name.split(".")[1:]).with_suffix(".py")


# Protocol method names. A method that disappears or is renamed breaks every
# driver, simulator and mock that satisfies the Protocol structurally.
PROTOCOL_METHODS = {
    "solarscribe.devices.abc": {
        "Frame": ("stats", "cut_roi"),
        "Camera": (
            "open", "close", "is_open", "info", "get_roi", "set_roi",
            "effective_area", "get_param", "set_param", "param_range",
            "dropped_frames", "start_stream", "stop_stream",
        ),
        "Mount": (
            "connect", "close", "is_connected", "position", "move_axis",
            "stop", "slew", "sync", "set_tracking", "park", "unpark",
            "abort_slew", "status", "capabilities",
        ),
        "DeviceManager": (
            "backends", "cameras", "mounts", "open_camera", "open_mount",
        ),
    },
    "solarscribe.capture.abc": {
        "SerWriter": ("open", "write", "close", "counters"),
        "CaptureEngine": (
            "configure", "start", "stop", "is_running", "on_frame", "on_stats",
            "start_recording", "stop_recording", "is_recording", "counters",
        ),
    },
    "solarscribe.shg.abc": {
        "FrameSource": ("on_frame",),
        "RowRecorder": ("start_row", "stop_row"),
        "ScanEngine": ("plan", "prepare", "run", "pause", "resume", "abort"),
        "TiltMeter": ("measure",),
        "SunCenteringService": ("center",),
        "PolarAlignmentAssistant": ("add_sample", "result", "confirm"),
    },
}

# Parameter names of the methods the other layers call with keywords or with a
# documented order. The names are part of the contract: the UI and the engine
# agree on them, and a rename is a break even when the arity does not change.
PROTOCOL_SIGNATURES = {
    "solarscribe.devices.abc": {
        "Frame.cut_roi": ("roi",),
        "Camera.set_roi": ("roi",),
        "Camera.get_param": ("p",),
        "Camera.set_param": ("p", "value"),
        "Camera.param_range": ("p",),
        "Camera.start_stream": ("on_frame",),
        "Mount.move_axis": ("axis", "rate"),
        "Mount.slew": ("ra", "dec"),
        "Mount.sync": ("ra", "dec"),
        "Mount.set_tracking": ("on",),
        "DeviceManager.open_camera": ("camera_id",),
        "DeviceManager.open_mount": ("mount_id",),
    },
    "solarscribe.capture.abc": {
        "SerWriter.open": ("path", "header"),
        "SerWriter.write": ("frame",),
        "CaptureEngine.configure": ("camera", "roi", "params"),
        "CaptureEngine.on_frame": ("cb",),
        "CaptureEngine.on_stats": ("cb",),
        "CaptureEngine.start_recording": ("path", "header"),
    },
    "solarscribe.shg.abc": {
        "FrameSource.on_frame": ("cb",),
        "RowRecorder.start_row": ("path",),
        "RowRecorder.stop_row": (),
        "ScanEngine.plan": ("config",),
        "ScanEngine.prepare": ("cb",),
        "ScanEngine.run": ("plan", "cb", "recorder"),
        "TiltMeter.measure": ("frame", "band"),
        "SunCenteringService.center": ("cb",),
        "PolarAlignmentAssistant.add_sample": ("sample", "cb"),
        "PolarAlignmentAssistant.result": (),
        "PolarAlignmentAssistant.confirm": ("samples", "cb"),
    },
}

# Value types are frozen dataclasses: they travel between layers and everybody
# must agree on their fields (ADR-023 rule 1). The three mutable ones are the
# deliberate exceptions: the ROI model is edited by the ROI step, and the
# session state is edited by the step rail.
FROZEN_VALUE_TYPES = {
    "solarscribe.devices.abc": (
        "ParamRange", "RoiConstraints", "CameraCaps", "CameraInfo", "MountCaps",
        "MountStatus", "MountInfo", "BackendInfo",
    ),
    "solarscribe.capture.abc": (
        "CaptureParams", "SerHeader", "WriterCounters", "StreamCounters",
        "RoiWarning",
    ),
    "solarscribe.shg.abc": (
        "ScanRow", "ScanConfig", "ScanPlan", "PrepareStatus", "PrepareResult",
        "ScanProgress", "ScanResult", "RowCounters", "TiltResult",
        "CenteringStatus", "CenteringResult", "PolarSample", "PolarProgress",
        "PolarResult",
    ),
    "solarscribe.config.schema": (
        "Key", "TelescopeData", "CameraData", "RoiPreset", "Profile",
    ),
}
MUTABLE_VALUE_TYPES = {
    "solarscribe.capture.abc": ("RoiModel",),
    "solarscribe.config.schema": ("StepState", "SessionState"),
}

# Enums keep a stable spelling because `.value` is what the INI, the JSON and
# the logs persist (ADR-003, ADR-018). The whole set is pinned, so a typo in a
# saved file cannot silently become a new member.
STRING_ENUM_VALUES = {
    "solarscribe.devices.abc": {
        "Param": {
            "EXPOSURE": "exposure", "GAIN": "gain", "OFFSET": "offset",
            "BIT_DEPTH": "bit_depth", "BINNING": "binning", "READOUT": "readout",
            "TEMPERATURE": "temperature", "COOLER": "cooler",
        },
        "Axis": {"RA": "ra", "DEC": "dec"},
        "DeviceKind": {"CAMERA": "camera", "MOUNT": "mount"},
        "BackendReason": {
            "AVAILABLE": "available", "SDK_MISSING": "sdk_missing",
            "PLATFORM_MISSING": "platform_missing",
            "SERVER_MISSING": "server_missing", "OS_UNSUPPORTED": "os_unsupported",
            "ERROR": "error",
        },
    },
    "solarscribe.capture.abc": {
        "RoiIssue": {
            "BAND_CLIPPED": "band_clipped", "TILT_HEIGHT": "tilt_height",
            "SDK_MULTIPLE": "sdk_multiple", "SDK_BOUNDS": "sdk_bounds",
            "BINNING_MISMATCH": "binning_mismatch", "LOW_RATE": "low_rate",
            "SLIT_OFF_CENTRE": "slit_off_centre",
        },
        "Severity": {"INFO": "info", "WARNING": "warning", "ERROR": "error"},
    },
    "solarscribe.shg.abc": {
        "ScanMode": {"SIMPLE": "simple", "MOSAIC": "mosaic"},
        "DecCenterMethod": {"AUTO": "auto", "SYMMETRY": "symmetry", "CHORD": "chord"},
        "PreparePhase": {
            "FINE_CENTER": "fine_center", "CALIBRATE_RATE": "calibrate_rate",
        },
        "ScanState": {
            "RUNNING": "running", "PAUSED": "paused", "ABORTING": "aborting",
        },
        "ScanStatus": {
            "COMPLETED": "completed", "ABORTED": "aborted", "FAILED": "failed",
        },
    },
    "solarscribe.config.schema": {
        "StepStatus": {
            "PENDING": "pending", "CURRENT": "current", "DONE": "done",
            "SKIPPED": "skipped",
        },
    },
}

# The SER colour IDs are integers written raw into the header; the
# post-processing reads them (ADR-018), so these numbers are not ours to move.
SER_COLOR_IDS = {
    "MONO": 0, "BAYER_RGGB": 8, "BAYER_GRBG": 9, "BAYER_GBRG": 10,
    "BAYER_BGGR": 11, "RAW8": 102, "RAW16": 103,
}

# Numeric fields whose name carries its unit. ARCHITECTURE 2 fixes hours,
# degrees, arcseconds, seconds and microseconds; a field that loses its suffix
# is how the unit mix-ups start (the ROI bug, the exposure bug).
UNIT_BEARING_FIELDS = {
    "solarscribe.devices.abc": {
        "MountCaps": ("min_rate_arcsec_s", "max_rate_arcsec_s"),
    },
    "solarscribe.capture.abc": {
        "CaptureParams": ("exposure_us", "stall_timeout_s"),
        "WriterCounters": ("queue_high_water_mb",),
        "StreamCounters": ("disk_mb_s",),
        "RoiModel": ("tilt_deg", "tilt_px"),
    },
    "solarscribe.shg.abc": {
        "ScanRow": ("dec_offset_arcsec", "ra_start_hours", "ra_end_hours",
                    "duration_s"),
        "ScanConfig": ("rate_arcsec_s", "row_step_arcsec", "padding_s",
                       "preload_s", "tilt_deg", "tilt_px"),
        "ScanProgress": ("ra_hours", "dec_deg", "dec_error_arcsec", "elapsed_s"),
        "ScanResult": ("duration_s", "rate_arcsec_s", "dec_error_arcsec"),
        "CenteringStatus": ("dec_offset_arcsec",),
        "CenteringResult": ("dec_offset_arcsec", "dead_zone_arcsec"),
        "PolarSample": ("time_s", "hour_angle_deg", "dec_deg",
                        "dec_ephemeris_deg", "altitude_deg", "azimuth_deg"),
        "PolarProgress": ("hour_angle_deg", "elapsed_s"),
        "PolarResult": ("azimuth_error_arcsec", "altitude_error_arcsec",
                        "drift_rate_arcsec_min", "residual_arcsec"),
    },
}

# ARCHITECTURE 2 / ADR-023: a contract module holds no algorithm. Behaviour is
# declared as a Protocol (stub bodies only); the few concrete functions allowed
# here are the tiny accessors whose types live in the module and whose bodies
# are data plumbing, not logic.
CONTRACT_ALGORITHMS = {
    "solarscribe.devices.abc": frozenset({"DeviceError.__init__"}),
    "solarscribe.capture.abc": frozenset({"RoiModel.output", "RoiModel.set_tilt"}),
    "solarscribe.shg.abc": frozenset(),
    "solarscribe.config.schema": frozenset(
        {"Profile.preset", "new_steps", "keys_of", "default_value"}
    ),
}


# @args: node - a function definition
# @return: whether its body is a Protocol stub: nothing but `...`, optionally
#          preceded by a docstring
def _is_stub(node: ast.AST) -> bool:
    body = list(getattr(node, "body", ()))
    if body and isinstance(body[0], ast.Expr) and isinstance(
        body[0].value, ast.Constant
    ) and isinstance(body[0].value.value, str):
        body = body[1:]
    return len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(
        body[0].value, ast.Constant
    ) and body[0].value.value is Ellipsis


# @args: tree - a parsed module
# @return: every (qualified name, node) of the functions defined in it, with the
#          class name as prefix for methods
def _function_defs(tree: ast.AST):
    def walk(node: ast.AST, prefix: str):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield prefix + child.name, child
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, prefix + child.name + ".")

    yield from walk(tree, "")


@pytest.mark.parametrize("module_name", sorted(PROTOCOL_METHODS))
def test_protocols_declare_every_required_method(module_name):
    # The method table is the surface every simulator, mock and driver codes
    # against. A missing method is a structural break even when the module
    # still imports, so it must fail here instead of in someone else's layer.
    module = importlib.import_module(module_name)
    for protocol_name, methods in PROTOCOL_METHODS[module_name].items():
        protocol = getattr(module, protocol_name)
        missing = [name for name in methods if not callable(getattr(protocol, name, None))]
        assert not missing, f"{module_name}.{protocol_name} lost methods: {missing}"

        # A Protocol must not smuggle in an implementation: only the declared
        # methods, each with a stub body.
        extra = [
            name for name in dir(protocol)
            if not name.startswith("_") and callable(getattr(protocol, name, None))
            and name not in methods
        ]
        assert not extra, (
            f"{module_name}.{protocol_name} declares methods outside the "
            f"contract table: {extra}"
        )


@pytest.mark.parametrize("module_name", sorted(PROTOCOL_SIGNATURES))
def test_protocol_method_parameters_are_stable(module_name):
    module = importlib.import_module(module_name)
    for dotted, expected in PROTOCOL_SIGNATURES[module_name].items():
        owner_name, method_name = dotted.split(".")
        method = getattr(getattr(module, owner_name), method_name)
        params = [
            p.name for p in inspect.signature(method).parameters.values()
            if p.name != "self"
            and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
        ]
        assert tuple(params) == expected, (
            f"{module_name}.{dotted} takes {tuple(params)}, contract says "
            f"{expected}: this is an ADR-012 change, not a refactor"
        )


def test_scan_engine_dry_run_is_a_none_recorder():
    # run(plan, cb, recorder=None) is the dry mode of DESIGN.md 14: a missing
    # recorder must mean "do not write files", never "use some default writer".
    from solarscribe.shg.abc import ScanEngine

    recorder = inspect.signature(ScanEngine.run).parameters["recorder"]
    assert recorder.default is None


@pytest.mark.parametrize("module_name", sorted(FROZEN_VALUE_TYPES))
def test_cross_layer_value_types_are_frozen(module_name):
    module = importlib.import_module(module_name)
    for name in FROZEN_VALUE_TYPES[module_name]:
        value_type = getattr(module, name)
        assert is_dataclass(value_type), f"{module_name}.{name} is not a dataclass"
        assert value_type.__dataclass_params__.frozen, (
            f"{module_name}.{name} must be frozen: it travels between layers "
            f"and nobody owns a private copy (ADR-023)"
        )
        assert fields(value_type), f"{module_name}.{name} has no fields"


@pytest.mark.parametrize("module_name", sorted(MUTABLE_VALUE_TYPES))
def test_deliberately_editable_value_types_are_not_frozen(module_name):
    module = importlib.import_module(module_name)
    for name in MUTABLE_VALUE_TYPES[module_name]:
        value_type = getattr(module, name)
        assert is_dataclass(value_type)
        assert not value_type.__dataclass_params__.frozen, (
            f"{module_name}.{name} is edited in place by the UI step that owns it"
        )


@pytest.mark.parametrize("module_name", sorted(FROZEN_VALUE_TYPES))
def test_value_type_hints_all_resolve(module_name):
    # A forward reference that no longer resolves is invisible to a plain
    # import and explodes later, in the layer that first builds the type.
    module = importlib.import_module(module_name)
    for name in FROZEN_VALUE_TYPES[module_name] + MUTABLE_VALUE_TYPES.get(module_name, ()):
        assert get_type_hints(getattr(module, name))


@pytest.mark.parametrize("module_name", sorted(STRING_ENUM_VALUES))
def test_persisted_enum_spellings_are_stable(module_name):
    module = importlib.import_module(module_name)
    for enum_name, expected in STRING_ENUM_VALUES[module_name].items():
        enum_type = getattr(module, enum_name)
        assert issubclass(enum_type, Enum)
        assert {member.name: member.value for member in enum_type} == expected, (
            f"{module_name}.{enum_name} changed its persisted spellings"
        )
        for value in expected.values():
            # The UI translates reason codes, so they are snake_case keys, not
            # sentences (ADR-014, ADR-016).
            assert re.fullmatch(r"[a-z][a-z0-9_]*", value), (
                f"{module_name}.{enum_name} value {value!r} is not snake_case"
            )


def test_ser_colour_ids_are_the_standard_numbers():
    # These integers go raw into the SER header (ADR-018). A moved value breaks
    # JSol'Ex and every post-processing tool without any Python error.
    from solarscribe.capture.abc import SerColorId

    assert {member.name: int(member) for member in SerColorId} == SER_COLOR_IDS


@pytest.mark.parametrize("module_name", sorted(UNIT_BEARING_FIELDS))
def test_numeric_fields_name_their_unit(module_name):
    # ARCHITECTURE 2 fixes the units once: hours, degrees, arcseconds, seconds
    # and microseconds. The suffix in the field name is the only thing that
    # tells them apart at a call site, so it is part of the contract.
    module = importlib.import_module(module_name)
    for name, expected in UNIT_BEARING_FIELDS[module_name].items():
        value_type = getattr(module, name)
        actual = {item.name for item in fields(value_type)}
        missing = [field for field in expected if field not in actual]
        assert not missing, f"{module_name}.{name} lost unit-bearing fields: {missing}"


@pytest.mark.parametrize("module_name", sorted(CONTRACT_ALGORITHMS))
def test_contract_modules_hold_no_algorithm(module_name):
    # ADR-023: a contract module declares types; it never computes. Protocols
    # have stub bodies, and the allowlist contains only the tiny accessors that
    # pair with a type declared in the same module. A real function appearing
    # here means the algorithm is in the wrong layer.
    tree = ast.parse(
        contract_module_path(module_name).read_text(encoding="utf-8"),
        filename=module_name,
    )
    allowed = CONTRACT_ALGORITHMS[module_name]
    offenders = [
        qualname for qualname, node in _function_defs(tree)
        if qualname not in allowed and not _is_stub(node)
    ]
    assert not offenders, (
        f"{module_name} contains algorithm bodies outside the allowlist: "
        f"{offenders}. The validation and the reading/writing live in the "
        f"layer's modules (ADR-023)"
    )


def test_device_value_defaults_encode_sensor_facts():
    from solarscribe.devices.abc import (
        BackendInfo, BackendReason, CameraCaps, DeviceKind, MountCaps,
        MountStatus, ParamRange, RoiConstraints,
    )

    interval = ParamRange(minimum=0.0, maximum=100.0)
    assert interval.step == 0.0          # 0.0: continuous, not discrete

    limits = RoiConstraints(max_width=3480, max_height=248)
    assert (limits.min_width, limits.min_height) == (1, 1)
    assert (limits.width_multiple, limits.height_multiple, limits.offset_multiple) == (
        1, 1, 1
    )

    caps = CameraCaps(roi=limits)
    assert caps.is_color is False        # mono is the SHG case
    assert caps.bit_depths == (16,)      # the SER contract
    assert caps.binnings == (1,)
    assert (caps.has_cooler, caps.reports_temperature) == (False, False)

    mount = MountCaps()
    assert not any((mount.supports_axis_rates, mount.can_slew, mount.can_sync,
                    mount.can_track, mount.can_park, mount.can_abort,
                    mount.reports_position_while_moving))
    assert (mount.min_rate_arcsec_s, mount.max_rate_arcsec_s) == (0.0, 0.0)

    status = MountStatus()
    assert (status.tracking, status.slewing, status.parked) == (False, False, False)

    backend = BackendInfo(name="sim", kind=DeviceKind.CAMERA, available=True)
    assert backend.reason is BackendReason.AVAILABLE
    assert backend.detail == ""


def test_capture_value_defaults_encode_the_stream_budget():
    from solarscribe.capture.abc import (
        CaptureParams, RoiIssue, RoiWarning, SerColorId, SerHeader, Severity,
        StreamCounters, WriterCounters,
    )

    params = CaptureParams()
    assert params.exposure_us == 1000.0          # microseconds, Param's unit
    assert params.bit_depth == 16                # SER contract (ADR-018)
    assert params.exposure_us == 1000.0
    assert 0.0 < params.auto_exposure_target < 1.0
    assert params.auto_exposure_target == 0.25
    assert params.queue_budget_mb == 512.0       # ADR-013
    assert params.stall_timeout_s == 3.0         # ADR-014

    header = SerHeader(width=3480, height=248)
    assert header.bit_depth == 16
    assert header.color_id is SerColorId.MONO
    assert header.little_endian is True
    # roi is metadata for session_meta.json, not a SER field: empty until the
    # driver knows the sensor region (ARCHITECTURE 2.2).
    assert header.roi == (0, 0, 0, 0)

    written = WriterCounters()
    assert (written.frames_written, written.frames_dropped_queue) == (0, 0)
    assert written.queue_high_water_mb == 0.0

    stream = StreamCounters()
    assert stream.frames_received == 0
    assert stream.frames_dropped_sdk == 0
    assert stream.sequence_gaps == 0
    assert (stream.fps, stream.disk_mb_s) == (0.0, 0.0)

    warning = RoiWarning(issue=RoiIssue.SDK_BOUNDS, severity=Severity.ERROR)
    assert warning.args == {}
    # A warning carries a code and numbers, never a sentence (ADR-016).
    assert "message" not in {item.name for item in fields(RoiWarning)}
    assert "text" not in {item.name for item in fields(RoiWarning)}


def test_shg_value_defaults_encode_the_scan_contract():
    from solarscribe.shg.abc import (
        DecCenterMethod, PrepareResult, RowCounters, ScanConfig, ScanMode,
        ScanResult, ScanStatus, TiltResult,
    )

    config = ScanConfig(capture=(0, 0, 3480, 248), band=(0, 40, 3480, 160))
    assert config.analysis == {}                 # shg fills it, nobody else
    assert config.mode is ScanMode.SIMPLE
    assert config.cycles == 3                    # three cycles per session
    assert config.rate_arcsec_s == 0.0           # 0.0: calibrate in prepare()
    assert config.dec_center is DecCenterMethod.AUTO
    assert config.rows == 1
    assert config.row_step_arcsec == 0.0         # one slit height per row
    assert config.padding_s == 1.0
    assert config.preload_s == 1.0
    assert config.adaptive_stop is True
    assert (config.tilt_deg, config.tilt_px) == (0.0, 0.0)

    # Every instance gets its own analysis map: a shared mutable default would
    # leak one scan's regions into the next one.
    other = ScanConfig(capture=(0, 0, 3480, 248), band=(0, 40, 3480, 160))
    config.analysis["left"] = (0, 0, 10, 10)
    assert other.analysis == {}

    counters = RowCounters()
    assert (counters.frames_written, counters.frames_dropped_queue,
            counters.frames_dropped_sdk, counters.sequence_gaps) == (0, 0, 0, 0)
    assert counters.queue_high_water_mb == 0.0

    prepared = PrepareResult(
        ok=True, dec_offset_arcsec=0.0, rate_arcsec_s=13.0,
        method=DecCenterMethod.AUTO,
    )
    assert prepared.reason_code == ""            # empty when it went well

    result = ScanResult(
        status=ScanStatus.COMPLETED, frames_written=0, frames_dropped=0,
        duration_s=0.0, rate_arcsec_s=0.0, rows_completed=0,
        dec_error_arcsec=0.0,
    )
    assert result.ser_paths == ()
    assert result.reason_code == ""

    tilt = TiltResult(ok=True)
    assert (tilt.tilt_deg, tilt.tilt_px, tilt.edge_std_px) == (0.0, 0.0, 0.0)
    assert tilt.reason_code == ""


def test_config_schema_is_the_contract_of_files_steps_and_optics():
    from solarscribe.config.schema import (
        CONFIG_FILE, PROFILE_FILE, PROFILE_VERSION, SESSION_STATE_FILE,
        SESSION_STEPS, CameraData, Profile, RoiPreset, SCHEMA, SessionState,
        StepState, StepStatus, TelescopeData, default_value, keys_of, new_steps,
    )

    # File names are fixed here, never directories (ADR-003).
    assert CONFIG_FILE == "config.ini"
    assert PROFILE_FILE == "profile.json"
    assert SESSION_STATE_FILE == "session_state.json"
    assert PROFILE_VERSION == 2

    # The rail order is the order the UI paints and the JSON persists.
    assert SESSION_STEPS == ("find_sun", "polar", "roi", "scan")
    assert {member.value for member in StepStatus} == {
        "pending", "current", "done", "skipped"
    }

    # The MVP sections of ARCHITECTURE 3.2.
    sections = {key.section for key in SCHEMA}
    assert {
        "general", "observatory", "camera", "roi", "mount", "scan", "capture",
        "session", "polar",
    } <= sections

    assert keys_of("roi")
    assert all(key.section == "roi" for key in keys_of("roi"))
    assert keys_of("no_such_section") == ()
    with pytest.raises(KeyError):
        default_value("roi", "no_such_key")

    # A fresh step map is independent per SessionState (autosave rewrites one).
    first = new_steps()
    second = new_steps()
    first["roi"].status = StepStatus.DONE
    assert second["roi"].status is StepStatus.PENDING
    assert all(isinstance(step, StepState) for step in first.values())

    state = SessionState()
    assert set(state.steps) == set(SESSION_STEPS)
    assert (state.session_dir, state.created_at, state.updated_at) == ("", "", "")
    state.steps["roi"].metrics["tilt_deg"] = 0.4
    assert SessionState().steps["roi"].metrics == {}

    optics = TelescopeData()
    assert (optics.focal_length_mm, optics.aperture_mm, optics.slit_length_mm) == (
        714.0, 80.0, 7.0
    )
    # The slit geometry: 7 mm at 714 mm subtends 7/714 rad = 33.7', just over
    # the 32' solar diameter, which is why one row can cover the whole disk.
    import math
    assert 33.0 < math.degrees(7.0 / 714.0) * 60.0 < 34.5

    camera = CameraData()
    assert (camera.pixel_size_um, camera.binning) == (2.0, 1)

    preset = RoiPreset()
    assert preset.name == "default"
    assert preset.capture == (0, 0, 3480, 248)
    assert preset.band == (0, 40, 3480, 160)

    profile = Profile()
    assert profile.version == PROFILE_VERSION
    assert profile.preset("default") == preset
    assert profile.preset("no_such_preset") is None


def test_roi_coordinates_never_mix_sensor_and_frame_space():
    # ARCHITECTURE 2 fixes two coordinate systems and calls the mix-up the
    # classic ROI bug: capture is SENSOR pixels (binned), band and the analysis
    # regions are FRAME pixels, and the output ROI is always capture.
    from typing import get_args as typing_args

    from solarscribe.capture.abc import RoiModel
    from solarscribe.config.schema import RoiPreset, default_value
    from solarscribe.devices.abc import RoiConstraints, ROI

    assert typing_args(ROI) == (int, int, int, int), "ROI is (x, y, width, height)"

    model = RoiModel(
        capture=(120, 60, 3480, 248),
        band=(0, 40, 3480, 160),
        constraints=RoiConstraints(max_width=3480, max_height=248),
    )
    # The two rectangles live in different spaces, so a difference is expected
    # and the output is the sensor one.
    assert model.output() == (120, 60, 3480, 248)
    assert model.output() == model.capture
    assert model.capture != model.band

    # The profile and the INI persist the same two rectangles with the same
    # convention, so converting a preset into a model does no arithmetic.
    preset = RoiPreset(capture=model.capture, band=model.band)
    assert preset.capture == model.capture
    assert preset.band == model.band

    ini_capture = tuple(
        default_value("roi", f"capture_{name}") for name in ("x", "y", "width", "height")
    )
    ini_band = tuple(
        default_value("roi", f"band_{name}") for name in ("x", "y", "width", "height")
    )
    assert ini_capture == RoiPreset().capture
    assert ini_band == RoiPreset().band


def test_roi_model_is_editable_and_the_output_is_the_capture_region():
    from solarscribe.capture.abc import RoiModel
    from solarscribe.devices.abc import RoiConstraints

    model = RoiModel(
        capture=(0, 0, 3480, 248), band=(0, 40, 3480, 160),
        constraints=RoiConstraints(max_width=3480, max_height=248),
    )
    assert model.binning == 1
    assert (model.tilt_deg, model.tilt_px) == (0.0, 0.0)

    model.set_tilt(0.42, 1.7)
    assert (model.tilt_deg, model.tilt_px) == (0.42, 1.7)
    # Setting the tilt never moves the output ROI: it changes the geometry, not
    # what is written to the SER (ADR-010).
    assert model.output() == (0, 0, 3480, 248)


def test_failures_carry_codes_and_numbers_not_sentences():
    from solarscribe.capture.abc import RoiIssue, RoiWarning, Severity
    from solarscribe.devices.abc import DeviceError
    from solarscribe.shg.abc import (
        DecCenterMethod, PrepareResult, ScanResult, ScanStatus, TiltResult,
    )

    error = DeviceError("the SDK refused the ROI")
    assert isinstance(error, RuntimeError)
    assert error.code == "error"                 # the stable fallback key
    assert error.device_id == ""
    assert re.fullmatch(r"[a-z][a-z0-9_]*", error.code)

    tagged = DeviceError("gone", code="roi_rejected", device_id="sim:0")
    assert (tagged.code, tagged.device_id) == ("roi_rejected", "sim:0")

    # A warning is a code plus the numbers that justify it, so the UI can build
    # the sentence in the observer's language (ADR-016).
    warning = RoiWarning(
        issue=RoiIssue.TILT_HEIGHT, severity=Severity.WARNING,
        args={"band_height": 160, "tilt_px": 4},
    )
    assert warning.args["tilt_px"] == 4

    for result in (
        PrepareResult(ok=False, dec_offset_arcsec=12.0, rate_arcsec_s=0.0,
                      method=DecCenterMethod.CHORD, reason_code="no_limb"),
        ScanResult(status=ScanStatus.ABORTED, frames_written=10,
                   frames_dropped=0, duration_s=1.0, rate_arcsec_s=13.0,
                   rows_completed=0, dec_error_arcsec=0.0,
                   reason_code="sun_lost"),
        TiltResult(ok=False, reason_code="no_edge"),
    ):
        # The MVP reason-code vocabulary is snake_case, like every enum the UI
        # translates (ARCHITECTURE 2.3).
        assert re.fullmatch(r"[a-z][a-z0-9_]*", result.reason_code)


# ---------------------------------------------------------------------------
# The boundary functions ARCHITECTURE 2 names, now that the layer modules that
# implement them exist. The contract modules declare the shapes; these tests
# check that the implementations keep the documented units, reserved keys and
# severity rules.
# ---------------------------------------------------------------------------


def test_analysis_regions_use_the_reserved_keys_and_frame_pixels():
    # ARCHITECTURE 2.3: "left" and "right" are the halves used by the Dec
    # centring and "limb" is the strip where the limb is detected. The columns
    # inside "limb" are not contract, so only the three keys are pinned.
    from solarscribe.shg.abc import ANALYSIS_KEYS
    from solarscribe.shg.analysis import analysis_regions

    assert ANALYSIS_KEYS == ("left", "right", "limb")

    capture = (0, 0, 3480, 248)      # SENSOR pixels; its size is the frame
    band = (10, 40, 1000, 160)       # FRAME pixels, inside the frame
    regions = analysis_regions(capture, band)

    assert set(regions) == set(ANALYSIS_KEYS)
    assert regions["limb"] == band

    left, right = regions["left"], regions["right"]
    assert left[1] == right[1] == band[1] == 40
    assert left[3] == right[3] == band[3] == 160
    assert left[0] == band[0]
    assert left[2] + right[2] == band[2]      # the two halves cover the band
    assert left[0] + left[2] == right[0]

    # Every region is in frame pixels, so it must stay inside the frame the
    # capture ROI defines; a region that escapes would make numpy read garbage.
    for roi in regions.values():
        x, y, width, height = roi
        assert 0 <= x and 0 <= y
        assert x + width <= capture[2]
        assert y + height <= capture[3]


def test_roi_validation_returns_codes_and_severities():
    # ADR-010: a code plus the numbers, never a sentence. ERROR means the ROI
    # cannot be scanned; WARNING and INFO are recommendations (ADR-011).
    from solarscribe.capture.abc import RoiIssue, RoiModel, RoiWarning, Severity
    from solarscribe.capture.roi import validate_roi
    from solarscribe.devices.abc import RoiConstraints

    limits = RoiConstraints(max_width=3480, max_height=248)
    clean = RoiModel(
        capture=(0, 0, 3480, 248), band=(0, 40, 3480, 160),
        constraints=limits,
    )
    assert validate_roi(clean) == []

    # The band leaves the frame: clipped, but only a recommendation.
    clipped = RoiModel(
        capture=(0, 0, 3480, 248), band=(0, 200, 3480, 160),
        constraints=limits,
    )
    findings = validate_roi(clipped)
    clipped_finding = next(w for w in findings if w.issue is RoiIssue.BAND_CLIPPED)
    assert clipped_finding.severity is Severity.WARNING

    # The tilt drift does not fit above the band: this one cannot be scanned.
    tilted = RoiModel(
        capture=(0, 0, 3480, 248), band=(0, 40, 3480, 160),
        constraints=limits, tilt_px=100.0,
    )
    tilt_finding = next(
        w for w in validate_roi(tilted) if w.issue is RoiIssue.TILT_HEIGHT
    )
    assert tilt_finding.severity is Severity.ERROR
    assert tilt_finding.args["needed"] > tilt_finding.args["capture_height"]

    # An off-multiple offset is an SDK rejection, so it is an ERROR.
    misaligned = RoiModel(
        capture=(1, 0, 3480, 248), band=(0, 40, 3480, 160),
        constraints=RoiConstraints(max_width=3480, max_height=248,
                                   offset_multiple=2),
    )
    issues = {w.issue for w in validate_roi(misaligned)}
    assert RoiIssue.SDK_MULTIPLE in issues

    # A rate below the ADR-013 target is a warning, not a gate.
    slow = next(
        w for w in validate_roi(clean, fps=60.0) if w.issue is RoiIssue.LOW_RATE
    )
    assert slow.severity is Severity.WARNING
    assert slow.args["target_fps"] == 120.0

    # Whatever the finding, it is a code and a numeric bag, never a phrase.
    for warning in validate_roi(tilted):
        assert isinstance(warning, RoiWarning)
        assert isinstance(warning.issue, RoiIssue)
        assert all(isinstance(value, (int, float)) for value in warning.args.values())


def test_preset_and_model_round_trip_without_touching_coordinates():
    # ARCHITECTURE 2.2: preset_to_model/model_to_preset are conversions, not
    # arithmetic. capture stays in SENSOR pixels and band in FRAME pixels.
    from solarscribe.capture.roi import model_to_preset, preset_to_model
    from solarscribe.config.schema import RoiPreset
    from solarscribe.devices.abc import RoiConstraints

    preset = RoiPreset(
        name="shg700", capture=(8, 4, 3480, 248), band=(0, 40, 3480, 160)
    )
    model = preset_to_model(
        preset, RoiConstraints(max_width=3480, max_height=248), binning=2,
        tilt_deg=0.3, tilt_px=2.0,
    )
    assert model.capture == preset.capture
    assert model.band == preset.band
    assert model.binning == 2
    assert (model.tilt_deg, model.tilt_px) == (0.3, 2.0)

    back = model_to_preset(model, name="shg700")
    assert back.capture == preset.capture
    assert back.band == preset.band
    assert back.name == "shg700"


def test_scan_engine_is_built_from_the_mount_and_the_frame_port():
    # ARCHITECTURE 2.3 makes the construction part of the contract:
    # ScanEngineImpl(mount, frames), built once per session by the UI.
    from solarscribe.shg.engine import ScanEngineImpl

    parameters = [
        parameter.name
        for parameter in inspect.signature(ScanEngineImpl).parameters.values()
    ]
    assert parameters[:2] == ["mount", "frames"]
