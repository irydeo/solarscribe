############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - real fixtures test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The catalogue is only worth something if each file is really what it says it
# is. These tests validate the catalogue itself (no data needed) and then the
# catalogued files when they are present: a SER whose header disagrees with the
# catalogue, or a scan log that no longer shows the calibration bug, would feed
# the science tests with the wrong reference.

import csv
import json
import struct

import pytest

from tests.fixtures.catalogue import CATALOGUE, KINDS, by_id, is_safe_relative

# SER header: FileID[14], then seven int32 (LuID, ColorID, LittleEndian,
# ImageWidth, ImageHeight, PixelDepth, FrameCount), then Observer[40],
# Instrument[40], Telescope[40], DateTime[8], DateTime double[8]. 178 bytes.
SER_HEADER_BYTES = 178
SER_STRUCT = struct.Struct("<14s7i40s40s40s8s8s")


def test_catalogue_is_well_formed():
    # A duplicated id or a path with ".." would let one entry shadow another or
    # read outside the fixtures directory.
    ids = set()
    for entry in CATALOGUE:
        assert entry.id not in ids, f"duplicated fixture id {entry.id!r}"
        ids.add(entry.id)
        assert entry.kind in KINDS, f"{entry.id}: unknown kind {entry.kind!r}"
        assert is_safe_relative(entry.path), (
            f"{entry.id}: {entry.path!r} must be relative and stay under the "
            f"fixtures directory"
        )
        assert entry.what.strip(), f"{entry.id} does not say what it holds"
        assert entry.tests.strip(), f"{entry.id} does not say what it proves"
        assert entry.source.strip(), f"{entry.id} does not say where it came from"

    assert by_id(CATALOGUE[0].id) is CATALOGUE[0]
    assert by_id("no-such-fixture") is None


def test_the_fixtures_environment_is_a_valid_directory():
    # fixtures_root fails (not skips) when the variable is set but wrong: a
    # gate that points at a typo must not look like a gate that did not run.
    import os
    from pathlib import Path

    raw = os.environ.get("SOLARSCRIBE_FIXTURES")
    if not raw:
        pytest.skip("SOLARSCRIBE_FIXTURES is not set (ADR-015)")
    assert Path(raw).expanduser().is_dir()


@pytest.mark.realdata
@pytest.mark.parametrize("entry", CATALOGUE, ids=lambda entry: entry.id)
def test_catalogued_file_is_present_and_not_empty(fixture_path, entry):
    path = fixture_path(entry.id)
    assert path.stat().st_size > 0


@pytest.mark.realdata
def test_scan_log_still_shows_the_calibration_bug(fixture_path):
    # The prototype's regression test (nightscribe-scan/tests/test_calibration.py)
    # reads the same log. If a future capture replaces it with a corrected one,
    # this test must be re-pointed instead of quietly losing the reference.
    entry = by_id("scan-log-calibration-bug")
    assert entry is not None
    expected = entry.expected()
    path = fixture_path(entry.id)

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) >= int(expected["min_rows"])
    columns = set(rows[0])
    assert {
        "actual_xy", "calibration_factor", "fps_used", "scan_speed_arcsec_s",
    } <= columns

    xy = [float(row["actual_xy"]) for row in rows if row["actual_xy"]]
    factors = [
        float(row["calibration_factor"])
        for row in rows
        if row["calibration_factor"]
    ]
    fps = [float(row["fps_used"]) for row in rows if row["fps_used"]]

    assert xy and max(xy) > float(expected["min_actual_xy"]), (
        f"the log no longer shows the stretched sweep: actual_xy values {xy}"
    )
    assert factors and min(factors) < float(expected["max_calibration_factor"]), (
        f"the log no longer shows the tiny calibration factor: {factors}"
    )
    assert fps and max(fps) >= float(expected["min_fps"])


@pytest.mark.realdata
@pytest.mark.parametrize(
    "entry",
    [entry for entry in CATALOGUE if entry.kind == "ser"],
    ids=lambda entry: entry.id,
)
def test_ser_fixture_header_matches_the_catalogue(fixture_path, entry):
    # Validate the file before any product code reads it. A wrong width or a
    # pixel depth other than 16 would make every downstream metric meaningless.
    path = fixture_path(entry.id)
    data = path.read_bytes()
    assert len(data) >= SER_HEADER_BYTES, f"{entry.id}: file is shorter than a SER header"

    (
        file_id, _lu_id, color_id, _little_endian, width, height, depth,
        frame_count, _observer, _instrument, _telescope, _dt8, _dt_double,
    ) = SER_STRUCT.unpack(data[:SER_HEADER_BYTES])

    assert file_id.rstrip(b"\x00") == b"LUCAM-RECORDER", (
        f"{entry.id}: not a SER file"
    )
    assert width > 0 and height > 0, f"{entry.id}: empty frame {width}x{height}"
    assert depth in (8, 16), f"{entry.id}: unexpected pixel depth {depth}"
    assert frame_count > 0, f"{entry.id}: no frames"

    actual = {
        "width": width, "height": height, "bit_depth": depth, "color_id": color_id,
    }
    for key, value in entry.expected().items():
        if key in actual:
            assert actual[key] == value, (
                f"{entry.id}: header {key} is {actual[key]}, catalogue says {value}"
            )

    # A truncated copy is worse than a missing one: it passes the header check
    # and fails in the middle of a scan. One plane per frame is the SER layout.
    payload = frame_count * width * height * max(1, depth // 8)
    assert len(data) >= SER_HEADER_BYTES + payload, (
        f"{entry.id}: frame count and file size disagree "
        f"({frame_count} frames, {len(data) - SER_HEADER_BYTES} payload bytes, "
        f"{payload} expected)"
    )


@pytest.mark.realdata
def test_session_meta_fixture_is_json(fixture_path):
    entry = by_id("session-meta")
    assert entry is not None
    path = fixture_path(entry.id)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
