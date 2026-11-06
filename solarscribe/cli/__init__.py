############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - cli layer init module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""cli: startup, dry run and device diagnostics.

The package entry point is solarscribe.__main__. It gives every argument to
ui.app.run, which dispatches the two headless modes here. Nothing in this layer
imports Qt: it must work over SSH and in CI.
"""

from .main import diagnostics, dry_run, run

__all__ = ["diagnostics", "dry_run", "run"]
