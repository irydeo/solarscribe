############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - hardware validation test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Real-hardware tests for the camera and mount layers (ADR-002, ADR-019).
#
# Every test is marked `hardware` and skips when the SDK, the camera or the
# server is absent: the gate must be runnable on a machine without hardware and
# must never turn a missing device into a failure. Run it with -s to see the
# diagnostic output:
#
#   .venv/bin/python -m pytest tests/functional/test_devices_hardware.py -q -s
#
# The detailed Touptek report is also available as a standalone command:
#
#   .venv/bin/python -m solarscribe.devices.native.diagnose touptek
#
# What each test proves, and what it cannot: the Touptek tests exercise the
# reference G3M678M end to end (enumeration, open, ROI alignment, options, a
# stream with fps and the SDK drop counter). The ZWO, QHY and Player One tests
# only enumerate and open/close, because those cameras were not attached to the
# validation machine; they prove the library loads and the signatures do not
# truncate a handle, not that the stream is correct on that brand. The mount
# tests connect and disconnect without moving the telescope.

import pytest

pytestmark = pytest.mark.hardware


# @args: names - loader candidate names
# @return: the CDLL or None, without raising
def _library(names):
    from solarscribe.devices.native.loader import load_library

    return load_library(names)


def test_touptek_library_enumerates_opens_and_closes():
    from solarscribe.devices.native.touptek import (
        LIBRARIES, CtypesToupcamSdk, TouptekCamera,
    )

    library = _library(LIBRARIES)
    if library is None:
        pytest.skip("libtoupcam is not installed")
    devices = CtypesToupcamSdk.enumerate(library)
    if not devices:
        pytest.skip("libtoupcam loaded but no Touptek camera is attached")
    print(f"\ntouptek: {len(devices)} device(s)")
    for device in devices:
        print(f"  index {device.index}: {device.display_name} "
              f"id={device.device_id!r}")
        sdk = CtypesToupcamSdk(library, device.index)
        sdk.open()
        try:
            width, height = sdk.size()
            print(f"  sensor: {width} x {height} px")
            assert width > 0 and height > 0
        finally:
            sdk.close()
    # Discovery opens and closes each camera; it must survive the same path the
    # "Find cameras" button uses.
    infos = TouptekCamera.discover(library)
    assert infos
    for info in infos:
        print(f"  discover: {info.camera_id} {info.model}")


def test_touptek_g3m678m_diagnostic():
    from solarscribe.devices.native.touptek import (
        LIBRARIES, diagnose, format_report,
    )

    library = _library(LIBRARIES)
    if library is None:
        pytest.skip("libtoupcam is not installed")
    report = diagnose(library, index=0, frames=30)
    text = format_report(report)
    # Print before asserting: when the camera is there but something fails, the
    # observer needs the whole report, not only the assertion message.
    print("\n" + text)
    assert "sensor" in report, "the SDK did not report a sensor size"
    assert not report.get("errors"), f"SDK errors: {report['errors']}"
    stream = report.get("stream") or {}
    assert stream.get("frames", 0) > 0, "no frame arrived; check USB and exposure"
    assert stream.get("fps", 0.0) > 0.0, "fps must be positive"
    # The reference camera is the G3M678M: 3840x2160. If a different Touptek
    # camera is attached the test still reports its real size instead of failing
    # on a hard-coded geometry.
    print(f"measured fps: {stream['fps']:.2f}; "
          f"SDK drops: {stream['dropped_sdk']}")


def test_zwo_library_enumerates_and_opens():
    from solarscribe.devices.native.zwo import AsiCamera, LIBRARIES

    library = _library(LIBRARIES)
    if library is None:
        pytest.skip("libASICamera2 is not installed")
    infos = AsiCamera.discover(library)
    if not infos:
        pytest.skip("libASICamera2 loaded but no ASI camera is attached")
    for info in infos:
        print(f"\nasi: {info.camera_id} {info.model} "
              f"{info.caps.roi.max_width} x {info.caps.roi.max_height}")
        camera = AsiCamera(info.camera_id, library=library)
        camera.open()
        try:
            after = camera.info()
            print(f"  after open: {after.caps.roi.max_width} x "
                  f"{after.caps.roi.max_height}")
        finally:
            camera.close()


