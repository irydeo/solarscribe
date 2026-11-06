############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - package init module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""SolarScribe: capture application for a solar spectroheliograph (SHG).

The package is split into layers (see the contracts): devices, capture, shg, ui
and cli. ui/cli depend on capture/shg; capture/shg depend on devices; devices
depends on nothing from the application.
"""

from importlib.metadata import PackageNotFoundError, version as _dist_version

# The real version is written into the dist-info by setuptools-scm at build
# time (pyproject.toml, ADR-017). Reading it here keeps one source of truth:
# the installers, the wheel and session_meta.json all see the same string.
# A bare source tree has no dist-info, so that case keeps the explicit
# fallback and `import solarscribe` still works. This is a read-only metadata
# lookup: no files are created and nothing outside the package is touched.
try:
    __version__ = _dist_version("solarscribe")
except PackageNotFoundError:
    __version__ = "0.0.0"
