############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - capture simulator functional test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Functional capture pipeline (G2) and the measurable part of the ADR-013
# budget (G3), on the real-rate simulator.
#
# What these tests CAN measure on this machine: sustained frame rate, dropped
# frames from all three counters, sequence gaps, SER throughput and the inline
# consumer latency, with a small ROI so the suite stays fast. What they CANNOT
# measure: the 207 MB/s of the reference 3480x248 ROI on a real G3M678M, the
# USB/SDK behaviour, and the CPU cost of a real SDK callback. Those need the
# hardware validation phase and are reported as unverified.

import math
import os
import struct
import time

import numpy as np
import pytest

from solarscribe.capture.abc import (
    CaptureParams, RoiModel, SerColorId, SerHeader,
)
from solarscribe.capture.engine import CaptureEngineImpl
from solarscribe.capture.roi import validate_roi
from solarscribe.capture.ser import SerWriterImpl
from solarscribe.devices.abc import RoiConstraints
from solarscribe.devices.sim import SimCamera, SimFrame, SimMount, SolarPattern
from solarscribe.shg.abc import DecCenterMethod, ScanConfig, ScanStatus
from solarscribe.shg.engine import ScanEngineImpl


def _run(engine, camera, path, seconds, latencies=None):
    if latencies is not None:
        engine.on_frame(
            lambda frame: latencies.append(time.monotonic() - frame.timestamp),
        )
    engine.start()
    area = camera.effective_area()
    header = SerHeader(width=area[2], height=area[3], bit_depth=16, roi=area)
    engine.start_recording(path, header)
    started = time.monotonic()
    time.sleep(seconds)
    elapsed = time.monotonic() - started
    # Freeze the source before closing the recording. That is the honest
    # ordering for the accounting: every frame the host received is already in
    # the queue, so frames_written and frames_received refer to the same window
    # instead of racing the last few frames.
    camera.stop_stream()
    writer = engine.stop_recording()
    counters = engine.counters()
    engine.stop()
    return writer, counters, elapsed


def test_simulated_stream_records_a_readable_ser(tmp_path):
    camera = SimCamera(width=320, height=64, fps=120.0, bit_depth=16)
    engine = CaptureEngineImpl(start_timeout_s=5.0)
    area = camera.effective_area()
    roi = RoiModel(capture=area, band=(0, 16, 320, 32),
                   constraints=camera.info().caps.roi)
    engine.configure(camera, roi, CaptureParams(auto_exposure=False,
                                                queue_budget_mb=64.0))
    path = tmp_path / "sim.ser"
    writer, counters, elapsed = _run(engine, camera, path, 0.5)

    assert counters.frames_received >= 20
    assert counters.sequence_gaps == 0
    assert writer.frames_dropped_queue == 0
    assert writer.frames_written >= 20
    # The stream is up before the recording starts, so a handful of frames are
    # received but not recorded by design. What must never happen is the other
    # way round: more written than received.
    assert writer.frames_written <= counters.frames_received
    raw = path.read_bytes()
    assert struct.unpack_from("<i", raw, 38)[0] == writer.frames_written
    assert len(raw) == 178 + writer.frames_written * 320 * 64 * 2


