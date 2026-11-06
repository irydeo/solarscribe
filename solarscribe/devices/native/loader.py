############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native loader module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Dynamic SDK loading (ADR-001, ADR-014).
#
# A missing SDK library is not an error: it simply means the backend does not
# appear and the app carries on with the others. That is why every load is
# wrapped in OSError here and why the caller gets None instead of an exception.
#
# Order matters. First the exact names the vendor ships (the .dll next to the
# executable on Windows, libtoupcam.so on Linux); then ctypes.util.find_library,
# which searches the system loader path (udev-installed SDKs and distro
# packages). Loading by name first lets a user drop a newer SDK next to the app
# without touching the system.

from __future__ import annotations

import ctypes
import ctypes.util
from collections.abc import Iterable

__all__ = ["library_available", "load_library"]


# @args: names - vendor file names, most specific first
# @return: the loaded CDLL, or None when none of the candidates is present
def load_library(names: Iterable[str]) -> ctypes.CDLL | None:
    candidates = tuple(names)
    for name in candidates:
        try:
            return ctypes.CDLL(name)
        except OSError:
            # Not next to the app: try the system search path below.
            continue
    for name in candidates:
        # find_library wants the bare name ("toupcam"), not "libtoupcam.so".
        bare = name
        for prefix in ("lib",):
            if bare.startswith(prefix):
                bare = bare[len(prefix):]
        for suffix in (".so", ".dylib", ".dll"):
            if bare.endswith(suffix):
                bare = bare[: -len(suffix)]
        found = ctypes.util.find_library(bare)
        if not found:
            continue
        try:
            return ctypes.CDLL(found)
        except OSError:
            continue
    return None


# @args: names - vendor file names
# @return: whether the library can be loaded right now
def library_available(names: Iterable[str]) -> bool:
    return load_library(names) is not None
