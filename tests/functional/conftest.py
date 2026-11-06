############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - functional tests fixtures module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Fixtures of the functional layer (ADR-015).
#
# A real capture is never required: if SOLARSCRIBE_FIXTURES is not set, or the
# catalogued file is not there, the test skips. A path that IS set but does not
# exist is a broken gate and fails loudly, because silently skipping a
# misconfigured directory would hide the fact that the real-data gate never ran.

import os
from pathlib import Path

import pytest

from tests.fixtures.catalogue import CATALOGUE, FixtureEntry, by_id


@pytest.fixture(scope="session")
def fixtures_root():
    # @return: the external fixtures directory; skips when the gate is off
    raw = os.environ.get("SOLARSCRIBE_FIXTURES")
    if not raw:
        pytest.skip(
            "SOLARSCRIBE_FIXTURES is not set: real captures live outside the "
            "repository (ADR-015)"
        )
    root = Path(raw).expanduser()
    if not root.is_dir():
        pytest.fail(
            f"SOLARSCRIBE_FIXTURES points to {root}, which is not a directory"
        )
    return root


@pytest.fixture(scope="session")
def catalogue() -> tuple[FixtureEntry, ...]:
    # @return: the catalogue of the real captures the suite knows about
    return CATALOGUE


@pytest.fixture
def fixture_path(fixtures_root):
    # @return: a callable id -> Path, skipping when the capture is not present
    def _path(entry_id: str) -> Path:
        entry = by_id(entry_id)
        assert entry is not None, f"fixture id {entry_id!r} is not catalogued"
        path = fixtures_root / entry.path
        if not path.is_file():
            pytest.skip(
                f"{entry.id}: {entry.path} is not in {fixtures_root} "
                f"({entry.what})"
            )
        if path.stat().st_size == 0:
            pytest.skip(f"{entry.id}: {entry.path} is empty")
        return path

    return _path
