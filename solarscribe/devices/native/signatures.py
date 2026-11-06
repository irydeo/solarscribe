############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native signatures module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# ctypes signatures for the vendor SDKs (ADR-001, ADR-002).
#
# Why this module exists, with the failure it prevents: ctypes assumes every
# function returns a 32-bit int unless restype is set. Every one of these SDKs
# returns a 64-bit opaque handle from its Open call. On a 64-bit machine the
# default restype truncates that pointer, and the next call with the truncated
# value segfaults the interpreter with no Python traceback and no log line. The
# same applies to output parameters (a missing argtypes makes ctypes pass a
# Python int where the SDK expects a pointer) and to structs (a wrong layout is
# a heap overflow the moment the SDK fills an array).
#
# So each wrapper declares one table: symbol -> (restype, argtypes). The table
# is applied to the loaded library before the first call and the unit suite
# walks the wrapper source to fail if a call appears without its entry. A
# symbol the installed SDK lacks is skipped on purpose: optional calls that are
# probed with hasattr (PullImageV4 versus PullImage) must not stop the driver.

from __future__ import annotations

import ctypes

__all__ = ["apply_signatures"]


# @args: library - loaded ctypes.CDLL or a test double with the same names
#        table - {symbol: (restype, [argtypes])}
# @return: the symbols that were actually configured
def apply_signatures(library, table) -> set[str]:
    configured: set[str] = set()
    for symbol, (restype, argtypes) in table.items():
        function = getattr(library, symbol, None)
        if function is None:
            continue
        try:
            function.restype = restype
            function.argtypes = list(argtypes)
        except (AttributeError, TypeError):
            # A unit-test double may expose a bound method, which refuses new
            # attributes. The real CDLL function always accepts them; the
            # AST test proves the table covers every symbol we call.
            continue
        configured.add(symbol)
    return configured
