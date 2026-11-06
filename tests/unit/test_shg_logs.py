############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg logs test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Anchor: ADR-018 and the prototype's write_scan_log / write_scan_stats /
# _session_meta. The first 24 CSV headers below are the prototype's list, in
# its order; the test locks them so a refactor cannot silently break the
# post-processing contract. New columns are allowed only at the end.

import csv
import json

from solarscribe.shg import logs
from solarscribe.shg.abc import RowCounters, ScanConfig, ScanPlan, ScanRow, ScanMode

# The exact nightscribe-scan headers, in order.
BASE_HEADERS = [
    "label", "utc", "local", "dec_start_deg", "dec_end_deg",
    "dec_offset_measured_arcsec", "ra_start_h", "ra_end_h",
    "displacement_arcsec", "fps_used", "scan_multiplier",
    "scan_speed_arcsec_s", "cos_dec", "calibration_factor", "padded_seconds",
    "scan_duration_s", "frames", "frames_expected", "frames_short_pct",
    "move_seconds", "actual_fps", "actual_xy", "slit_extent_px", "problem",
]


def _row() -> logs.ScanLogRow:
    return logs.ScanLogRow(
        label="scan00",
        utc="2026-11-06T12:00:00Z",
        local="2026-11-06T13:00:00",
        dec_start_deg=20.0,
        dec_end_deg=20.0,
        dec_offset_measured_arcsec=1.5,
        ra_start_h=12.0,
        ra_end_h=11.96,
        displacement_arcsec=2043.0,
        fps_used=120.0,
        scan_multiplier=1.0,
        scan_speed_arcsec_s=69.3,
        cos_dec=0.9397,
        calibration_factor=1.0,
        padded_seconds=1.0,
        scan_duration_s=29.7,
        frames=3564,
        frames_expected=3564.0,
        frames_short_pct=0.0,
        move_seconds=29.7,
        actual_fps=120.0,
        actual_xy=1.0,
        slit_extent_px=2010.0,
        problem="",
        roi_capture="0,0,3480,248",
        roi_band="0,40,3480,160",
        tilt_deg=0.4,
        tilt_px=1.7,
        frames_dropped_queue=2,
        frames_dropped_sdk=1,
        sequence_gaps=3,
        queue_high_water_mb=128.0,
        app_version="0.1.0",
        counters=RowCounters(frames_written=3564, frames_dropped_queue=2,
                             frames_dropped_sdk=1, sequence_gaps=3,
                             queue_high_water_mb=128.0),
    )


def test_scan_log_keeps_the_prototype_columns_in_order():
    headers = [header for header, _ in logs.SCAN_LOG_COLUMNS]
    assert headers[:len(BASE_HEADERS)] == BASE_HEADERS
    # Additions are allowed only after the base columns (ADR-018).
    assert set(BASE_HEADERS).issubset(headers)
    assert headers[len(BASE_HEADERS):] == [
        "roi_capture", "roi_band", "tilt_deg", "tilt_px",
        "frames_dropped_queue", "frames_dropped_sdk", "sequence_gaps",
        "queue_high_water_mb", "app_version", "consistency",
    ]


def test_write_scan_log_round_trips(tmp_path):
    path = tmp_path / "scan_log.csv"
    logs.write_scan_log([_row()], path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    row = rows[0]
    assert row["label"] == "scan00"
    assert row["utc"] == "2026-11-06T12:00:00Z"
    assert float(row["dec_start_deg"]) == 20.0
    assert float(row["scan_speed_arcsec_s"]) == 69.3
    assert row["roi_capture"] == "0,0,3480,248"
    assert float(row["tilt_deg"]) == 0.4
    assert row["app_version"] == "0.1.0"
    # A None becomes an empty cell, as in the prototype.
    empty = _row()
    empty.problem = None
    logs.write_scan_log([empty], path)
    with path.open(newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle))[0]["problem"] == ""


def test_scan_stats_has_the_prototype_keys_and_the_new_counters(tmp_path):
    path = tmp_path / "scan_stats.jsonl"
    logs.write_scan_stats(_row(), path)
    logs.write_scan_stats(_row(), path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    data = json.loads(lines[0])
    for key in ("label", "utc", "local", "dec_start", "frames",
                "frames_expected", "frames_short_pct", "actual_fps",
                "actual_xy", "slit_extent_px", "calibration_factor",
                "problem"):
        assert key in data
    assert data["frames_dropped_queue"] == 2
    assert data["sequence_gaps"] == 3
    assert data["roi_band"] == "0,40,3480,160"


def test_session_meta_keeps_the_prototype_sections_and_adds_roi(tmp_path):
    config = ScanConfig(capture=(0, 0, 3480, 248), band=(0, 40, 3480, 160),
                        tilt_deg=0.4, tilt_px=1.7)
    plan = ScanPlan(
        mode=ScanMode.SIMPLE, rate_arcsec_s=69.3,
        rows=(ScanRow(0, 0.0, 12.0, 11.96, 29.7),),
        duration_s=29.7, frames_estimate=3564, padding_s=1.0, preload_s=0.3)
    optics = {
        "focal_length_mm": 714.0,
        "pixel_size_um": 2.0,
        "pixel_scale_arcsec_px": 0.5778,
        "solar_diameter_arcsec": 1920.0,
        "solar_diameter_source": "ephemeris",
        "sidereal_arcsec_s": 15.04,
    }
    meta = logs.build_session_meta(config, plan, optics, "0.1.0",
                                   counters=RowCounters(frames_dropped_queue=2))
    for section in ("script", "created", "optics", "scan", "calibration",
                    "slit", "mosaic", "roi", "capture"):
        assert section in meta
    assert meta["roi"]["capture"] == "0,0,3480,248"
    assert meta["roi"]["tilt_deg"] == 0.4
    assert meta["capture"]["frames_dropped_queue"] == 2
    assert meta["optics"]["pixel_scale_arcsec_px"] == 0.5778

    path = tmp_path / "session_meta.json"
    logs.write_session_meta(meta, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["roi"]["band"] == "0,40,3480,160"
    assert loaded["app_version"] == "0.1.0"


def test_utc_stamp_is_iso8601_with_z():
    from datetime import datetime, timezone
    stamp = logs.utc_stamp(datetime(2026, 11, 6, 12, 34, 56,
                                   tzinfo=timezone.utc))
    assert stamp == "2026-11-06T12:34:56Z"