def test_adr013_budget_on_the_simulator(tmp_path):
    # A deliberately small ROI: the target is the pipeline, not the sensor. The
    # reference ROI numbers (3480x248, ~207 MB/s) are for hardware.
    width, height, fps = 320, 64, 120.0
    camera = SimCamera(width=width, height=height, fps=fps, bit_depth=16,
                       pattern="flat")
    engine = CaptureEngineImpl(start_timeout_s=5.0)
    roi = RoiModel(capture=(0, 0, width, height), band=(0, 16, width, 32),
                   constraints=camera.info().caps.roi)
    engine.configure(camera, roi, CaptureParams(auto_exposure=False,
                                                queue_budget_mb=64.0))
    latencies = []
    path = tmp_path / "budget.ser"
    cpu_start = time.process_time()
    writer, counters, elapsed = _run(engine, camera, path, 1.0,
                                     latencies=latencies)
    cpu_used = time.process_time() - cpu_start
    mb_s = (writer.frames_written * width * height * 2 / 1_000_000.0
            / max(elapsed, 1e-9))
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0

    # Printed with -s so the numbers go into the validation report verbatim.
    print(
        "\nADR-013 simulator bench: "
        f"fps={counters.fps:.1f} "
        f"frames={writer.frames_written} "
        f"drops_sdk={counters.frames_dropped_sdk} "
        f"drops_queue={writer.frames_dropped_queue} "
        f"gaps={counters.sequence_gaps} "
        f"disk={mb_s:.1f} MB/s "
        f"queue_high_water={writer.queue_high_water_mb:.3f} MB "
        f"latency_p95={p95 * 1000.0:.2f} ms "
        f"cpu={cpu_used / max(elapsed, 1e-9) * 100.0:.0f}% of one core",
    )

    # The simulator runs a small ROI, so the rate is the only budget item that
    # transfers directly. A loaded CI machine is allowed some slack; a real
    # regression (a blocked capture thread) would show up as a much lower rate
    # or as queue drops.
    assert counters.fps >= 90.0
    assert writer.frames_written > 0
    assert counters.sequence_gaps == 0
    assert writer.frames_dropped_queue == 0
    assert p95 <= 0.150


@pytest.mark.skipif(
    not os.environ.get("SOLARSCRIBE_BENCH_REFERENCE"),
    reason="reference-ROI bench writes ~400 MB; set SOLARSCRIBE_BENCH_REFERENCE=1",
)
def test_adr013_reference_roi_throughput(tmp_path):
    # The 3480x248 reference ROI at 120 fps is the real budget: ~207 MB/s. The
    # simulator's numpy pattern generation is part of what this measures, so
    # the CPU number is an upper bound (a real SDK does the fill in C). The
    # rate, drops, gaps and disk throughput are directly comparable.
    width, height, fps = 3480, 248, 120.0
    camera = SimCamera(width=width, height=height, fps=fps, bit_depth=16,
                       pattern="flat")
    engine = CaptureEngineImpl(start_timeout_s=5.0)
    engine.configure(
        camera,
        RoiModel(capture=(0, 0, width, height), band=(0, 40, width, 160),
                 constraints=camera.info().caps.roi),
        CaptureParams(auto_exposure=False, queue_budget_mb=512.0),
    )
    latencies = []
    engine.on_frame(
        lambda frame: latencies.append(time.monotonic() - frame.timestamp),
    )
    path = tmp_path / "reference.ser"
    header = SerHeader(width=width, height=height, bit_depth=16,
                       roi=(0, 0, width, height))
    cpu_start = time.process_time()
    engine.start()
    engine.start_recording(path, header)
    started = time.monotonic()
    time.sleep(2.0)
    elapsed = time.monotonic() - started
    cpu_used = time.process_time() - cpu_start
    camera.stop_stream()
    writer = engine.stop_recording()
    counters = engine.counters()
    engine.stop()

    bytes_written = path.stat().st_size - 178
    mb_s = bytes_written / 1e6 / max(elapsed, 1e-9)
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    print(
        "\nADR-013 reference-ROI bench: "
        f"fps={counters.fps:.1f} frames={writer.frames_written} "
        f"drops_sdk={counters.frames_dropped_sdk} "
        f"drops_queue={writer.frames_dropped_queue} "
        f"gaps={counters.sequence_gaps} "
        f"disk={mb_s:.1f} MB/s "
        f"queue_high_water={writer.queue_high_water_mb:.1f} MB "
        f"latency_p95={p95 * 1000.0:.2f} ms "
        f"cpu_upper_bound={cpu_used / max(elapsed, 1e-9) * 100.0:.0f}% of one core",
    )
    assert counters.frames_received > 0
    assert counters.sequence_gaps == 0
    assert writer.frames_dropped_queue == 0
    assert mb_s >= 150.0     # a regression below this is a real disk problem
    assert p95 <= 0.150


