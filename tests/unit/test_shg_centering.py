############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg centering test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Anchors: the chord L = 2*sqrt(R^2 - e^2) (ADR-006) for the coarse score and
# the chord method; the centroid as the first moment of the illumination for
# the symmetry method. The honest limit: inside |q| < S/2 the chord is the full
# diameter, so the fine chord method cannot resolve the centre below S/2 and
# the coarse histogram is flat there too.

import math

import numpy as np
import pytest

from solarscribe.shg import centering, geometry
from solarscribe.shg.abc import DecCenterMethod, SunCenteringService

from .test_shg_support import (
    FakeClock,
    FakeFrame,
    FakeFrames,
    FakeMount,
    block_frame,
)


def _chord_score(dec_deg: float) -> float:
    # The illuminated extent at a Dec, with the slit at Dec 20.
    q = (dec_deg - 20.0) * 3600.0
    return geometry.chord_arcsec(q, 1444.0, 1920.0)


def test_coarse_hill_climb_stops_inside_the_dead_zone():
    # Start inside the flat top: the climb cannot know where the centre is,
    # so it stops with |q| <= S/2 + step. That is the honest limit.
    ok, best_dec, best_score, _steps = centering.coarse_center(
        _chord_score, start_dec_deg=20.0 + 700.0 / 3600.0,
        step_arcsec=300.0, max_steps=10)
    assert ok
    q = (best_dec - 20.0) * 3600.0
    assert abs(q) <= geometry.dead_zone_arcsec(1444.0) + 300.0
    assert best_score == pytest.approx(1920.0)


def test_coarse_hill_climb_walks_towards_the_disk_from_outside():
    # From 1500" out the chord is short; the climb must move in and end with a
    # score near the full diameter.
    ok, best_dec, best_score, _steps = centering.coarse_center(
        _chord_score, start_dec_deg=20.0 + 1500.0 / 3600.0,
        step_arcsec=300.0, max_steps=10)
    assert ok
    assert best_score == pytest.approx(1920.0, rel=1e-3)
    assert abs((best_dec - 20.0) * 3600.0) <= geometry.dead_zone_arcsec(1444.0) + 300.0


def test_symmetry_offset_recovers_a_known_block_shift():
    # A 10 px block 8 px right of the band centre, at 0.5778"/px.
    frame = block_frame(width=64, height=32, centre_px=40, block_px=10)
    offset = centering.measure_symmetry_offset_arcsec(
        frame, (0, 0, 64, 32), slit_arcsec_px=0.5778, columns=64)
    assert offset == pytest.approx(8.0 * 0.5778, abs=0.6)


def test_symmetry_center_converges_in_one_physical_step():
    # The probe returns the measured error; the loop moves Dec by -error.
    target = 20.0

    def probe(dec_deg: float) -> float:
        return (target - dec_deg) * 3600.0

    result = centering.symmetry_center(probe, start_dec_deg=19.0,
                                       tolerance_arcsec=0.5,
                                       max_iterations=4)
    assert result.ok
    assert result.dec_offset_arcsec == pytest.approx(0.0, abs=0.5)
    assert result.dead_zone_arcsec == 0.0


def test_symmetry_center_damps_a_noisy_probe():
    # A gain below 1 must take more than one step but still converge on a
    # noiseless probe.
    def probe(dec_deg: float) -> float:
        return (20.0 - dec_deg) * 3600.0

    result = centering.symmetry_center(probe, start_dec_deg=10.0,
                                       tolerance_arcsec=1.0,
                                       max_iterations=20, gain=0.5)
    assert result.ok
    assert result.dec_offset_arcsec == pytest.approx(0.0, abs=1.0)


def test_symmetry_center_reports_no_signal():
    result = centering.symmetry_center(lambda dec: None, 20.0)
    assert not result.ok
    assert result.reason_code == "no_limb"


class _ChordWorld:
    # A synthetic disk whose Dec offset is q arcsec. measure_chord returns the
    # chord at q; move_dec changes q. This is the external chord geometry,
    # driven as a fake mount.
    def __init__(self, q_arcsec: float) -> None:
        self.q = float(q_arcsec)
        self.moves = []

    def measure(self) -> float:
        return geometry.chord_arcsec(self.q, 1444.0, 1920.0)

    def move(self, delta_arcsec: float) -> None:
        self.moves.append(delta_arcsec)
        self.q += delta_arcsec

    def current(self) -> float:
        return 20.0 + self.q / 3600.0


