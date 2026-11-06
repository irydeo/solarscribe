############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - cli main module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The two command modes of DESIGN.md 14: a dry run and a device diagnostic.
#
# Neither imports Qt. The CLI has to work over SSH on the observatory machine
# and in a CI job where there is no display, and the layer rule of ARCHITECTURE 1
# says cli may use the engines and the config but never needs the GUI.
#
# Dry run:
#   - reads the same INI and profile the GUI reads, with the same defaults;
#   - validates the ROI geometry and prints the findings in plain language;
#   - prints the plan it would hand to shg, without opening a camera, moving a
#     mount or writing a single file (DESIGN.md 14: rehersal, not a take).
#
# Diagnostics:
#   - prints where the config, the profile and the sessions live;
#   - reports whether the device layer is in this build, and says so plainly
#     instead of pretending a camera is missing;
#   - reports unknown INI keys, because a typo that is silently ignored is the
#     most expensive kind of configuration bug (ADR-024).
#
# Exit codes: 0 success, 1 the dry run found an error in the ROI geometry,
# 2 the command line itself was wrong.

from __future__ import annotations

import importlib.metadata
import importlib.util
import platform
from datetime import datetime
from pathlib import Path

import solarscribe
from solarscribe.capture.abc import RoiModel
from solarscribe.config import paths, store
from solarscribe.config.schema import SCAN_LOG_FILE, SESSION_STATE_FILE
from solarscribe.devices.abc import RoiConstraints

__all__ = ["diagnostics", "dry_run", "run"]

# The same generous fallback the UI uses before a camera connects: a dry run
# cannot know the sensor limits, so it catches geometry mistakes and leaves the
# SDK-specific checks to the ROI step once the camera is open.
FALLBACK_CONSTRAINTS = RoiConstraints(max_width=20000, max_height=20000)

USAGE = """SolarScribe: capture for the solar spectroheliograph

Usage:
  python -m solarscribe --dry-run [--settings FILE] [--profile FILE]
  python -m solarscribe --diagnostics
  python -m solarscribe gui

The GUI is the default mode; these two are the headless checks.
"""


# @args: argv - the arguments after the mode
# @return: 0 when the rehearsal is valid, 1 when the ROI cannot be scanned
def dry_run(argv: list[str]) -> int:
    settings_path = Path(_argument(argv, "--settings", str(paths.settings_path())))
    profile_path = Path(_argument(argv, "--profile", str(paths.profile_path())))
    session_arg = _argument(argv, "--session", "")

    settings = store.load_settings(settings_path)
    profile = store.load_profile(profile_path)

    capture = (
        int(settings.get("roi", "capture_x")),
        int(settings.get("roi", "capture_y")),
        int(settings.get("roi", "capture_width")),
        int(settings.get("roi", "capture_height")),
    )
    band = (
        int(settings.get("roi", "band_x")),
        int(settings.get("roi", "band_y")),
        int(settings.get("roi", "band_width")),
        int(settings.get("roi", "band_height")),
    )
    model = RoiModel(capture=capture, band=band,
                     constraints=FALLBACK_CONSTRAINTS,
                     binning=int(settings.get("camera", "binning")),
                     tilt_deg=float(settings.get("roi", "tilt_deg")),
                     tilt_px=float(settings.get("roi", "tilt_px")))

    # The dry run cannot estimate the rate (no camera, no readout speed), so the
    # LOW_RATE check is deliberately skipped: inventing a rate would be worse
    # than saying nothing.
    warnings = _validate(model, None)
    errors = [item for item in warnings if item.severity.value == "error"]

    print("DRY RUN: no camera is opened, no mount is moved, no file is written.")
    print(f"Settings: {settings_path}")
    print(f"Profile:  {profile_path}")
    if session_arg:
        print(f"Session:  {Path(session_arg)}")
    else:
        stamp = datetime.now().strftime(store.SESSION_FOLDER_FORMAT)
        print(f"Session:  {paths.default_session_base() / stamp} (would be created)")
    print(f"Optics:   focal {profile.telescope.focal_length_mm:.0f} mm, "
          f"slit {profile.telescope.slit_length_mm:.0f} mm")
    print(f"ROI:      capture {_rect(capture)} (sensor pixels)")
    print(f"          band    {_rect(band)} (frame pixels)")
    print(f"Tilt:     {model.tilt_deg:.2f} deg, {model.tilt_px:.1f} px of drift")
    rows = int(settings.get("scan", "rows"))
    print(f"Mode:     {'mosaic' if rows > 1 else 'simple'}, "
          f"{int(settings.get('scan', 'cycles'))} cycles, "
          f"{rows} row{'s' if rows != 1 else ''}")
    if int(settings.get("scan", "rate_arcsec_s")) > 0:
        print(f"Rate:     {float(settings.get('scan', 'rate_arcsec_s')):.2f} "
              f"arcsec/s (fixed in the INI)")
    else:
        print("Rate:     the engine calibrates it during preparation")
    print("")
    if warnings:
        print("Findings:")
        for warning in warnings:
            print(f"  [{warning.severity.value.upper()}] {_warning_text(warning)}")
    else:
        print("Findings: none. The geometry is consistent.")
    print("")
    print("The shg engine computes the real plan when the scan step runs; the "
          "dry run only checks what can be checked without hardware.")
    if errors:
        print("")
        print("Result: the ROI cannot be scanned until the errors above are fixed.")
        return 1
    print("Result: the dry run is valid.")
    return 0


