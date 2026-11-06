############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - tests fixtures module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""Shared pytest fixtures.

The functional suite uses the camera and mount simulators and, when available,
real SER/video fixtures kept OUTSIDE the repository (a configurable path), never
committed. The catalogue of fixtures lives with the quality agent.
"""

import os

import pytest

# Where the real SER/video fixtures live, if the machine has them. The path is
# external on purpose: the captures are big and must not travel in the repo.
FIXTURES_ENV = "SOLARSCRIBE_FIXTURES"


@pytest.fixture(scope="session")
def fixtures_dir():
    # @return: the Path to the external fixtures folder, or None if not set
    from pathlib import Path
    path = os.environ.get(FIXTURES_ENV)
    return Path(path) if path else None
