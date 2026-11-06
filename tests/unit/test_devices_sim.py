############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - simulator device test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The camera and mount simulators are first-class backends (ADR-005), not test
# hacks: the app, the SHG engine and the capture engine must all be able to run
# against them. These tests pin the parts the rest of the suite relies on:
# deterministic frames, sequence numbers, injectable drops and a mount that
# really integrates its rate.

import numpy as np
import pytest

from solarscribe.devices.abc import (
    Axis, Camera, DeviceError, Mount, Param, RoiConstraints,
)
from solarscribe.devices.sim import SimCamera, SimFrame, SimMount, SolarPattern
from solarscribe.shg.analysis import column_means, symmetry_centroid_offset_px


# @args: none
# @return: a small open manual camera and the frames it emitted
def _open_manual(width=64, height=32, **kwargs):
    cam = SimCamera(width=width, height=height, fps=0.0, **kwargs)
    cam.open()
    frames = []
    cam.start_stream(frames.append)
    return cam, frames


def test_sim_camera_satisfies_the_camera_contract():
    cam = SimCamera(width=64, height=32, fps=0.0)
    assert isinstance(cam, Camera)
    assert not cam.is_open()
    cam.open()
    assert cam.is_open()
    cam.close()
    assert not cam.is_open()
    cam.close()  # idempotent


def test_sim_camera_info_and_effective_area():
    cam = SimCamera(width=64, height=32, fps=0.0, camera_id="sim:test")
    info = cam.info()
    assert info.camera_id == "sim:test"
    assert info.backend == "sim"
    assert info.caps.roi == RoiConstraints(max_width=64, max_height=32)
    assert info.caps.bit_depths == (8, 16)
    assert cam.effective_area() == (0, 0, 64, 32)


def test_sim_camera_rejects_a_roi_outside_the_sensor():
    cam, _ = _open_manual()
    with pytest.raises(DeviceError) as exc:
        cam.set_roi((0, 0, 65, 32))
    assert exc.value.code == "roi_rejected"
    with pytest.raises(DeviceError):
        cam.set_roi((-1, 0, 10, 10))
    cam.set_roi((0, 0, 32, 16))
    assert cam.get_roi() == (0, 0, 32, 16)


def test_sim_camera_binning_changes_the_effective_area():
    cam, _ = _open_manual()
    cam.set_param(Param.BINNING, 2)
    assert cam.get_param(Param.BINNING) == 2
    assert cam.effective_area() == (0, 0, 32, 16)
    assert cam.get_roi() == (0, 0, 32, 16)
    with pytest.raises(DeviceError):
        cam.set_param(Param.BINNING, 5)


def test_sim_camera_params_have_ranges_and_refuse_unknown_ones():
    cam, _ = _open_manual()
    cam.set_param(Param.EXPOSURE, 2500.0)
    assert cam.get_param(Param.EXPOSURE) == pytest.approx(2500.0)
    rng = cam.param_range(Param.EXPOSURE)
    assert rng.minimum <= 2500.0 <= rng.maximum
    with pytest.raises(DeviceError) as exc:
        cam.get_param(Param.TEMPERATURE)   # no cooler in the MVP (DESIGN 5.1)
    assert exc.value.code == "not_supported"


def test_sim_camera_manual_stream_numbers_frames_deterministically():
    cam, frames = _open_manual()
    cam.emit(3)
    assert [f.sequence for f in frames] == [0, 1, 2]
    # The pattern is deterministic: same sequence, same pixels.
    cam2, frames2 = _open_manual()
    cam2.emit(3)
    a = np.frombuffer(frames[0].data, dtype=frames[0].dtype)
    b = np.frombuffer(frames2[0].data, dtype=frames2[0].dtype)
    assert np.array_equal(a, b)
    # ... and it changes with the sequence, so a test can tell frames apart.
    c = np.frombuffer(frames[1].data, dtype=frames[1].dtype)
    assert not np.array_equal(a, c)


def test_sim_camera_frame_stats_and_cut_roi_are_consistent():
    cam, frames = _open_manual()
    cam.emit(1)
    frame = frames[0]
    arr = np.frombuffer(frame.data, dtype=frame.dtype).reshape(frame.height, frame.width)
    stats = frame.stats()
    assert stats.mean == pytest.approx(float(arr.mean()))
    assert stats.std == pytest.approx(float(arr.std()))

    # A full-width strip is a zero-copy view and still reads with frombuffer.
    strip = frame.cut_roi((0, 4, frame.width, 8))
    strip_arr = np.frombuffer(strip.data, dtype=strip.dtype).reshape(8, frame.width)
    assert np.array_equal(strip_arr, arr[4:12, :])

    # Any narrower region is copied and matches the same pixels.
    sub = frame.cut_roi((5, 3, 10, 6))
    sub_arr = np.frombuffer(sub.data, dtype=sub.dtype).reshape(6, 10)
    assert np.array_equal(sub_arr, arr[3:9, 5:15])
    assert sub.width == 10 and sub.height == 6