def test_chord_center_recovers_an_offset_outside_the_dead_zone():
    for start in (1500.0, -1500.0):
        world = _ChordWorld(start)
        result = centering.chord_center(
            world.measure, world.move, world.current,
            solar_diameter_arcsec=1920.0, slit_arcsec=1444.0)
        assert result.ok, result.reason_code
        assert abs(world.q) < 1.0
        assert result.dead_zone_arcsec == pytest.approx(722.0)


def test_chord_center_leaves_the_dead_zone_and_reports_it():
    # Starting exactly at the centre: the chord is full and cannot resolve the
    # offset, so the method walks out of the dead zone, probes the sign and
    # corrects. The result must state the dead zone.
    world = _ChordWorld(0.0)
    result = centering.chord_center(
        world.measure, world.move, world.current,
        solar_diameter_arcsec=1920.0, slit_arcsec=1444.0)
    assert result.ok, result.reason_code
    assert abs(world.q) < 1.0
    assert result.dead_zone_arcsec == pytest.approx(722.0)


def test_chord_center_reports_no_limb_when_the_sweep_fails():
    world = _ChordWorld(1500.0)
    result = centering.chord_center(
        lambda: None, world.move, world.current,
        solar_diameter_arcsec=1920.0, slit_arcsec=1444.0)
    assert not result.ok
    assert result.reason_code == "no_limb"


def test_chord_is_flat_inside_the_dead_zone():
    # The mathematical limit the UI must state: the chord does not move until
    # the slit edge leaves the disk centre by more than S/2.
    full = geometry.chord_arcsec(0.0, 1444.0, 1920.0)
    assert geometry.chord_arcsec(700.0, 1444.0, 1920.0) == pytest.approx(full)
    assert geometry.chord_arcsec(800.0, 1444.0, 1920.0) < full


# ── SunCenteringImpl: the concrete SunCenteringService ───────────────────────

class _Pump:
    # Advances the fake clock and mount and delivers a frame on every sleep the
    # service takes. The frame function shapes the illuminated block from the
    # current mount Dec, so the coarse and fine stages see a physical disk.
    def __init__(self, clock, mount, frames, frame_fn):
        self.clock = clock
        self.mount = mount
        self.frames = frames
        self.frame_fn = frame_fn
        self.n = 0

    def sleep(self, dt: float) -> None:
        self.clock.sleep(dt)
        self.mount.advance(dt)
        self.n += 1
        self.frames.emit(self.frame_fn(self.n, self.mount))


def _symmetry_frame(target_dec: float, slit_arcsec: float,
                    solar_diameter: float, slit_arcsec_px: float):
    # A disk that fits along the slit: the block is the chord at the Dec error
    # and its centroid is the disk centre. For |q| + R <= S/2 it is not
    # clipped, which is the symmetry method's validity condition.
    def frame_fn(_n, mount):
        # q is the MOUNT error (north positive). The Sun is fixed, so a mount
        # north of it puts the Sun's image south of the slit centre: the block
        # centre moves the other way.
        q = (mount.dec - target_dec) * 3600.0
        chord = geometry.chord_arcsec(q, slit_arcsec, solar_diameter)
        width = max(1, int(round(chord / slit_arcsec_px)))
        centre = 128.0 - q / slit_arcsec_px
        data = np.zeros((32, 256), dtype=np.uint16)
        start = max(0, int(round(centre - width / 2.0)))
        stop = min(256, start + width)
        data[:, start:stop] = 1000
        return FakeFrame(data)
    return frame_fn


def test_coarse_score_is_the_illuminated_fraction():
    # The coarse stage maximises the LIT FRACTION, not the brightest pixel
    # value: a wider block must score higher, and the score is dimensionless.
    band = (0, 0, 128, 32)
    narrow = block_frame(width=128, height=32, centre_px=64, block_px=8,
                         band_y=0, band_h=32)
    wide = block_frame(width=128, height=32, centre_px=64, block_px=32,
                       band_y=0, band_h=32)
    assert centering.coarse_score(narrow, band) == pytest.approx(8.0 / 128.0)
    assert centering.coarse_score(wide, band) == pytest.approx(32.0 / 128.0)
    assert centering.coarse_score(wide, band) > centering.coarse_score(narrow, band)


