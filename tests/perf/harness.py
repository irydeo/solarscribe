############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - performance bench harness module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The bench itself: build a rig out of the camera simulator and the capture
# engine, run it at the reference ROI for a few seconds and measure what
# ADR-013 asks for.
#
# It is a BLACK-BOX bench. It talks to the camera through the devices contract
# and to the engine through the capture contract: it never reaches inside
# either. That is the point: the gate must measure the same boundary the app
# uses, so a refactor that keeps the contract cannot silently invalidate the
# numbers.
#
# What it cannot see, it says so. The engine's own counters are used when they
# exist (they are part of the contract), and the harness keeps an independent
# count of frames and sequence holes as a cross-check. If the engine cannot
# expose a working SER writer, the recording metrics are reported as
# unverified, never as a pass.

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from tests.perf.budget import (
    MAX_CAPTURE_START_S, Measurement, REFERENCE_BAND, REFERENCE_CAPTURE,
)
from tests.support import find_camera, find_capture_engine


@dataclass(frozen=True)
class Rig:
    # The two halves of a bench run, discovered at runtime.
    camera: object
    engine: object
    camera_label: str
    engine_label: str


@dataclass(frozen=True)
class RigBuild:
    # A build result instead of an exception: the caller skips with the reason
    # and the report can explain why the gate did not run.
    rig: Rig | None
    reason: str = ""


# @args: none
# @return: a Rig at the reference ROI, or the reason it cannot be built yet
def build_rig() -> RigBuild:
    camera, camera_label = find_camera(
        width=REFERENCE_CAPTURE[2], height=REFERENCE_CAPTURE[3],
        fps=120.0, pattern="test",
    )
    if camera is None:
        return RigBuild(None, "the camera simulator is not available "
                              "(solarscribe.devices.sim)")

    engine, engine_label = find_capture_engine()
    if engine is None:
        return RigBuild(None, "the capture engine is not available "
                              "(solarscribe.capture.engine)")

    if not _reference_roi_supported(camera):
        info = camera.info()
        return RigBuild(
            None,
            f"the simulator sensor {info.caps.roi.max_width}x"
            f"{info.caps.roi.max_height} cannot hold the reference ROI "
            f"{REFERENCE_CAPTURE[2]}x{REFERENCE_CAPTURE[3]}",
        )

    return RigBuild(Rig(camera=camera, engine=engine,
                        camera_label=camera_label, engine_label=engine_label))


# @args: camera - a Camera contract instance
# @return: whether its sensor accepts the 3480x248 reference strip exactly
def _reference_roi_supported(camera) -> bool:
    width, height = REFERENCE_CAPTURE[2], REFERENCE_CAPTURE[3]
    limits = camera.info().caps.roi
    return (
        limits.min_width <= width <= limits.max_width
        and limits.min_height <= height <= limits.max_height
        and width % max(1, limits.width_multiple) == 0
        and height % max(1, limits.height_multiple) == 0
        and REFERENCE_CAPTURE[0] % max(1, limits.offset_multiple) == 0
        and REFERENCE_CAPTURE[1] % max(1, limits.offset_multiple) == 0
    )


# @args: p - a percentile in [0, 100]
# @return: the percentile of a sorted list, nearest-rank; None for no samples
def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(p / 100.0 * (len(ordered) - 1)))))
    return ordered[index]


