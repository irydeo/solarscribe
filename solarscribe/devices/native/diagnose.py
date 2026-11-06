############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native diagnose module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Hardware diagnostic for the native camera SDKs (ADR-002, ADR-013).
#
# This is the tool the observer runs when a camera does not appear or the
# stream misbehaves. It prints what the SDK really says, not what the driver
# hopes: sensor size, measured ROI alignment, option write behaviour, frames
# per second and the SDK drop counter. A number without its explanation is
# useless (AGENTS.md), so every line says what it means and why it matters.
#
# Usage:
#   python -m solarscribe.devices.native.diagnose touptek
#   python -m solarscribe.devices.native.diagnose asi --frames 60
#   python -m solarscribe.devices.native.diagnose all
#
# The camera must not be open in another application: the SDK will report a
# busy device and the report will say so. Nothing is recorded and no setting is
# left changed (the ROI and options are restored where the SDK allows it).

from __future__ import annotations

import argparse
import sys
import threading
import time

from solarscribe.devices.abc import DeviceError, Param
from solarscribe.devices.native.loader import load_library

__all__ = ["main", "run_backend"]

BACKENDS = ("touptek", "asi", "qhy", "playerone")


# @args: argv - command line arguments, or None for sys.argv
# @return: process exit code: 0 when every requested backend was exercised,
#          1 when a library, a camera or a frame was missing
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m solarscribe.devices.native.diagnose",
        description=(
            "Measure a real camera through SolarScribe's native driver and "
            "print the sensor geometry, the options and the stream rate."
        ),
    )
    parser.add_argument(
        "backend", choices=BACKENDS + ("all",),
        help="which SDK to diagnose (all = every installed one)",
    )
    parser.add_argument(
        "--index", type=int, default=0,
        help="camera index when the SDK sees more than one (default 0)",
    )
    parser.add_argument(
        "--frames", type=int, default=30,
        help="frames to stream for the rate measurement (default 30)",
    )
    args = parser.parse_args(argv)

    names = BACKENDS if args.backend == "all" else (args.backend,)
    status = 0
    for name in names:
        print()
        print(f"### {name}")
        if not run_backend(name, args.index, args.frames):
            status = 1
    return status


# @args: name - "touptek", "asi", "qhy" or "playerone"
#        index - camera index
#        frames - frames to stream
# @return: True when the backend was exercised, False when it was missing
def run_backend(name: str, index: int, frames: int) -> bool:
    if name == "touptek":
        return _run_touptek(index, frames)
    if name == "asi":
        return _run_asi(index, frames)
    if name == "qhy":
        return _run_qhy(index, frames)
    if name == "playerone":
        return _run_playerone(index, frames)
    return False


# @args: index - camera index; frames - frames to stream
# @return: True when a camera answered
def _run_touptek(index: int, frames: int) -> bool:
    from solarscribe.devices.native.touptek import (
        LIBRARIES, diagnose, format_report,
    )

    library = load_library(LIBRARIES)
    if library is None:
        print("libtoupcam not found: install the Touptek SDK or place the "
              "library next to the app (ADR-014: the backend simply stays "
              "absent).")
        return False
    report = diagnose(library, index=index, frames=frames)
    print(format_report(report))
    return "sensor" in report and not report.get("errors")


# @args: index - camera index; frames - frames to stream
# @return: True when a camera answered
def _run_asi(index: int, frames: int) -> bool:
    from solarscribe.devices.native.zwo import AsiCamera, LIBRARIES

    library = load_library(LIBRARIES)
    if library is None:
        print("libASICamera2 not found: install the ZWO SDK (ADR-014).")
        return False
    cameras = AsiCamera.discover(library)
    if not cameras:
        print("the SDK loaded but reports no ASI camera: check the USB cable "
              "and that no other program has the camera open.")
        return False
    for info in cameras:
        print(f"found {info.camera_id}: {info.model}, "
              f"{info.caps.roi.max_width} x {info.caps.roi.max_height} px, "
              f"{'colour' if info.caps.is_color else 'mono'}")
    return _measure(AsiCamera(cameras[min(index, len(cameras) - 1)].camera_id,
                              library=library), frames, "ASI")