def test_sim_camera_injectable_drops_count_and_open_sequence_holes():
    cam, frames = _open_manual(drop_every=2)
    cam.emit(6)
    # Frames 1, 3 and 5 are dropped: the host sees holes in the sequence.
    assert [f.sequence for f in frames] == [0, 2, 4]
    assert cam.dropped_frames() == 3
    cam.inject_drop(2)
    cam.emit(2)
    assert cam.dropped_frames() == 5
    cam.stop_stream()


def test_sim_camera_streams_on_a_thread_at_the_configured_rate():
    cam = SimCamera(width=32, height=16, fps=200.0)
    cam.open()
    frames = []
    cam.start_stream(frames.append)
    # 200 fps means about 20 frames in 100 ms; a wide window keeps it robust
    # under a loaded CI machine without making the suite slow.
    import time
    time.sleep(0.15)
    cam.stop_stream()
    assert len(frames) >= 8
    assert all(f.sequence == i for i, f in enumerate(frames))


def test_sim_frame_satisfies_the_frame_contract():
    cam, frames = _open_manual()
    cam.emit(1)
    from solarscribe.devices.abc import Frame, FrameStats
    assert isinstance(frames[0], Frame)
    assert isinstance(frames[0].stats(), FrameStats)
    assert frames[0].roi == (0, 0, 64, 32)
    assert SimFrame.__name__


def test_sim_mount_satisfies_the_mount_contract_and_integrates_rates():
    clock = [100.0]
    mount = SimMount(ra_hours=12.0, dec_deg=10.0, clock=lambda: clock[0])
    assert isinstance(mount, Mount)
    assert not mount.is_connected()
    mount.connect()
    assert mount.is_connected()
    assert mount.capabilities().supports_axis_rates
    assert mount.capabilities().can_slew

    # 15 arcsec/s in RA for 10 s: 150 arcsec = 150/54000 hours (1 h = 15 deg).
    mount.move_axis(Axis.RA, 15.0)
    clock[0] += 10.0
    ra, dec = mount.position()
    assert ra == pytest.approx(12.0 + 150.0 / 54000.0)
    assert dec == pytest.approx(10.0)

    # Dec movement is plain arcseconds of declination.
    mount.stop()
    mount.move_axis(Axis.DEC, -3.6)
    clock[0] += 10.0
    ra, dec = mount.position()
    assert ra == pytest.approx(12.0 + 150.0 / 54000.0)
    assert dec == pytest.approx(10.0 - 36.0 / 3600.0)

    mount.stop()
    before = mount.position()
    clock[0] += 10.0
    assert mount.position() == pytest.approx(before)


def test_sim_mount_tracks_slew_syncs_and_parks():
    clock = [0.0]
    mount = SimMount(ra_hours=12.0, dec_deg=0.0, clock=lambda: clock[0])
    mount.connect()

    # Sidereal tracking is 15.041 arcsec/s of RA coordinate.
    mount.set_tracking(True)
    clock[0] += 10.0
    ra, _ = mount.position()
    assert ra == pytest.approx(12.0 + 150.41 / 54000.0)
    assert mount.status().tracking

    mount.slew(6.0, -20.0)
    assert mount.position() == pytest.approx((6.0, -20.0))
    assert mount.status().parked is False

    mount.sync(5.0, -21.0)
    assert mount.position() == pytest.approx((5.0, -21.0))

    mount.park()
    assert mount.status().parked
    with pytest.raises(DeviceError):
        mount.move_axis(Axis.RA, 10.0)   # a parked mount must not move
    mount.unpark()
    assert not mount.status().parked

    mount.close()
    assert not mount.is_connected()


def test_sim_mount_refuses_rates_outside_its_capabilities():
    mount = SimMount()
    mount.connect()
    caps = mount.capabilities()
    with pytest.raises(DeviceError) as exc:
        mount.move_axis(Axis.RA, caps.max_rate_arcsec_s * 10.0)
    assert exc.value.code == "rate_rejected"
    mount.close()


# ── the solar-spectrum pattern ───────────────────────────────────────────────
# The pattern models a real SHG frame: x is the slit (north-south), y is the
# dispersion, the illuminated x span is the chord of the solar disk at the
# current RA, and its centre moves with the Dec error. These tests pin the
# properties the shg limb detector, centring and scan rely on.

# @args: camera - an open solar SimCamera
# @return: an empty frame list and the on_frame sink, armed
def _solar_sink(camera):
    frames: list = []
    camera.start_stream(frames.append)
    return frames


# @args: frame - a SimFrame
# @return: its pixels as a 2-D numpy array
def _pixels(frame):
    return np.frombuffer(frame.data, dtype=frame.dtype).reshape(
        frame.height, frame.width,
    )


