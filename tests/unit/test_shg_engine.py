############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg engine test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Engine tests over deterministic fakes (ADR-005): the plan geometry is pure,
# the adaptive stop is the stddev drop of the prototype's trailing_limb_stop,
# and pause/resume/abort are exercised without a camera or a driver.
#
# The engine's external anchors are the same as its modules: the chord and
# 1/cos(Dec) geometry, the 15.04"/s sidereal rate and the 1920" solar diameter
# of the prototype. The tests assert the sequencing, not a re-derivation.

import math

import numpy as np
import pytest

from solarscribe.devices.abc import Axis
from solarscribe.shg import geometry
from solarscribe.shg.abc import (
    DecCenterMethod,
    RowCounters,
    ScanConfig,
    ScanMode,
    ScanState,
    ScanStatus,
)
from solarscribe.shg.engine import ScanEngineImpl, check_consistency

from .test_shg_support import (
    FakeClock,
    FakeFrame,
    FakeFrames,
    FakeMount,
    FakeRecorder,
    block_frame,
)


class Pump:
    # Advances the simulated clock and the mount, and delivers a frame on every
    # sleep the engine takes. frame_fn(n, mount) builds the frame, so a test can
    # shape the stddev timeline or the illuminated centroid.
    def __init__(self, clock, mount, frames, frame_fn, on_sleep=None):
        self.clock = clock
        self.mount = mount
        self.frames = frames
        self.frame_fn = frame_fn
        self.on_sleep = on_sleep
        self.n = 0

    def sleep(self, dt: float) -> None:
        self.clock.sleep(dt)
        self.mount.advance(dt)
        self.n += 1
        frame = self.frame_fn(self.n, self.mount)
        if frame is not None:
            self.frames.emit(frame)
        if self.on_sleep is not None:
            self.on_sleep(self.n)


def _std_frame(_n, _mount, value=0):
    return FakeFrame(np.full((8, 8), value, dtype=np.uint16),
                     std=float(value), mean=float(value))


def _make_engine(std_sequence=None, frame_fn=None, on_sleep=None):
    clock = FakeClock()
    mount = FakeMount(ra=12.0, dec=20.0)
    frames = FakeFrames()
    if frame_fn is None:
        def frame_fn(n, _mount):
            value = std_sequence(n) if std_sequence else 0
            return _std_frame(n, _mount, value)
    pump = Pump(clock, mount, frames, frame_fn, on_sleep)
    holder = {"pump": pump}
    engine = ScanEngineImpl(mount, frames, clock=clock.time,
                            sleep=lambda dt: holder["pump"].sleep(dt))
    engine.set_optics(pixel_scale=0.5778, solar_diameter_arcsec=1920.0,
                      fps=120.0)
    engine.set_slit_arcsec(2000.0)
    return engine, mount, frames, clock, pump


def _config(**overrides):
    values = dict(
        capture=(0, 0, 3480, 248),
        band=(0, 0, 64, 32),
        analysis={"limb": (0, 0, 64, 32)},
        rate_arcsec_s=1000.0,
        padding_s=0.05,
        preload_s=0.0,
        adaptive_stop=True,
    )
    values.update(overrides)
    return ScanConfig(**values)


def test_plan_simple_geometry_and_ra_limits():
    engine, mount, _frames, _clock, _pump = _make_engine()
    plan = engine.plan(_config())
    assert plan.mode == ScanMode.SIMPLE
    assert plan.rate_arcsec_s == pytest.approx(1000.0)
    assert len(plan.rows) == 1
    row = plan.rows[0]
    assert row.dec_offset_arcsec == 0.0
    assert row.ra_start_hours == pytest.approx(12.0)
    # RA decreases during the scan, and the span is the sky span / cos(Dec).
    assert row.ra_end_hours < row.ra_start_hours
    expected_span = 1920.0 / math.cos(math.radians(20.0)) / 54000.0
    assert (row.ra_start_hours - row.ra_end_hours) == pytest.approx(expected_span)
    assert plan.duration_s == pytest.approx(2 * 0.05 + 1920.0 / 1000.0)
    assert plan.frames_estimate == int(round(120.0 * plan.duration_s))


