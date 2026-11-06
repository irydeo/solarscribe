############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - performance tests fixtures module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Fixtures of the ADR-013 bench.
#
# The bench is opt-in: a plain `pytest tests` must stay fast and green while
# the engines are mid-change, so every test marked `perf` is skipped unless
# SOLARSCRIBE_PERF=1. The gate command is:
#
#   SOLARSCRIBE_PERF=1 .venv/bin/python -m pytest tests/perf -q -s
#
# or, for a report file:
#
#   SOLARSCRIBE_PERF=1 SOLARSCRIBE_BENCH_REPORT=/tmp/opencode/g3.md \
#       .venv/bin/python -m pytest tests/perf -q -s
#
# The measurement runs once per session and every test reads the same numbers,
# so a report and its checks can never come from two different runs.

import os
from pathlib import Path

import pytest

from tests.perf.budget import report_markdown
from tests.perf.harness import build_rig, measure

# A run shorter than this cannot average out the simulator's scheduling jitter;
# longer than it and CI spends minutes on benchmarks. Five seconds gives about
# 600 frames at 120 fps, enough to see a one-frame hole; phase 0 closes the
# figure with a longer run on hardware.
DEFAULT_SECONDS = 5.0


# @args: config - pytest's configuration; items - the collected tests
# @return: None. Skips the perf items unless the gate is explicitly enabled
def pytest_collection_modifyitems(config, items):
    if os.environ.get("SOLARSCRIBE_PERF") == "1":
        return
    skip = pytest.mark.skip(
        reason="performance bench is opt-in: set SOLARSCRIBE_PERF=1 (ADR-013 gate)"
    )
    for item in items:
        # Use the marker, not the keyword: the package name is also a keyword,
        # and the cheap budget/consistency tests must keep running always.
        if item.get_closest_marker("perf") is not None:
            item.add_marker(skip)


# @args: none
# @return: the measurement window in seconds, from SOLARSCRIBE_PERF_SECONDS
def _seconds() -> float:
    raw = os.environ.get("SOLARSCRIBE_PERF_SECONDS", str(DEFAULT_SECONDS))
    try:
        return max(0.1, float(raw))
    except ValueError:
        return DEFAULT_SECONDS


@pytest.fixture(scope="session")
def rig():
    # @return: the camera simulator plus the capture engine, or a clean skip
    built = build_rig()
    if built.rig is None:
        pytest.skip(f"perf bench not runnable: {built.reason}")
    return built.rig


@pytest.fixture(scope="session")
def measurement(rig, tmp_path_factory):
    # @return: one Measurement shared by every test in this run
    workdir = tmp_path_factory.mktemp("perf")
    result = measure(rig, _seconds(), Path(workdir))

    # The report is written before the assertions: a blocked gate must leave
    # its numbers behind even when the test that reads them fails.
    report_path = os.environ.get("SOLARSCRIBE_BENCH_REPORT")
    if report_path:
        Path(report_path).write_text(report_markdown(result), encoding="utf-8")

    return result
