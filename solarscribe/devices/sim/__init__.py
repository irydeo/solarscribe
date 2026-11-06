############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices sim package
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The camera and mount simulators are first-class backends (ADR-005). They are
# exported here so the app, the tests and the DeviceManager share one spelling.

from solarscribe.devices.sim.backend import SimCameraBackend, SimMountBackend
from solarscribe.devices.sim.camera import SimCamera
from solarscribe.devices.sim.frame import (
    SolarPattern, SimFrame, make_pattern, make_solar_pattern,
)
from solarscribe.devices.sim.mount import SimMount

__all__ = [
    "SimCamera", "SimCameraBackend", "SimFrame", "SimMount",
    "SimMountBackend", "SolarPattern", "make_pattern", "make_solar_pattern",
]
