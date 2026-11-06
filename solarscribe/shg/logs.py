############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg logs module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The three logs of ADR-018, written by shg from the contract value types:
#   - scan_log.csv: one row per scan, the link between the SERs and the
#     stacking/mosaic tools. It keeps the exact columns of nightscribe-scan and
#     adds ROI, tilt, drop counters and the app version at the end.
#   - scan_stats.jsonl: one JSON line per scan, the same per-scan statistics.
#   - session_meta.json: the effective configuration, the optics, the plan and
#     the counters, for reproducing the session.
#
# The CSV is rewritten after every scan (the prototype does the same) so a
# crash leaves the scans done so far. The JSON-lines file is appended, so a
# crash cannot truncate the history.
#
# Column rule (ADR-018): never remove or rename a nightscribe-scan column; add
# new ones at the end. The base list below is the prototype's write_scan_log
# order, kept verbatim, followed by the SolarScribe additions.

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from solarscribe.devices.abc import ROI

from .abc import RowCounters, ScanConfig, ScanPlan

__all__ = [
    "SCAN_LOG_COLUMNS",
    "ScanLogRow",
    "build_session_meta",
    "scan_stats_dict",
    "utc_stamp",
    "write_scan_log",
    "write_scan_stats",
    "write_session_meta",
]

# header, attribute. The first 24 pairs are nightscribe-scan's write_scan_log,
# in its order. Do not reorder or rename them (ADR-018).
_BASE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("label", "label"),
    ("utc", "utc"),
    ("local", "local"),
    ("dec_start_deg", "dec_start_deg"),
    ("dec_end_deg", "dec_end_deg"),
    ("dec_offset_measured_arcsec", "dec_offset_measured_arcsec"),
    ("ra_start_h", "ra_start_h"),
    ("ra_end_h", "ra_end_h"),
    ("displacement_arcsec", "displacement_arcsec"),
    ("fps_used", "fps_used"),
    ("scan_multiplier", "scan_multiplier"),
    ("scan_speed_arcsec_s", "scan_speed_arcsec_s"),
    ("cos_dec", "cos_dec"),
    ("calibration_factor", "calibration_factor"),
    ("padded_seconds", "padded_seconds"),
    ("scan_duration_s", "scan_duration_s"),
    ("frames", "frames"),
    ("frames_expected", "frames_expected"),
    ("frames_short_pct", "frames_short_pct"),
    ("move_seconds", "move_seconds"),
    ("actual_fps", "actual_fps"),
    ("actual_xy", "actual_xy"),
    ("slit_extent_px", "slit_extent_px"),
    ("problem", "problem"),
)

# SolarScribe additions (ADR-018: added, never replacing a base column).
_NEW_COLUMNS: tuple[tuple[str, str], ...] = (
    ("roi_capture", "roi_capture"),
    ("roi_band", "roi_band"),
    ("tilt_deg", "tilt_deg"),
    ("tilt_px", "tilt_px"),
    ("frames_dropped_queue", "frames_dropped_queue"),
    ("frames_dropped_sdk", "frames_dropped_sdk"),
    ("sequence_gaps", "sequence_gaps"),
    ("queue_high_water_mb", "queue_high_water_mb"),
    ("app_version", "app_version"),
    ("consistency", "consistency"),
)

SCAN_LOG_COLUMNS: tuple[tuple[str, str], ...] = _BASE_COLUMNS + _NEW_COLUMNS


@dataclass
class ScanLogRow:
    # One row of scan_log.csv. The types are deliberately plain: a row must
    # serialise even when a figure is unavailable (None becomes an empty cell,
    # as in the prototype).
    label: str = ""
    utc: str = ""
    local: str = ""
    dec_start_deg: float | None = None
    dec_end_deg: float | None = None
    dec_offset_measured_arcsec: float | None = None
    ra_start_h: float | None = None
    ra_end_h: float | None = None
    displacement_arcsec: float | None = None
    fps_used: float | None = None
    scan_multiplier: float | None = None
    scan_speed_arcsec_s: float | None = None
    cos_dec: float | None = None
    calibration_factor: float | None = None
    padded_seconds: float | None = None
    scan_duration_s: float | None = None
    frames: int | None = None
    frames_expected: float | None = None
    frames_short_pct: float | None = None
    move_seconds: float | None = None
    actual_fps: float | None = None
    actual_xy: float | None = None
    slit_extent_px: float | None = None
    problem: str = ""
    # Added columns.
    roi_capture: str = ""
    roi_band: str = ""
    tilt_deg: float | None = None
    tilt_px: float | None = None
    frames_dropped_queue: int = 0
    frames_dropped_sdk: int = 0
    sequence_gaps: int = 0
    queue_high_water_mb: float = 0.0
    app_version: str = ""
    consistency: str = ""      # issue keys from engine.check_consistency
    # Not written to the CSV: the raw counters, so the caller can build the
    # session meta and the stats line without re-parsing the row.
    counters: RowCounters = field(default_factory=RowCounters)


# @args: when - a datetime; None means now
# @return: ISO-8601 UTC with a trailing Z, as the prototype writes it
def utc_stamp(when: datetime | None = None) -> str:
    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# @args: roi - a rectangle
# @return: "x,y,w,h", the compact form used in the added ROI columns
def _roi_text(roi: ROI | None) -> str:
    if roi is None:
        return ""
    return ",".join(str(int(value)) for value in roi)


# @args: value - a cell value
# @return: the CSV text: floats with 6 decimals, None empty, everything else
#          as str
def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