def test_real_reference_strip_round_trips_through_the_ser_writer(
    tmp_path, fixture_path,
):
    # The user's real reference strip (3480x248, mono 16 bit). The writer must
    # reproduce its standard header fields and its payload byte for byte: that
    # is the ADR-018 promise, checked against a capture instead of a fixture
    # we invented. Skipped when SOLARSCRIBE_FIXTURES is not set.
    path = fixture_path("reference-strip-ser")
    raw = path.read_bytes()
    width, height = struct.unpack_from("<ii", raw, 26)
    depth = struct.unpack_from("<i", raw, 34)[0]
    little_endian = bool(struct.unpack_from("<i", raw, 22)[0])
    payload = raw[178:]
    assert (width, height, depth) == (3480, 248, 16)

    # Read the payload with the endianness the header declares, then hand the
    # writer the same flag: the round trip must not silently swap the words.
    dtype = "<u2" if little_endian else ">u2"
    array = np.frombuffer(payload, dtype=dtype).astype(np.uint16).reshape(
        height, width,
    )
    frame = SimFrame(array, (0, 0, width, height), 0, 0.0)
    out = tmp_path / "roundtrip.ser"
    writer = SerWriterImpl()
    writer.open(out, SerHeader(
        width=width, height=height, bit_depth=depth,
        color_id=SerColorId.MONO, little_endian=little_endian,
        roi=(0, 0, width, height),
    ))
    writer.write(frame)
    writer.close()

    written = out.read_bytes()
    assert written[0:38] == raw[0:38]          # FileID and standard fields
    assert written[178:] == payload            # the real pixels, untouched

    # The same geometry must pass the ROI validation as a reference case.
    model = RoiModel(
        capture=(0, 0, width, height),
        band=(0, 40, width, 160),
        constraints=RoiConstraints(max_width=width, max_height=height,
                                   width_multiple=8, height_multiple=2,
                                   offset_multiple=8),
    )
    assert validate_roi(model, fps=120.0) == []


def test_short_shg_scan_runs_against_the_solar_simulator():
    # End to end without hardware: the solar pattern is bound to the mount, the
    # capture engine streams it, and the real SHG scan engine drives the mount
    # and watches the limb. The row is short (a 1920" disk at 900"/s) so the
    # test stays inside a couple of seconds.
    sun_ra, sun_dec = 12.0, 0.0
    diameter = 1920.0
    slit_scale = 0.5778
    # Start exactly at the leading limb; the padding moves just outside it, so
    # the detector first sees dark sky and then a genuine rising edge.
    start_ra = sun_ra + (diameter / 2.0) / (
        54000.0 * math.cos(math.radians(sun_dec))
    )
    mount = SimMount(ra_hours=start_ra, dec_deg=sun_dec)
    mount.connect()
    camera = SimCamera(
        pattern="solar", fps=60.0,
        solar=SolarPattern(sun_ra_hours=sun_ra, sun_dec_deg=sun_dec),
    )
    camera.bind_mount(mount)
    camera.open()

    capture = CaptureEngineImpl(start_timeout_s=5.0)
    area = camera.effective_area()
    capture.configure(
        camera,
        RoiModel(capture=area, band=(0, 40, 3480, 160),
                 constraints=camera.info().caps.roi),
        CaptureParams(auto_exposure=False, queue_budget_mb=64.0),
    )
    scan = ScanEngineImpl(mount, capture)
    scan.set_optics(pixel_scale=slit_scale, solar_diameter_arcsec=diameter,
                    fps=60.0, slit_arcsec_px=slit_scale)
    scan.set_slit_arcsec(2022.0)

    capture.start()
    try:
        time.sleep(0.2)      # let the first frames settle
        config = ScanConfig(
            capture=(0, 0, 3480, 248),
            band=(0, 40, 3480, 160),
            analysis={"limb": (0, 40, 3480, 160)},
            rate_arcsec_s=900.0,
            # 0.1 s of padding leaves ~100 ms of margin after the trailing
            # limb, enough for two 20 ms detector polls on a loaded machine.
            padding_s=0.1,
            adaptive_stop=True,
        )
        plan = scan.plan(config)
        result = scan.run(plan, lambda _progress: None, recorder=None)
    finally:
        capture.stop()
        camera.close()
        mount.close()

    assert result.status == ScanStatus.COMPLETED
    assert result.rows_completed == 1
    assert result.frames_written > 0
    assert result.reason_code == ""
    # The adaptive stop, not the plan timer, ended the row: the trailing limb
    # was seen before the planned duration.
    assert scan.log_rows()[0].move_seconds < plan.rows[0].duration_s


