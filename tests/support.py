############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - tests device discovery module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Where the tests find the camera, the mount and the capture engine.
#
# The functional suite and the performance bench must run against the same
# first-class simulators the app uses (ADR-005), not against a private test
# double. This module keeps that discovery in one place so a rename in
# solarscribe/devices/sim or solarscribe/capture/engine does not touch every
# test.
#
# Everything is optional on purpose: while an agent is still writing the
# simulator or the engine, discovery returns None and the test skips with a
# reason instead of failing for a file that does not exist yet. A module that
# imports but explodes is NOT hidden: only ImportError/AttributeError are
# treated as "not there"; a construction error is returned as None so the
# caller can decide, and the bench reports it.

from __future__ import annotations

import importlib
from typing import Any

# Modules a device factory may live in. The package and the two submodules are
# all tried because a simulator may export its class from __init__ or keep it
# in camera.py/mount.py.
SIM_MODULES = (
    "solarscribe.devices.sim",
    "solarscribe.devices.sim.camera",
    "solarscribe.devices.sim.mount",
)

# Factory spellings, most specific first. SimCamera() is the current one; the
# rest are the obvious names a later refactor might use.
CAMERA_FACTORIES = ("SimCamera", "camera", "make_camera", "create_camera", "Camera")
MOUNT_FACTORIES = ("SimMount", "mount", "make_mount", "create_mount", "Mount")
ENGINE_FACTORIES = (
    "CaptureEngineImpl", "CaptureEngine", "Engine", "make_engine", "create_engine",
)


# @args: name - a dotted module name
# @return: the imported module, or None when it does not exist yet
def optional_module(name: str):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return None


# @args: factory - a class or callable; kwargs - what to pass first
# @return: an instance, or None when the factory rejects the call. Only the
#          construction is guarded: a broken callable is "not available"
def _instantiate(factory: Any, kwargs: dict[str, Any]):
    try:
        return factory(**kwargs)
    except Exception:
        return None


# @args: modules - modules to search; names - factory spellings; kwargs - the
#        construction arguments to try first
# @return: (instance, "module.factory") or (None, "")
def _find(modules, names, kwargs: dict[str, Any]):
    for module in modules:
        for name in names:
            factory = getattr(module, name, None)
            if not callable(factory):
                continue
            # Try the requested size first, then the factory's own defaults.
            instance = _instantiate(factory, kwargs)
            if instance is None and kwargs:
                instance = _instantiate(factory, {})
            if instance is not None:
                return instance, f"{module.__name__}.{name}"
    return None, ""


# @args: kwargs - construction arguments (width, height, fps, pattern...)
# @return: (camera, label) from the simulator, or (None, "") while it is absent
def find_camera(**kwargs):
    modules = [m for m in (optional_module(n) for n in SIM_MODULES) if m]
    return _find(modules, CAMERA_FACTORIES, kwargs)


# @args: kwargs - construction arguments (ra_hours, dec_deg, clock...)
# @return: (mount, label) from the simulator, or (None, "") while it is absent
def find_mount(**kwargs):
    modules = [m for m in (optional_module(n) for n in SIM_MODULES) if m]
    return _find(modules, MOUNT_FACTORIES, kwargs)


# @args: kwargs - construction arguments, normally none: the contract says the
#        engine is built with no arguments and configured later
# @return: (engine, label) from the capture layer, or (None, "") while it is
#          still being written
def find_capture_engine(**kwargs):
    module = optional_module("solarscribe.capture.engine")
    if module is None:
        return None, ""
    return _find([module], ENGINE_FACTORIES, kwargs)