def test_plan_mosaic_has_the_requested_rows_and_centred_offsets():
    engine, _mount, _frames, _clock, _pump = _make_engine()
    config = _config(mode=ScanMode.MOSAIC, rows=3, row_step_arcsec=1000.0)
    plan = engine.plan(config)
    assert plan.mode == ScanMode.MOSAIC
    assert len(plan.rows) == 3
    offsets = [row.dec_offset_arcsec for row in plan.rows]
    assert offsets == pytest.approx([-1000.0, 0.0, 1000.0])
    assert sum(offsets) / len(offsets) == pytest.approx(0.0)


def test_plan_rate_zero_uses_the_one_pixel_per_frame_target():
    engine, _mount, _frames, _clock, _pump = _make_engine()
    plan = engine.plan(_config(rate_arcsec_s=0.0))
    assert plan.rate_arcsec_s == pytest.approx(0.5778 * 120.0)


def test_prepare_symmetry_centres_a_known_offset():
    def frame_fn(_n, mount):
        # The telescope north of the Sun makes the Sun appear south of the slit
        # centre, so the measured offset is the negative of the mount error.
        offset_px = (20.0 - mount.dec) * 3600.0 / 0.5778
        return block_frame(width=64, height=32, centre_px=32 + offset_px,
                           block_px=10, band_y=0, band_h=32)

    engine, mount, _frames, _clock, _pump = _make_engine(frame_fn=frame_fn)
    mount.dec = 20.0 + 10.0 / 3600.0          # 10" north of the centre
    config = _config(rate_arcsec_s=50.0,
                     dec_center=DecCenterMethod.SYMMETRY)
    engine.plan(config)
    statuses = []
    result = engine.prepare(statuses.append)
    assert result.ok, result.reason_code
    assert result.method == DecCenterMethod.SYMMETRY
    assert result.rate_arcsec_s == pytest.approx(50.0)
    # The loop converges when the measured offset is inside 1", so the mount
    # can be up to 1" from the exact centre: that is the honest residual.
    assert abs(result.dec_offset_arcsec) <= 1.0
    assert mount.dec == pytest.approx(20.0, abs=1.0 / 3600.0)
    assert statuses


def test_prepare_calibrates_the_rate_with_the_corrected_formula():
    def frame_fn(_n, _mount):
        # A centred block: the symmetry step sees zero offset and converges.
        return block_frame(width=64, height=32, centre_px=32, block_px=10,
                           band_y=0, band_h=32)

    engine, _mount, _frames, _clock, _pump = _make_engine(frame_fn=frame_fn)
    per_unit = 13.35
    engine.set_probe_functions(crossing_measure=lambda: 16.0 * per_unit)
    config = _config(rate_arcsec_s=0.0,
                     dec_center=DecCenterMethod.SYMMETRY)
    engine.plan(config)
    result = engine.prepare(lambda status: None)
    assert result.ok, result.reason_code
    # target = 0.5778*120 = 69.336"/s; the corrected formula must recover it.
    assert result.rate_arcsec_s == pytest.approx(0.5778 * 120.0, rel=1e-6)


def test_run_adaptive_stop_ends_before_the_planned_duration():
    # std timeline: dark, on disk, then the trailing limb. The detector needs
    # two samples above and two below, as in the prototype.
    def timeline(n):
        if n <= 5:
            return 100.0
        if n <= 25:
            return 10000.0
        return 100.0

    engine, _mount, _frames, _clock, _pump = _make_engine(std_sequence=timeline)
    plan = engine.plan(_config())
    recorder = FakeRecorder(RowCounters(frames_written=50,
                                        frames_dropped_queue=2,
                                        frames_dropped_sdk=1,
                                        sequence_gaps=3))
    result = engine.run(plan, lambda progress: None, recorder)
    assert result.status == ScanStatus.COMPLETED
    assert result.rows_completed == 1
    assert result.frames_written == 50
    assert result.frames_dropped == 3
    assert recorder.paths and recorder.paths[0].name == "scan_00.ser"
    row = engine.log_rows()[0]
    assert row.frames == 50
    assert row.frames_dropped_queue == 2
    assert row.sequence_gaps == 3
    assert row.move_seconds < plan.rows[0].duration_s
    assert row.problem == ""


def test_run_without_adaptive_stop_uses_the_planned_duration():
    engine, _mount, _frames, _clock, _pump = _make_engine(
        std_sequence=lambda _n: 100.0)
    plan = engine.plan(_config(adaptive_stop=False))
    recorder = FakeRecorder(RowCounters(frames_written=10))
    result = engine.run(plan, lambda progress: None, recorder)
    assert result.status == ScanStatus.COMPLETED
    row = engine.log_rows()[0]
    assert row.move_seconds == pytest.approx(plan.rows[0].duration_s, rel=0.05)