def test_sun_centering_symmetry_end_to_end_and_progress():
    target = 20.0
    slit, diameter, slit_px = 4000.0, 1920.0, 4000.0 / 256.0
    clock = FakeClock()
    mount = FakeMount(ra=12.0, dec=target + 800.0 / 3600.0)
    frames = FakeFrames()
    frame_fn = _symmetry_frame(target, slit, diameter, slit_px)
    pump = _Pump(clock, mount, frames, frame_fn)
    service = centering.SunCenteringImpl(
        mount, frames, band=(0, 0, 256, 32),
        slit_arcsec=slit, solar_diameter_arcsec=diameter,
        slit_arcsec_px=slit_px,
        # One fake pixel is 15.6" wide (a 256 px band on a 4000" slit), so
        # the honest convergence threshold is one pixel, not the 1" the real
        # 0.58"/px camera can reach.
        fine_tolerance_arcsec=slit_px,
        clock=clock.time, sleep=pump.sleep)
    assert isinstance(service, SunCenteringService)
    statuses = []
    result = service.center(statuses.append)
    assert result.ok, result.reason_code
    assert result.method == DecCenterMethod.SYMMETRY
    assert result.dead_zone_arcsec == 0.0
    assert abs((mount.dec - target) * 3600.0) <= slit_px
    assert abs(result.dec_offset_arcsec) <= slit_px
    assert any(status.phase == "coarse" for status in statuses)
    assert statuses[-1].phase == "fine"
    assert statuses[-1].progress == pytest.approx(1.0)


def test_sun_centering_chord_reports_the_dead_zone():
    target = 20.0
    slit, diameter = 1000.0, 1920.0
    clock = FakeClock()
    mount = FakeMount(ra=12.0, dec=target + 1200.0 / 3600.0)
    frames = FakeFrames()
    pump = _Pump(clock, mount, frames,
                 lambda _n, _mount: FakeFrame(
                     np.zeros((32, 256), dtype=np.uint16)))

    def measure() -> float:
        q = (mount.dec - target) * 3600.0
        return geometry.chord_arcsec(q, slit, diameter)

    service = centering.SunCenteringImpl(
        mount, frames, band=(0, 0, 256, 32),
        slit_arcsec=slit, solar_diameter_arcsec=diameter,
        slit_arcsec_px=slit / 256.0,
        method=DecCenterMethod.CHORD, coarse=False,
        chord_measure=measure, clock=clock.time, sleep=pump.sleep)
    result = service.center()
    assert result.ok, result.reason_code
    assert result.method == DecCenterMethod.CHORD
    assert result.dead_zone_arcsec == pytest.approx(slit / 2.0)
    assert abs((mount.dec - target) * 3600.0) < 1.0


def test_sun_centering_chord_reports_no_limb():
    slit, diameter = 1000.0, 1920.0
    clock = FakeClock()
    mount = FakeMount(ra=12.0, dec=20.0)
    frames = FakeFrames()
    pump = _Pump(clock, mount, frames,
                 lambda _n, _mount: FakeFrame(
                     np.zeros((32, 256), dtype=np.uint16)))
    service = centering.SunCenteringImpl(
        mount, frames, band=(0, 0, 256, 32),
        slit_arcsec=slit, solar_diameter_arcsec=diameter,
        method=DecCenterMethod.CHORD, coarse=False,
        chord_measure=lambda: None, clock=clock.time, sleep=pump.sleep)
    result = service.center()
    assert not result.ok
    assert result.reason_code == "no_limb"
    assert result.dead_zone_arcsec == pytest.approx(slit / 2.0)


def test_sun_centering_reports_low_contrast_on_a_dark_frame():
    # A dark frame has no illuminated spectrum; the symmetry method cannot
    # work there, so the service says low_contrast instead of inventing a
    # centre.
    clock = FakeClock()
    mount = FakeMount(ra=12.0, dec=20.0)
    frames = FakeFrames()
    pump = _Pump(clock, mount, frames,
                 lambda _n, _mount: FakeFrame(
                     np.zeros((32, 256), dtype=np.uint16)))
    service = centering.SunCenteringImpl(
        mount, frames, band=(0, 0, 256, 32),
        slit_arcsec=4000.0, solar_diameter_arcsec=1920.0,
        method=DecCenterMethod.SYMMETRY, clock=clock.time, sleep=pump.sleep)
    result = service.center()
    assert not result.ok
    assert result.reason_code == "low_contrast"
