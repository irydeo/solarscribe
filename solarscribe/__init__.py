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

# Version fallback: the real one comes from setuptools-scm at build time.
__version__ = "0.0.0"