def test_qhy_library_enumerates_and_opens():
    from solarscribe.devices.native.qhy import LIBRARIES, QhyCamera

    library = _library(LIBRARIES)
    if library is None:
        pytest.skip("libqhyccd is not installed")
    infos = QhyCamera.discover(library)
    if not infos:
        pytest.skip("libqhyccd loaded but no QHY camera is attached")
    for info in infos:
        print(f"\nqhy: {info.camera_id} {info.model} "
              "(sensor read on open)")
        camera = QhyCamera(info.camera_id, library=library)
        camera.open()
        try:
            after = camera.info()
            print(f"  after open: {after.caps.roi.max_width} x "
                  f"{after.caps.roi.max_height}")
        finally:
            camera.close()


def test_playerone_library_enumerates_and_opens():
    from solarscribe.devices.native.playerone import (
        LIBRARIES, PlayerOneCamera,
    )

    library = _library(LIBRARIES)
    if library is None:
        pytest.skip("libPlayerOneCamera is not installed")
    infos = PlayerOneCamera.discover(library)
    if not infos:
        pytest.skip("libPlayerOneCamera loaded but no Player One camera attached")
    for info in infos:
        print(f"\nplayerone: {info.camera_id} {info.model} "
              f"{info.caps.roi.max_width} x {info.caps.roi.max_height}")
        camera = PlayerOneCamera(info.camera_id, library=library)
        camera.open()
        try:
            after = camera.info()
            print(f"  after open: {after.caps.roi.max_width} x "
                  f"{after.caps.roi.max_height}")
        finally:
            camera.close()


def test_indi_server_connects_and_disconnects():
    from solarscribe.devices.abc import BackendReason
    from solarscribe.devices.mount.indi import IndiMount, probe_indi

    reason, detail = probe_indi()
    if reason is not BackendReason.AVAILABLE:
        pytest.skip(f"no indiserver: {detail}")
    mount = IndiMount()
    print(f"\nindi: connecting to {mount.info().name}")
    mount.connect()
    try:
        print(f"  connected; position: {_safe_position(mount)}")
    finally:
        mount.close()


def test_indigo_server_connects_and_disconnects():
    from solarscribe.devices.abc import BackendReason
    from solarscribe.devices.mount.indigo import (
        IndigoMount, probe_indigo,
    )

    reason, detail = probe_indigo()
    if reason is not BackendReason.AVAILABLE:
        pytest.skip(f"no indigo_server: {detail}")
    mount = IndigoMount()
    print(f"\nindigo: connecting to {mount.device}")
    mount.connect()
    try:
        print(f"  connected; position: {_safe_position(mount)}")
    finally:
        mount.close()


# @args: mount - a connected Mount
# @return: the position, or a sentence when the mount has not reported one yet
def _safe_position(mount) -> str:
    from solarscribe.devices.abc import DeviceError

    try:
        ra, dec = mount.position()
        return f"RA {ra:.5f} h, Dec {dec:.4f} deg"
    except DeviceError as exc:
        return f"not reported yet ({exc.code})"


def test_ascom_platform_enumerates_and_connects():
    # Windows only: the probe reports OS_UNSUPPORTED elsewhere. Connecting and
    # disconnecting does not move the telescope; the test never slews.
    from solarscribe.devices.abc import BackendReason
    from solarscribe.devices.mount.ascom import backend, probe_ascom

    reason, detail = probe_ascom()
    if reason is not BackendReason.AVAILABLE:
        pytest.skip(f"ASCOM not available: {reason.value}: {detail}")
    driver = backend()
    mounts = driver.mounts()
    if not mounts:
        pytest.skip("no ASCOM telescope driver is registered")
    for info in mounts:
        print(f"\nascom: {info.mount_id} {info.name}")
    mount = driver.create(mounts[0].mount_id)
    mount.connect()
    try:
        print(f"  connected; position: {_safe_position(mount)}")
        caps = mount.capabilities()
        print(f"  axis rates: {caps.supports_axis_rates}; "
              f"rate range {caps.min_rate_arcsec_s:.3f} to "
              f"{caps.max_rate_arcsec_s:.1f} arcsec/s")
    finally:
        mount.close()