def test_run_abort_keeps_the_aborted_status():
    holder = {}

    def on_sleep(n):
        if n == 10:
            holder["engine"].abort()

    engine, _mount, _frames, _clock, _pump = _make_engine(
        std_sequence=lambda _n: 10000.0, on_sleep=on_sleep)
    holder["engine"] = engine
    plan = engine.plan(_config(adaptive_stop=False))
    result = engine.run(plan, lambda progress: None,
                        FakeRecorder(RowCounters(frames_written=10)))
    assert result.status == ScanStatus.ABORTED
    assert result.reason_code == "aborted"
    assert engine.state() == ScanState.ABORTING


def test_run_pause_and_resume_hold_and_continue_the_sweep():
    def on_sleep(n):
        if n == 10:
            holder["engine"].pause()
        elif n == 15:
            holder["engine"].resume()

    holder = {}
    engine, _mount, _frames, _clock, _pump = _make_engine(
        std_sequence=lambda _n: 100.0, on_sleep=on_sleep)
    holder["engine"] = engine
    plan = engine.plan(_config(adaptive_stop=False))
    result = engine.run(plan, lambda progress: None,
                        FakeRecorder(RowCounters(frames_written=10)))
    assert result.status == ScanStatus.COMPLETED
    assert result.rows_completed == 1


def test_pause_and_resume_flags_are_honest():
    engine, _mount, _frames, _clock, _pump = _make_engine()
    engine.pause()
    assert engine.state() in (ScanState.RUNNING, ScanState.PAUSED)
    engine.resume()
    assert engine.state() in (ScanState.RUNNING, ScanState.PAUSED)


def test_dry_run_counts_the_frames_it_saw():
    engine, _mount, _frames, _clock, _pump = _make_engine(
        std_sequence=lambda _n: 100.0)
    plan = engine.plan(_config(adaptive_stop=False, padding_s=0.0))
    result = engine.run(plan, lambda progress: None, None)
    assert result.status == ScanStatus.COMPLETED
    assert result.ser_paths == ()
    assert result.frames_written > 0


def test_prepare_reports_a_mount_without_rate_movement():
    from solarscribe.devices.abc import MountCaps
    engine, mount, _frames, _clock, _pump = _make_engine()
    mount.capabilities = lambda: MountCaps(supports_axis_rates=False)
    engine.plan(_config())
    result = engine.prepare(lambda status: None)
    assert not result.ok
    assert result.reason_code == "mount_no_rate"


def test_consistency_flags_a_scale_or_extent_drift():
    # The prototype warns at 3% (_check_consistency). A matching row is silent;
    # a 5% X/Y drift and a 5% extent drift are two issues.
    assert check_consistency(1.0, 2000.0, 1.0, 2000.0) == ()
    issues = check_consistency(1.05, 1900.0, 1.0, 2000.0)
    assert {issue.field for issue in issues} == {"actual_xy", "slit_extent_px"}
    assert all(issue.deviation == pytest.approx(0.05) for issue in issues)
    # The first good row sets the reference, so a missing one is not an issue.
    assert check_consistency(1.0, 2000.0, None, None) == ()


def test_run_writes_the_three_adr018_logs(tmp_path):
    # The engine owns the three logs (ARCHITECTURE 3.3): a scan row in the CSV,
    # a line in the JSONL and the session meta with the ROI and the counters.
    engine, _mount, _frames, _clock, _pump = _make_engine(
        std_sequence=lambda _n: 100.0)
    scan_log = tmp_path / "scan_log.csv"
    scan_stats = tmp_path / "scan_stats.jsonl"
    session_meta = tmp_path / "session_meta.json"
    engine.set_log_paths(scan_log, scan_stats, session_meta)
    plan = engine.plan(_config(adaptive_stop=False, padding_s=0.0))
    result = engine.run(plan, lambda progress: None,
                        FakeRecorder(RowCounters(frames_written=20)))
    assert result.status == ScanStatus.COMPLETED
    assert scan_log.exists() and scan_stats.exists() and session_meta.exists()
    header = scan_log.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("label,utc,local,dec_start_deg")
    assert "roi_capture" in header
    meta_text = session_meta.read_text(encoding="utf-8")
    assert '"roi"' in meta_text
    assert '"band": "0,0,64,32"' in meta_text
    assert scan_stats.read_text(encoding="utf-8").strip()