# @args: rows - the scans so far; path - the CSV path
# @return: the path written
# The file is rewritten, not appended: the header stays in front and the rows
# are always in memory, so a crash mid-session cannot leave a half row.
def write_scan_log(rows: list[ScanLogRow], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([header for header, _ in SCAN_LOG_COLUMNS])
        for row in rows:
            writer.writerow([_cell(getattr(row, attr, None))
                             for _, attr in SCAN_LOG_COLUMNS])
    return path


# @args: row - one scan
# @return: the flat dict of scan_stats.jsonl
# It keeps the prototype's keys and adds the same figures as the CSV. The
# counters are the raw material of the G3 gate (ADR-013).
def scan_stats_dict(row: ScanLogRow) -> dict[str, object]:
    return {
        "label": row.label,
        "utc": row.utc,
        "local": row.local,
        "dec_start": row.dec_start_deg,
        "frames": row.frames,
        "frames_expected": row.frames_expected,
        "frames_short_pct": row.frames_short_pct,
        "actual_fps": row.actual_fps,
        "actual_xy": row.actual_xy,
        "slit_extent_px": row.slit_extent_px,
        "calibration_factor": row.calibration_factor,
        "problem": row.problem,
        # Added fields.
        "scan_speed_arcsec_s": row.scan_speed_arcsec_s,
        "cos_dec": row.cos_dec,
        "roi_capture": row.roi_capture,
        "roi_band": row.roi_band,
        "tilt_deg": row.tilt_deg,
        "tilt_px": row.tilt_px,
        "frames_dropped_queue": row.frames_dropped_queue,
        "frames_dropped_sdk": row.frames_dropped_sdk,
        "sequence_gaps": row.sequence_gaps,
        "queue_high_water_mb": row.queue_high_water_mb,
        "app_version": row.app_version,
        "consistency": row.consistency,
    }


# @args: row - one scan; path - the JSON-lines path
# @return: the path written
# One line per scan, sort_keys so two runs with the same data produce the same
# bytes. Best effort at the caller: a logging failure must not stop a scan.
def write_scan_stats(row: ScanLogRow, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(scan_stats_dict(row), sort_keys=True,
                      default=str, allow_nan=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return path


# @args: path - the session_meta.json path; meta - the dict to write
# @return: the path written
def write_session_meta(meta: dict[str, object], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    return path


# @args: config - the scan configuration
#        plan - the computed plan, or None before plan()
#        optics - focal_length_mm, pixel_size_um, pixel_scale_arcsec_px,
#                 solar_diameter_arcsec, solar_diameter_source and
#                 sidereal_arcsec_s
#        app_version - the package version
#        created - ISO timestamp; None means now
#        counters - the capture accounting of the last row
#        calibration - the calibration dict of the prototype
#        slit - the slit geometry dict of the prototype
#        extra - a dict merged last, for the caller's own fields
# @return: the session_meta.json dict, with the prototype keys and the new
#          ROI, tilt, counters and app version
# The shape follows the prototype's _session_meta() so the post-processing
# keeps reading it; the new keys are additions (ADR-018).
def build_session_meta(config: ScanConfig, plan: ScanPlan | None,
                       optics: dict[str, object], app_version: str,
                       created: str | None = None,
                       counters: RowCounters | None = None,
                       calibration: dict[str, object] | None = None,
                       slit: dict[str, object] | None = None,
                       fps: float | None = None,
                       scan_multiplier: float | None = None,
                       crossing_time_s: float | None = None,
                       extra: dict[str, object] | None = None) -> dict[str, object]:
    counters = counters or RowCounters()
    calibration = calibration or {
        "applied": False, "factor": 1.0, "measured_rate": 0.0,
        "target_rate": 0.0, "measured_per_unit": 0.0,
    }
    slit = slit or {
        "length_mm": 0.0,
        "image_scale_configured": 1.0,
        "image_scale_used": 1.0,
        "measured_extent_px": None,
        "measured_S_Y_arcsec_px": None,
    }
    scan = {
        "fps": fps,
        "scan_multiplier": scan_multiplier,
        "scan_speed_arcsec_s": plan.rate_arcsec_s if plan else config.rate_arcsec_s,
        "crossing_time_s": crossing_time_s,
        "padded_seconds": config.padding_s,
        "scan_duration_s": plan.duration_s if plan else None,
        "capture_fps_override": None,
        "fps_probe_seconds": None,
        "cos_dec_correction": True,
        "mode": config.mode.value,
        "rows": len(plan.rows) if plan else config.rows,
    }
    meta: dict[str, object] = {
        "script": "solarscribe",
        "app_version": app_version,
        "created": created or utc_stamp(),
        "optics": dict(optics),
        "scan": scan,
        "calibration": {"scan_rate": dict(calibration)},
        "slit": dict(slit),
        "mosaic": {
            "enabled": config.mode.value == "mosaic",
            "effective_slit_arcsec": slit.get("effective_slit_arcsec"),
            "overlap": None,
            "margin_arcsec": None,
            "scans_per_row": 1,
            "auto_center_dec": config.dec_center.value == "auto",
        },
        "roi": {
            "capture": _roi_text(config.capture),
            "band": _roi_text(config.band),
            "tilt_deg": config.tilt_deg,
            "tilt_px": config.tilt_px,
        },
        "capture": {
            "frames_dropped_queue": counters.frames_dropped_queue,
            "frames_dropped_sdk": counters.frames_dropped_sdk,
            "sequence_gaps": counters.sequence_gaps,
            "queue_high_water_mb": counters.queue_high_water_mb,
        },
    }
    if extra:
        meta.update(extra)
    return meta
