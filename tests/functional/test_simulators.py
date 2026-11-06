############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - simulator contract boundary test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The functional boundary of the devices contract (ARCHITECTURE 2.1, ADR-005).
#
# The simulators are first-class backends, so the pipeline, the SHG engine and
# the UI run against them. These tests check the promises the rest of the suite
# stands on, at the boundary and not inside the implementation: the runtime
# Protocol, the frame buffer shape, the stats pair and the copy-on-cut rule that
# protects numpy's frombuffer from row strides.
#
# They use the same discovery as the performance bench. If the simulator is not
# there yet, they skip; if it is there but breaks the contract, they fail.

import threading
import time

import numpy as np
import pytest

from solarscribe.devices.abc import (
    Axis, Camera, Frame, FrameStats, Mount, MountCaps, MountStatus,
)
from tests.support import find_camera, find_mount

pytestmark = [pytest.mark.functional, pytest.mark.sim]


# @args: camera - an open simulator camera already streaming
# @return: the first `count` frames, or raises after the timeout
def _collect(camera, count=8, timeout=5.0):
    frames: list = []
    done = threading.Event()

    def on_frame(frame):
        frames.append(frame)
        if len(frames) >= count:
            done.set()

    camera.start_stream(on_frame)
    if not done.wait(timeout):
        camera.stop_stream()
        raise TimeoutError(f"only {len(frames)} of {count} frames arrived")
    return frames


def test_camera_simulator_satisfies_the_protocol():
    camera, label = find_camera()
    if camera is None:
        pytest.skip("the camera simulator is not available")
    assert isinstance(camera, Camera), f"{label} does not satisfy Camera"


def test_camera_frames_keep_the_contract_at_the_boundary():
    camera, _ = find_camera(fps=120.0)
    if camera is None:
        pytest.skip("the camera simulator is not available")

    camera.open()
    try:
        roi = camera.effective_area()
        camera.set_roi(roi)
        frames = _collect(camera, count=8)
    finally:
        camera.close()

    assert frames
    for frame in frames:
        assert isinstance(frame, Frame)
        assert (frame.width, frame.height) == (roi[2], roi[3])
        assert frame.roi == roi
        assert frame.dtype in (np.dtype(np.uint8), np.dtype(np.uint16))
        assert frame.dtype.itemsize in (1, 2)

        # Owned, C-contiguous buffer: np.frombuffer must work with no strides.
        assert memoryview(frame.data).c_contiguous
        array = np.frombuffer(frame.data, dtype=frame.dtype)
        assert array.size == frame.width * frame.height
        array = array.reshape(frame.height, frame.width)

        stats = frame.stats()
        assert isinstance(stats, FrameStats)
        assert stats.mean == pytest.approx(float(array.mean()), rel=1e-5)
        assert stats.std == pytest.approx(float(array.std()), rel=1e-5)

    # Sequence advances and timestamps never go backwards: the two host-side
    # signals the drop accounting is built on (ARCHITECTURE 4).
    sequences = [frame.sequence for frame in frames]
    assert sequences == list(range(sequences[0], sequences[0] + len(frames)))
    stamps = [frame.timestamp for frame in frames]
    assert stamps == sorted(stamps)


def test_cut_roi_is_always_contiguous_and_reads_the_right_pixels():
    camera, _ = find_camera(fps=120.0)
    if camera is None:
        pytest.skip("the camera simulator is not available")

    camera.open()
    try:
        camera.set_roi(camera.effective_area())
        frame = _collect(camera, count=1)[0]
    finally:
        camera.close()

    pixels = np.frombuffer(frame.data, dtype=frame.dtype).reshape(
        frame.height, frame.width
    )

    # Full-width strip: the zero-copy case that must still be C-contiguous.
    strip = frame.cut_roi((0, 2, frame.width, min(4, frame.height - 2)))
    assert memoryview(strip.data).c_contiguous
    strip_pixels = np.frombuffer(strip.data, dtype=strip.dtype).reshape(
        strip.height, strip.width
    )
    assert np.array_equal(
        strip_pixels, pixels[2:2 + strip.height, :]
    )

    # Narrow sub-rectangle: a strided view here would break frombuffer, so the
    # contract says it is copied.
    if frame.width >= 8 and frame.height >= 4:
        window = frame.cut_roi((2, 0, min(16, frame.width - 2),
                                min(4, frame.height)))
        assert memoryview(window.data).c_contiguous
        window_pixels = np.frombuffer(window.data, dtype=window.dtype).reshape(
            window.height, window.width
        )
        assert np.array_equal(
            window_pixels, pixels[0:window.height, 2:2 + window.width]
        )


def test_mount_simulator_satisfies_the_protocol_and_integrates_rates():
    mount, label = find_mount()
    if mount is None:
        pytest.skip("the mount simulator is not available")
    assert isinstance(mount, Mount), f"{label} does not satisfy Mount"

    mount.connect()
    try:
        caps = mount.capabilities()
        assert isinstance(caps, MountCaps)

        ra, dec = mount.position()
        assert 0.0 <= ra < 24.0, f"RA is in hours, got {ra}"
        assert -90.0 <= dec <= 90.0, f"Dec is in degrees, got {dec}"

        status = mount.status()
        assert isinstance(status, MountStatus)

        if caps.supports_axis_rates:
            mount.move_axis(Axis.RA, 15.0)
            time.sleep(0.01)
            mount.stop()
        assert mount.is_connected()
    finally:
        mount.close()
    assert not mount.is_connected()