# @args: argv - the arguments after the mode
# @return: 0 when the report could be produced, 2 on an unexpected failure
def diagnostics(argv: list[str]) -> int:
    settings_path = Path(_argument(argv, "--settings", str(paths.settings_path())))
    profile_path = Path(_argument(argv, "--profile", str(paths.profile_path())))
    settings = store.load_settings(settings_path)
    profile = store.load_profile(profile_path)

    try:
        pyside = importlib.metadata.version("PySide6")
    except importlib.metadata.PackageNotFoundError:
        pyside = "not installed"

    print(f"SolarScribe {solarscribe.__version__}")
    print(f"Python      {platform.python_version()} ({platform.platform()})")
    print(f"PySide6     {pyside}")
    print("")
    print(f"Config dir  {paths.config_dir()}")
    print(f"Data dir    {paths.data_dir()}")
    print(f"Log dir     {paths.log_dir()}")
    print(f"Settings    {settings_path} "
          f"({_exists(settings_path)})")
    print(f"Profile     {profile_path} ({_exists(profile_path)})")
    print(f"Sessions    {paths.default_session_base()}")
    print(f"State file  {SESSION_STATE_FILE}")
    print(f"Scan log    {SCAN_LOG_FILE}")
    print("")
    print(f"Optics      focal {profile.telescope.focal_length_mm:.0f} mm, "
          f"slit {profile.telescope.slit_length_mm:.0f} mm, "
          f"pixel {profile.camera.pixel_size_um:.2f} um")
    print(f"Presets     {len(profile.roi_presets)} ROI preset(s): "
          f"{', '.join(preset.name for preset in profile.roi_presets)}")
    print(f"Last ROI    {_rect((int(settings.get('roi', 'capture_x')), int(settings.get('roi', 'capture_y')), int(settings.get('roi', 'capture_width')), int(settings.get('roi', 'capture_height'))))}")
    print("")
    present = importlib.util.find_spec("solarscribe.devices.manager") is not None
    if not present:
        print("Device layer: not in this build. No camera or mount can be "
              "opened; the GUI runs the simulator so the interface is usable.")
    else:
        print("Device layer: present. Probing the backends now:")
        _print_devices()
    print("Network:     no telemetry. The only optional network use is the SDO "
          "image in the sky calendar, off by default (ADR-021).")
    if settings.unknown:
        print("")
        print("WARNING: these INI keys are not in the schema and will be ignored:")
        for name in settings.unknown:
            print(f"  {name}")
    else:
        print("Unknown INI keys: none.")
    return 0


# @args: none. Lists the backends and the devices found, with the reason when a
#        backend is not usable (ADR-014: say what is missing)
def _print_devices() -> None:
    try:
        from solarscribe.devices.manager import default_manager
        manager = default_manager()
        for backend in manager.backends():
            state = "available" if backend.available else f"unavailable: {backend.reason.value}"
            print(f"  {backend.kind.value:6s} {backend.name:20s} {state}")
            if backend.detail and not backend.available:
                print(f"         {backend.detail}")
        cameras = manager.cameras()
        mounts = manager.mounts()
        print("Cameras found: " + (", ".join(
            f"{camera.camera_id} ({camera.model})" for camera in cameras)
            or "none"))
        print("Mounts found:  " + (", ".join(
            f"{mount.mount_id} ({mount.name})" for mount in mounts) or "none"))
    except Exception as error:  # noqa: BLE001 - a probe may fail in any way
        # The diagnostic must report the failure and still exit usable; the
        # observer can paste this line into a report.
        print(f"  probe failed: {type(error).__name__}: {error}")