# @args: index - camera index; frames - frames to stream
# @return: True when a camera answered
def _run_qhy(index: int, frames: int) -> bool:
    from solarscribe.devices.native.qhy import LIBRARIES, QhyCamera

    library = load_library(LIBRARIES)
    if library is None:
        print("libqhyccd not found: install the QHY SDK (ADR-014).")
        return False
    cameras = QhyCamera.discover(library)
    if not cameras:
        print("the SDK loaded but reports no QHY camera: check the USB cable "
              "and the SDK's udev rules.")
        return False
    for info in cameras:
        print(f"found {info.camera_id} (the sensor size is read on open, "
              "because opening during discovery breaks the QHY USB state)")
    return _measure(QhyCamera(cameras[min(index, len(cameras) - 1)].camera_id,
                              library=library), frames, "QHY")


# @args: index - camera index; frames - frames to stream
# @return: True when a camera answered
def _run_playerone(index: int, frames: int) -> bool:
    from solarscribe.devices.native.playerone import (
        LIBRARIES, PlayerOneCamera,
    )

    library = load_library(LIBRARIES)
    if library is None:
        print("libPlayerOneCamera not found: install the Player One SDK "
              "(ADR-014).")
        return False
    cameras = PlayerOneCamera.discover(library)
    if not cameras:
        print("the SDK loaded but reports no Player One camera: check the USB "
              "cable and the SDK's udev rules.")
        return False
    for info in cameras:
        print(f"found {info.camera_id}: {info.model}, "
              f"{info.caps.roi.max_width} x {info.caps.roi.max_height} px, "
              f"{'colour' if info.caps.is_color else 'mono'}")
    return _measure(
        PlayerOneCamera(cameras[min(index, len(cameras) - 1)].camera_id,
                        library=library), frames, "Player One",
    )


# @args: cam - an unopened Camera; frames - how many to wait for
#        label - brand name for the output
# @return: True when at least one frame arrived
def _measure(cam, frames: int, label: str) -> bool:
    timestamps: list[float] = []

    # @args: frame - one delivered frame
    # @return: none
    def on_frame(frame) -> None:
        timestamps.append(frame.timestamp)

    try:
        cam.open()
    except DeviceError as exc:
        print(f"could not open {label}: {exc.code}: {exc}")
        return False
    try:
        info = cam.info()
        print(f"after open: {info.caps.roi.max_width} x "
              f"{info.caps.roi.max_height} px, "
              f"{info.caps.bit_depths[0]} bit, "
              f"{'colour' if info.caps.is_color else 'mono'}")
        try:
            area = cam.effective_area()
            cam.set_roi(area)
        except DeviceError as exc:
            print(f"ROI refused ({exc.code}); streaming the sensor default")
        try:
            cam.set_param(Param.EXPOSURE, 5000)
            cam.set_param(Param.GAIN, 0)
        except DeviceError as exc:
            print(f"could not set exposure/gain ({exc.code}); the SDK default "
                  "is used")
        try:
            cam.start_stream(on_frame)
            deadline = time.monotonic() + max(10.0, frames / 5.0)
            while len(timestamps) < frames and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            cam.stop_stream()
        span = (timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0.0
        fps = (len(timestamps) - 1) / span if span > 0 else 0.0
        print(f"stream: {len(timestamps)} frames in {span:.3f} s = "
              f"{fps:.2f} fps (what the app will get with this ROI and "
              "exposure)")
        print(f"SDK drop counter: {cam.dropped_frames()} "
              "(the SDK's own count; a nonzero value means the link is losing "
              "frames before Python sees them)")
        return bool(timestamps)
    finally:
        try:
            cam.close()
        except Exception:  # noqa: BLE001 - closing a dead camera is harmless
            pass


if __name__ == "__main__":
    sys.exit(main())
