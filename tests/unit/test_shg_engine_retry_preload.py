############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg engine retry and preload test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The two nightscribe-scan parity guarantees that had no dedicated test:
#   - the single row retry (SCAN_RETRIES = 1): a first attempt that stalls must
#     be retried once, and the second outcome is the one reported;
#   - the RA preload (preload_s > 0): the mount takes up the backlash before
#     the row starts recording, and preload_s = 0 skips that move.
#
# Both are exercised through the public ScanEngine contract (ScanEngineImpl +
# FrameSource + Mount + RowRecorder), with the deterministic fakes the rest of
# the shg suite uses. The clock and the sleep are injected, so the test owns
# time and no wall clock is involved.

from pathlib import Path

import pytest

from solarscribe.devices.abc import Axis
from solarscribe.shg.abc import RowCounters, ScanConfig, ScanStatus
from solarscribe.shg.engine import ScanEngineImpl
from tests.unit.test_shg_support import (
    FakeClock, FakeFrames, FakeMount, FakeRecorder, uniform_frame,
)


# @args: clock, mount, frames - the simulators; emit_from - first sleep call
#        that delivers a frame (1-based)
# @return: a sleep function that advances time and the mount and feeds frames
def _sleeper(clock, mount, frames, emit_from=1):
    calls = {"n": 0}

    def sleep(dt):
        clock.sleep(dt)
        mount.advance(dt)
        calls["n"] += 1
        if calls["n"] >= emit_from:
            frames.emit(uniform_frame(std=0))

    return sleep


# @args: clock, mount, frames - the simulators; sleep - the engine's sleep seam
# @return: an engine with the reference optics already set
def _engine(clock, mount, frames, sleep):
    engine = ScanEngineImpl(mount, frames, clock=clock.time, sleep=sleep)
    engine.set_optics(pixel_scale=0.5778, solar_diameter_arcsec=1920.0,
                      fps=120.0)
    engine.set_slit_arcsec(2000.0)
    return engine


# @args: padding, preload - seconds; adaptive - whether the limb stop may end it
# @return: a one-row config with no mosaic offset
def _config(padding, preload, adaptive=False):
    return ScanConfig(
        capture=(0, 0, 3480, 248),
        band=(0, 0, 64, 32),
        analysis={"limb": (0, 0, 64, 32)},
        rate_arcsec_s=1920.0,
        padding_s=padding,
        preload_s=preload,
        adaptive_stop=adaptive,
    )


class _StartProbe(FakeRecorder):
    # A RowRecorder that snapshots the mount and the clock exactly when the
    # engine says "recording starts". That is the boundary the preload test
    # needs: no internal state, only the two public calls.

    # @args: mount - the mount whose moves are snapshotted; clock - the test
    #        clock
    def __init__(self, mount, clock):
        super().__init__(RowCounters(frames_written=10))
        self._mount = mount
        self._clock = clock
        self.at_start = None

    # @args: path - the row file the engine is about to record
    # @return: none
    def start_row(self, path) -> None:
        self.at_start = (tuple(self._mount.moves), self._clock.time(), Path(path))
        super().start_row(path)


def test_a_stalled_first_row_is_retried_once_and_the_second_outcome_wins():
    # Attempt 1 sees one frame that is already older than the 3 s stall guard,
    # so it cannot finish. Attempt 2 gets a frame on every poll and completes.
    # Without the retry the run would return FAILED/stalled; with it, the
    # result is the second, successful outcome and the log holds both rows.
    clock = FakeClock()
    mount = FakeMount(ra=12.0, dec=20.0)
    frames = FakeFrames()
    engine = _engine(clock, mount, frames, _sleeper(clock, mount, frames,
                                                    emit_from=2))

    frames.emit(uniform_frame(std=0))     # the stale frame is at t = 0
    clock.t = 4.0                         # 4 s later it exceeds the guard
    plan = engine.plan(_config(padding=0.0, preload=0.0))

    result = engine.run(plan, lambda _progress: None, recorder=None)

    assert result.status is ScanStatus.COMPLETED
    assert result.rows_completed == 1
    assert result.frames_written > 0
    assert result.reason_code == ""

    # The ADR-018 log keeps one row per attempt: the stalled first try and the
    # completed retry. That is how the window explains what happened.
    rows = engine.log_rows()
    assert len(rows) == 2
    assert rows[0].problem == "stalled"
    assert rows[0].frames == 0
    assert rows[1].problem == ""
    assert rows[1].frames > 0


def test_preload_moves_the_mount_back_before_recording_starts():
    # The scan sweeps towards decreasing RA. Padding moves away from the start
    # (+), then the preload moves back towards it (-) to take up the backlash.
    # start_row must see both moves and a clock already past padding + preload.
    clock = FakeClock()
    mount = FakeMount(ra=12.0, dec=20.0)
    frames = FakeFrames()
    engine = _engine(clock, mount, frames, _sleeper(clock, mount, frames))
    probe = _StartProbe(mount, clock)

    plan = engine.plan(_config(padding=0.2, preload=0.1))
    result = engine.run(plan, lambda _progress: None, recorder=probe)

    assert result.status is ScanStatus.COMPLETED
    assert probe.at_start is not None
    moves, start_time, path = probe.at_start
    ra_moves = [move for move in moves if move[0] is Axis.RA]

    # Two RA moves before recording: the padding and the preload. The scan's
    # own move is issued after start_row and is not in this snapshot.
    assert len(ra_moves) == 2
    assert ra_moves[0][1] > 0.0          # padding, away from the sweep
    assert ra_moves[1][1] < 0.0          # preload, back towards the start
    assert start_time == pytest.approx(0.2 + 0.1)
    assert path == Path("scan_00.ser")


def test_preload_zero_skips_the_extra_move():
    # The same geometry with preload_s = 0: only the padding move happens
    # before recording, and the clock stops at the padding boundary.
    clock = FakeClock()
    mount = FakeMount(ra=12.0, dec=20.0)
    frames = FakeFrames()
    engine = _engine(clock, mount, frames, _sleeper(clock, mount, frames))
    probe = _StartProbe(mount, clock)

    plan = engine.plan(_config(padding=0.2, preload=0.0))
    result = engine.run(plan, lambda _progress: None, recorder=probe)

    assert result.status is ScanStatus.COMPLETED
    assert probe.at_start is not None
    moves, start_time, _path = probe.at_start
    ra_moves = [move for move in moves if move[0] is Axis.RA]
    assert len(ra_moves) == 1
    assert ra_moves[0][1] > 0.0
    assert start_time == pytest.approx(0.2)