# @args: argv - the full argument list, with the mode already checked
# @return: the process exit code
def run(argv: list[str]) -> int:
    if "--dry-run" in argv:
        return dry_run(_without_mode(argv, "--dry-run"))
    if "--diagnostics" in argv:
        return diagnostics(_without_mode(argv, "--diagnostics"))
    print(USAGE)
    return 2


# @args: argv - the arguments; mode - the flag to remove
# @return: the list without the mode flag
def _without_mode(argv: list[str], mode: str) -> list[str]:
    return [item for item in argv if item != mode]


# @args: args - the arguments; name - the option; default - the fallback
# @return: the option's value
def _argument(args: list[str], name: str, default: str) -> str:
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    for item in args:
        if item.startswith(name + "="):
            return item.split("=", 1)[1]
    return default


# @args: roi - a rectangle
# @return: "x, y, width x height"
def _rect(roi) -> str:
    x, y, width, height = roi
    return f"{int(x)}, {int(y)}, {int(width)} x {int(height)}"


# @args: path - a file
# @return: "found" or "missing"
def _exists(path: Path) -> str:
    return "found" if path.is_file() else "missing"


# @args: model - the ROI model; fps - estimated rate or None
# @return: the findings, from capture/roi.py when present, otherwise from the
#          UI's documented fallback (which is the same list of issues)
def _validate(model: RoiModel, fps: float | None):
    try:
        from solarscribe.capture.roi import validate_roi  # type: ignore
    except (ImportError, AttributeError):
        from solarscribe.ui.roi_checks import validate_roi_model
        return validate_roi_model(model, fps)
    try:
        return list(validate_roi(model, fps=fps))
    except TypeError:
        return list(validate_roi(model))


# @args: warning - a RoiWarning
# @return: a plain sentence with its numbers. The CLI prints the same meaning
#          the dialog shows, so a bug report pasted from a terminal is readable
def _warning_text(warning) -> str:
    issue = warning.issue.value
    args = warning.args
    if issue == "band_clipped":
        end = args.get("band_x", 0) + args.get("band_width",
                                              args.get("band_w", 0))
        frame_w = args.get("frame_width", args.get("frame_w", 0))
        return (f"the band ends at {int(end)} but the frame is "
                f"{int(frame_w)} px wide; the order would be clipped")
    if issue == "tilt_height":
        height = args.get("capture_height", args.get("height", 0))
        return (f"the ROI is {int(height)} px tall but needs "
                f"{int(args.get('needed', 0))} (band {int(args.get('band_height', 0))} + "
                f"tilt {round(float(args.get('tilt_px', 0.0)), 1)} + "
                f"{int(args.get('margin', 0))} margin)")
    if issue == "sdk_multiple":
        if "axis" in args:
            return (f"{args.get('axis', 'width')} {int(args.get('value', 0))} is not "
                    f"a multiple of {int(args.get('multiple', 1))}; the driver would "
                    f"reject the ROI")
        return (f"the camera needs widths multiple of "
                f"{int(args.get('width_multiple', 1))} and heights multiple of "
                f"{int(args.get('height_multiple', 1))}; "
                f"{int(args.get('width', 0))} x {int(args.get('height', 0))} does "
                f"not fit")
    if issue == "sdk_bounds":
        if "right" in args:
            return (f"the ROI ends at ({int(args.get('right', 0))}, "
                    f"{int(args.get('bottom', 0))}) outside the "
                    f"{int(args.get('max_width', 0))} x {int(args.get('max_height', 0))} "
                    f"sensor")
        return (f"the ROI is {int(args.get('width', 0))} x "
                f"{int(args.get('height', 0))} on a "
                f"{int(args.get('max_width', 0))} x {int(args.get('max_height', 0))} "
                f"sensor")
    if issue == "binning_mismatch":
        if "from_binning" in args:
            return (f"the rectangles are at binning "
                    f"{int(args.get('from_binning', 0))} but the camera is at "
                    f"{int(args.get('to_binning', 0))}")
        return (f"the rectangles do not match the camera's binning "
                f"({int(args.get('binning', 1))})")
    if issue == "low_rate":
        return (f"{int(args.get('fps', 0))} fps is below the "
                f"{int(args.get('target_fps', args.get('target', 120)))} fps target")
    if issue == "slit_off_centre":
        offset = abs(args.get("offset_px", args.get("offset", 0)))
        return f"the slit is {int(offset)} px off the ROI centre"
    return "the ROI needs a check"
