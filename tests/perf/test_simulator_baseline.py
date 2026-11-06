############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - simulator baseline performance test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The pipeline cannot be faster than the source. Before blaming the capture
# engine for a missed 120 fps, measure the simulator alone at the reference
# strip: this is the rig's floor, not the product gate (the product gate is
# test_capture_bench.py).
#
# Why it exists: while the engine is being written, this number tells video
# whether the simulator can feed the bench at all. A simulator that generates
# frames in Python below 120 fps makes the G3 gate unmeasurable no matter how
# good the pipeline is, and that must be a measured finding, not a guess.

import time

import pytest

from tests.perf.budget import REFERENCE_CAPTURE, TARGET_FPS
from tests.support import find_camera

pytestmark = [pytest.mark.perf, pytest.mark.sim]

# The rig must at least approach the reference rate to say anything useful. It
# is deliberately below 120: the strict 120 check belongs to the product gate,
# where the source and the engine are measured together.
FLOOR_FPS = 100.0


# @args: seconds - how long to sample
# @return: (fps, MB/s, frames) delivered by the simulator alone at 3480x248
def _sample(seconds: float = 2.0):
    camera, _ = find_camera(
        width=REFERENCE_CAPTURE[2], height=REFERENCE_CAPTURE[3],
        fps=TARGET_FPS, pattern="test",
    )
    if camera is None:
        pytest.skip("the camera simulator is not available")

    frames: list = []
    camera.open()
    camera.set_roi(REFERENCE_CAPTURE)
    camera.start_stream(frames.append)
    start = time.monotonic()
    time.sleep(seconds)
    camera.stop_stream()
    camera.close()
    elapsed = time.monotonic() - start

    frame_bytes = 0
    if frames:
        frame = frames[0]
        frame_bytes = frame.width * frame.height * frame.dtype.itemsize
    return len(frames) / elapsed, len(frames) * frame_bytes / elapsed / 1e6, len(frames)


def test_simulator_can_drive_the_reference_strip():
    fps, throughput, frames = _sample()
    print(
        f"\nsimulator alone: {frames} frames, {fps:.2f} fps, "
        f"{throughput:.2f} MB/s at "
        f"{REFERENCE_CAPTURE[2]}x{REFERENCE_CAPTURE[3]}"
    )
    assert fps >= FLOOR_FPS, (
        f"the simulator delivered {fps:.2f} fps at the reference strip, below "
        f"the {FLOOR_FPS:.0f} fps floor: the bench cannot measure the "
        f"{TARGET_FPS:.0f} fps budget against this source"
    )

    # Report the gap to the ADR target without failing the harness: the product
    # gate is where 120 fps is demanded, and it will demand it of source plus
    # engine. The gate report quotes this line.
    if fps < TARGET_FPS:
        print(
            f"NOTE: the simulator alone is {TARGET_FPS - fps:.2f} fps below the "
            f"ADR-013 target; the pipeline gate cannot pass until the source "
            f"is faster or the bench uses a pre-generated stream."
        )
