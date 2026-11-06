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

# Shared pytest fixtures and markers (ADR-005, ADR-015).
#
# Three layers of tests (DESIGN.md 13):
#   - unit: no hardware, no simulator needed, strict TDD.
#   - functional: simulators, mocks and real SER/video captures kept OUTSIDE
#     the repository in the path named by SOLARSCRIBE_FIXTURES.
#   - perf: the ADR-013 bench against the camera simulator and the capture
#     engine. It skips cleanly while either of them is still missing.
#
# The real captures never travel in the repo (they are big and private), so a
# missing path is not an error: a test that needs one skips. A path that is set
# but does not exist IS an error, because that is a misconfigured gate.

import os
from pathlib import Path

import pytest

# Where the real SER/video fixtures live, if the machine has them. The path is
# external on purpose: the captures are big and must not travel in the repo.
FIXTURES_ENV = "SOLARSCRIBE_FIXTURES"

# Markers owned by the test suite. `hardware` and `network` come from
# pyproject.toml; these are registered here because QE owns tests/ and must not
# touch packaging files. An unknown marker is a typo in a gate, so registering
# them keeps `pytest --strict-markers` honest.
MARKERS = (
    "perf: performance bench against the ADR-013 budget",
    "sim: needs the camera or mount simulator (solarscribe.devices.sim)",
    "realdata: needs a real capture in SOLARSCRIBE_FIXTURES",
    "functional: functional-layer test (simulators, mocks or real fixtures)",
    "slow: takes more than a few seconds",
)


# @args: config - pytest's configuration object
# @return: None. Registers the test-local markers
def pytest_configure(config):
    for marker in MARKERS:
        config.addinivalue_line("markers", marker)


@pytest.fixture(scope="session")
def fixtures_dir():
    # @return: the Path to the external fixtures folder, or None if not set
    raw = os.environ.get(FIXTURES_ENV)
    return Path(raw) if raw else None