def test_solar_pattern_defaults_to_the_reference_roi():
    camera = SimCamera(pattern="solar", fps=0.0)
    info = camera.info()
    assert (info.caps.roi.max_width, info.caps.roi.max_height) == (3480, 248)
    camera.open()
    frames = _solar_sink(camera)
    camera.emit(1)
    frame = frames[0]
    assert (frame.width, frame.height) == (3480, 248)
    assert frame.dtype == np.dtype(np.uint16)
    # The generic default is untouched: only the solar pattern is the big one.
    assert SimCamera().info().caps.roi.max_width == 320


def test_solar_pattern_has_a_visible_limb_and_high_on_disk_std():
    camera = SimCamera(pattern="solar", fps=0.0)
    camera.open()
    frames = _solar_sink(camera)
    camera.emit(1)
    on_disk = _pixels(frames[0])

    # On the disk the spectral lines give a std far above the limb detector's
    # 500 ADU floor and its 2000 ADU peak guard.
    assert float(on_disk.std()) > 2000.0
    edges = np.linspace(0, on_disk.shape[1], 65).astype(int)
    profile = [
        float(on_disk[40:200, edges[i]:edges[i + 1]].std())
        for i in range(64)
    ]
    # The chord is visible: dark sky at the slit ends, bright spectrum inside.
    assert max(profile) > 2000.0
    assert profile[0] < 100.0
    assert profile[-1] < 100.0

    # Move the slit 2000" east of the Sun: no chord, only sensor noise.
    camera.set_sky_position(12.0 + 2000.0 / 54000.0, 0.0)
    camera.emit(1)
    off_disk = _pixels(frames[-1])
    assert float(off_disk.std()) < 100.0
    assert float(off_disk.mean()) < 100.0


def test_solar_pattern_left_right_and_centroid_follow_the_mount():
    # The slit north of the Sun makes the disk appear south, so the bright
    # chord moves left and the left half wins; south of it, the reverse.
    camera = SimCamera(pattern="solar", fps=0.0)
    camera.open()
    frames = _solar_sink(camera)
    camera.set_sun(12.0, 0.0)

    # @args: slit_dec_deg - where the slit points in Dec
    # @return: (left-right mean, centroid offset in px)
    def measure(slit_dec_deg):
        camera.set_sky_position(12.0, slit_dec_deg)
        camera.emit(1)
        frame = frames[-1]
        pixels = _pixels(frame)
        left = float(pixels[40:200, :1740].mean())
        right = float(pixels[40:200, 1740:].mean())
        means = column_means(frame, (0, 40, 3480, 160), 64)
        centroid = symmetry_centroid_offset_px(means, 3480 // 64)
        return left - right, centroid

    centred_balance, centred_centroid = measure(0.0)
    north_balance, north_centroid = measure(100.0 / 3600.0)
    south_balance, south_centroid = measure(-100.0 / 3600.0)

    assert abs(centred_centroid) < 20.0
    assert centred_balance == pytest.approx(0.0, abs=100.0)
    # The sign flips with the side of the Sun, and the shift is large enough
    # for the shg centroid (a few pixels is already a real Dec error).
    assert north_centroid < -20.0 < 20.0 < south_centroid
    assert north_balance > 100.0
    assert south_balance < -100.0


def test_solar_pattern_brightness_follows_the_exposure():
    camera = SimCamera(pattern="solar", fps=0.0)
    camera.open()
    frames = _solar_sink(camera)
    camera.set_sky_position(12.0, 0.0)
    camera.set_param(Param.EXPOSURE, 1000.0)
    camera.emit(1)
    first = float(_pixels(frames[-1])[40:200, 100:3300].mean())
    camera.set_param(Param.EXPOSURE, 1500.0)
    camera.emit(1)
    second = float(_pixels(frames[-1])[40:200, 100:3300].mean())
    # Linear response: 1.5x exposure, 1.5x signal (the noise floor does not
    # scale, so the measured ratio is a little below 1.5).
    ratio = second / first
    assert 1.3 < ratio < 1.6


def test_solar_pattern_is_deterministic_and_seeded():
    def frame_for(seed):
        camera = SimCamera(
            pattern="solar", fps=0.0, solar=SolarPattern(seed=seed),
        )
        camera.open()
        frames = _solar_sink(camera)
        camera.set_sun(12.0, 0.0)
        camera.set_sky_position(12.0, 0.0)
        camera.emit(1)
        return _pixels(frames[0])

    assert np.array_equal(frame_for(7), frame_for(7))
    # The seed changes the fixed sensor noise, so the pixels differ, but the
    # disk geometry (the limb) is still there.
    assert not np.array_equal(frame_for(7), frame_for(8))
    assert float(frame_for(8).std()) > 2000.0