def test_dec_centring_converges_against_the_solar_simulator():
    # The disk is 100" north of the slit. The real symmetry centring moves the
    # mount until the measured centroid offset is inside its 1" tolerance; the
    # pattern's left/right balance and centroid are what it reads.
    sun_ra, sun_dec = 12.0, 0.0
    slit_scale = 0.5778
    mount = SimMount(ra_hours=sun_ra, dec_deg=sun_dec + 100.0 / 3600.0)
    mount.connect()
    camera = SimCamera(
        pattern="solar", fps=60.0,
        solar=SolarPattern(sun_ra_hours=sun_ra, sun_dec_deg=sun_dec),
    )
    camera.bind_mount(mount)
    camera.open()

    capture = CaptureEngineImpl(start_timeout_s=5.0)
    area = camera.effective_area()
    capture.configure(
        camera,
        RoiModel(capture=area, band=(0, 40, 3480, 160),
                 constraints=camera.info().caps.roi),
        CaptureParams(auto_exposure=False, queue_budget_mb=64.0),
    )
    scan = ScanEngineImpl(mount, capture)
    scan.set_optics(pixel_scale=slit_scale, solar_diameter_arcsec=1920.0,
                    fps=60.0, slit_arcsec_px=slit_scale)
    scan.set_slit_arcsec(2022.0)

    capture.start()
    try:
        time.sleep(0.2)
        config = ScanConfig(
            capture=(0, 0, 3480, 248),
            band=(0, 40, 3480, 160),
            analysis={"limb": (0, 40, 3480, 160)},
            rate_arcsec_s=900.0,
            padding_s=0.1,
            dec_center=DecCenterMethod.SYMMETRY,
            adaptive_stop=True,
        )
        scan.plan(config)               # sets the engine's config
        result = scan.prepare(lambda _status: None)
    finally:
        capture.stop()
        camera.close()
        mount.close()

    assert result.ok, result.reason_code
    assert result.method == DecCenterMethod.SYMMETRY
    assert abs(result.dec_offset_arcsec) <= 1.0
    _ra, dec = mount.position()
    assert abs(dec - sun_dec) * 3600.0 <= 1.5


@pytest.mark.parametrize("fps", [30.0, 60.0])
def test_configured_rate_is_respected(tmp_path, fps):
    camera = SimCamera(width=64, height=32, fps=fps)
    engine = CaptureEngineImpl(start_timeout_s=5.0)
    area = camera.effective_area()
    engine.configure(
        camera,
        RoiModel(capture=area, band=(0, 8, 64, 16),
                 constraints=camera.info().caps.roi),
        CaptureParams(auto_exposure=False),
    )
    _, counters, elapsed = _run(engine, camera, tmp_path / f"{fps}.ser", 0.5)
    measured = counters.frames_received / max(elapsed, 1e-9)
    assert measured == pytest.approx(fps, rel=0.35)