# @args: none
# @return: the current resident set size in MB, or 0.0 where the platform does
#          not expose it (the report then prints 0.0 instead of inventing one)
def read_rss_mb() -> float:
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            pages = int(handle.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / 1e6
    except (OSError, ValueError, IndexError):
        return 0.0


# @args: workdir - where the probe file is written; size_mb - how much to write
# @return: the raw fsync write rate in MB/s, or None when the platform refuses
#          the probe. This is the ADR-013 "sustained disk" figure: the stream
#          feeds the writer at ~207 MB/s, so the storage must do at least 250.
#          It is measured apart from the writer because feeding a 204 MB/s
#          stream and then demanding 250 of the writer compares two things.
def write_disk_probe(workdir: Path, size_mb: int = 128) -> float | None:
    path = workdir / "disk-probe.bin"
    chunk = b"\x00" * (8 * 1024 * 1024)
    blocks = max(1, int(size_mb) // 8)
    try:
        start = time.monotonic()
        with open(path, "wb", buffering=0) as handle:
            for _ in range(blocks):
                handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        elapsed = max(1e-9, time.monotonic() - start)
        return blocks * len(chunk) / elapsed / 1e6
    except OSError:
        return None
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# @args: rig - camera + engine; seconds - measurement window after the first
#        frame; workdir - where the temporary SER is written; capture, band -
#        the rectangles to use (default: the ADR-013 reference strip; the
#        harness self-test uses a small one)
# @return: a Measurement. Raises when the rig starts but never delivers a frame:
#          that is a real failure of the pipeline, not a missing simulator
def measure(
    rig: Rig,
    seconds: float,
    workdir: Path,
    capture: tuple[int, int, int, int] = REFERENCE_CAPTURE,
    band: tuple[int, int, int, int] = REFERENCE_BAND,
) -> Measurement:
    from solarscribe.capture.abc import (
        CaptureParams, RoiModel, SerColorId, SerHeader,
    )

    camera, engine = rig.camera, rig.engine
    notes: list[str] = []
    seconds = max(0.1, float(seconds))

    camera.open()
    limits = camera.info().caps.roi
    model = RoiModel(
        capture=capture,
        band=band,
        constraints=limits,
        binning=1,
    )
    camera.set_roi(model.capture)

    # One state dict, filled from the capture thread. Everything here is a
    # constant-time append: the callback shares the frame budget of 8.3 ms at
    # 120 fps, so no numpy work and no file I/O.
    state = {
        "frames": 0,
        "first": None,
        "last": None,
        "last_seq": None,
        "gaps": 0,
        "frame_bytes": 0,
        "latencies": [],
        "rss": [],
    }
    rss_start = read_rss_mb()
    state["rss"].append(rss_start)

    def on_frame(frame):
        now = time.monotonic()
        if state["first"] is None:
            state["first"] = now
            state["frame_bytes"] = (
                int(frame.width) * int(frame.height) * int(frame.dtype.itemsize)
            )
        state["last"] = now
        state["frames"] += 1

        # Independent hole counter: sequence must advance by one. The engine
        # also counts gaps, but a cross-check costs nothing and catches a
        # counter that reports a healthy stream over a real hole.
        seq = getattr(frame, "sequence", None)
        if seq is not None:
            if state["last_seq"] is not None and seq != state["last_seq"] + 1:
                state["gaps"] += 1
            state["last_seq"] = seq

        # Age of the frame when the inline consumer sees it: the lower bound of
        # the viewer latency (the Qt mailbox adds its own hop). Only sane ages
        # are kept; a zero timestamp means the backend did not stamp it.
        age = now - float(getattr(frame, "timestamp", 0.0) or 0.0)
        if 0.0 <= age <= 10.0:
            state["latencies"].append(age * 1000.0)

        if state["frames"] % 25 == 0:
            state["rss"].append(read_rss_mb())

    engine.configure(camera, model, CaptureParams())
    engine.on_frame(on_frame)

    header = SerHeader(
        width=model.capture[2], height=model.capture[3], bit_depth=16,
        color_id=SerColorId.MONO, roi=model.capture,
    )
    ser_path = workdir / "bench.ser"
    recording = False
    started_recording = False
    writer = None
    counters = None
    live_disk_mb_s = 0.0
    # Storage capability first, with the stream idle: the SER write must not
    # share the disk with the probe, and a slow disk must not look like a slow
    # pipeline.
    disk_capability = write_disk_probe(workdir)
    cpu_start = time.process_time()
    start = time.monotonic()

    try:
        engine.start()
        deadline = start + MAX_CAPTURE_START_S
        while state["first"] is None and time.monotonic() < deadline:
            time.sleep(0.005)
        if state["first"] is None:
            raise RuntimeError(
                f"no frame within the {MAX_CAPTURE_START_S:.0f} s start budget"
            )

        # Recording starts after the first frame so its setup never counts as
        # capture latency; from here the queue and the writer are in the path.
        try:
            engine.start_recording(ser_path, header)
            started_recording = True
            recording = bool(engine.is_recording())
        except Exception as exc:  # noqa: BLE001 - reported, not hidden
            notes.append(
                f"SER recording unavailable: {type(exc).__name__}: {exc}"
            )

        end = state["first"] + seconds
        while time.monotonic() < end:
            time.sleep(0.01)

        if started_recording:
            # The live writer rate is only available while the recording is
            # open: stop_recording() detaches the writer. Read it here, before
            # closing, so "the writer kept up" is measured at the real stream
            # rate instead of dividing written frames by the stream time.
            try:
                live = engine.counters()
                live_disk_mb_s = float(getattr(live, "disk_mb_s", 0.0) or 0.0)
            except Exception as exc:  # noqa: BLE001
                notes.append(f"live counters failed: {type(exc).__name__}: {exc}")
            try:
                writer = engine.stop_recording()
            except Exception as exc:  # noqa: BLE001
                notes.append(
                    f"stop_recording failed: {type(exc).__name__}: {exc}"
                )
        try:
            counters = engine.counters()
        except Exception as exc:  # noqa: BLE001
            notes.append(f"counters() failed: {type(exc).__name__}: {exc}")
    finally:
        try:
            engine.stop()
        finally:
            camera.close()

    cpu_seconds = time.process_time() - cpu_start
    wall = max(1e-9, time.monotonic() - start)
    elapsed = max(1e-9, (state["last"] or start) - (state["first"] or start))
    frames = state["frames"]
    frame_bytes = state["frame_bytes"]
    if frame_bytes == 0:
        frame_bytes = capture[2] * capture[3] * 2

    # The engine's counters are the contract, but the harness has its own count
    # and its own holes; take the worst of both so a broken counter cannot hide
    # a lost frame.
    sdk_drops = int(getattr(counters, "frames_dropped_sdk", 0) or 0)
    if counters is None:
        try:
            sdk_drops = int(camera.dropped_frames())
        except Exception:  # noqa: BLE001
            sdk_drops = 0
    queue_drops = int(getattr(writer, "frames_dropped_queue", 0) or 0)
    gaps = max(int(getattr(counters, "sequence_gaps", 0) or 0), state["gaps"])
    received = int(getattr(counters, "frames_received", 0) or 0) or frames
    expected = received + sdk_drops + queue_drops + gaps
    dropped_pct = 100.0 * (sdk_drops + queue_drops + gaps) / max(1, expected)

    # The live writer rate is the right figure; the fallback is only for an
    # engine that does not expose disk_mb_s while recording, and it is rough.
    disk_mb_s = live_disk_mb_s
    if disk_mb_s <= 0.0:
        disk_mb_s = float(getattr(counters, "disk_mb_s", 0.0) or 0.0)
    if disk_mb_s <= 0.0 and writer is not None and frames:
        written = int(getattr(writer, "frames_written", 0) or 0)
        disk_mb_s = written * frame_bytes / elapsed / 1e6

    rss = [value for value in state["rss"] if value > 0.0]
    rss_end = read_rss_mb()
    if rss_end > 0.0:
        rss.append(rss_end)

    try:
        ser_path.unlink(missing_ok=True)
    except OSError:
        pass

    return Measurement(
        seconds=elapsed,
        frames=frames,
        fps=frames / elapsed,
        frame_bytes=frame_bytes,
        throughput_mb_s=frames * frame_bytes / elapsed / 1e6,
        dropped_pct=dropped_pct,
        sdk_drops=sdk_drops,
        queue_drops=queue_drops,
        sequence_gaps=gaps,
        latency_p50_ms=_percentile(state["latencies"], 50),
        latency_p95_ms=_percentile(state["latencies"], 95),
        latency_max_ms=max(state["latencies"]) if state["latencies"] else None,
        capture_start_s=state["first"] - start,
        queue_high_water_mb=float(
            getattr(writer, "queue_high_water_mb", 0.0) or 0.0
        ),
        disk_mb_s=disk_mb_s,
        disk_capability_mb_s=disk_capability,
        rss_start_mb=rss[0] if rss else 0.0,
        rss_peak_mb=max(rss) if rss else 0.0,
        rss_end_mb=rss[-1] if rss else 0.0,
        cpu_percent=100.0 * cpu_seconds / wall,
        recording=recording and writer is not None,
        notes=tuple(notes),
        extras={
            "engine_fps": float(getattr(counters, "fps", 0.0) or 0.0),
            "engine_received": float(received),
        },
    )
