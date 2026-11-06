############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - device manager test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# DeviceManager discovery and degradation (ADR-012, ADR-014). The point is not
# that the simulators work (test_devices_sim.py covers that) but that an absent
# SDK removes only its own backend and that open_* returns an unopened device.

import pytest

from solarscribe.devices.abc import (
    BackendReason, Camera, DeviceError, DeviceKind, DeviceManager, Mount,
)
from solarscribe.devices.manager import DeviceManagerImpl
from solarscribe.devices.mount.backend import MountBackend
from solarscribe.devices.native import native_camera_backends
from solarscribe.devices.sim.backend import SimCameraBackend, SimMountBackend


def _sim_only_manager():
    return DeviceManagerImpl(
        camera_backends=[SimCameraBackend()],
        mount_backends=[SimMountBackend()],
    )


def test_manager_satisfies_the_contract():
    assert isinstance(_sim_only_manager(), DeviceManager)


def test_simulator_cameras_and_mounts_are_discovered():
    manager = _sim_only_manager()
    backends = manager.backends()
    assert {(b.name, b.kind) for b in backends} == {
        ("sim", DeviceKind.CAMERA), ("sim", DeviceKind.MOUNT),
    }
    assert all(b.available and b.reason is BackendReason.AVAILABLE
               for b in backends)

    cameras = manager.cameras()
    assert [c.camera_id for c in cameras] == ["sim:0"]
    mounts = manager.mounts()
    assert [m.mount_id for m in mounts] == ["sim:mount0"]

    camera = manager.open_camera("sim:0")
    mount = manager.open_mount("sim:mount0")
    assert isinstance(camera, Camera)
    assert isinstance(mount, Mount)
    # open_* returns them UNOPENED: the caller decides (ARCHITECTURE 2.1).
    assert not camera.is_open()
    assert not mount.is_connected()


def test_missing_native_sdk_hides_only_its_own_cameras():
    manager = DeviceManagerImpl(
        camera_backends=native_camera_backends(loader=lambda names: None)
        + [SimCameraBackend()],
        mount_backends=[SimMountBackend()],
    )
    infos = manager.backends()
    native = [b for b in infos if b.kind is DeviceKind.CAMERA and b.name != "sim"]
    assert len(native) == 4
    assert all(not b.available and b.reason is BackendReason.SDK_MISSING
               for b in native)
    # The simulator still works: that is the graceful degradation.
    assert [c.camera_id for c in manager.cameras()] == ["sim:0"]


def test_a_backend_that_raises_during_probe_is_an_error_not_a_crash():
    class Broken:
        name = "broken"
        kind = DeviceKind.CAMERA

        def probe(self):
            raise RuntimeError("boom")

        def cameras(self):
            return []

        def create(self, camera_id):
            raise AssertionError("must not be called")

    manager = DeviceManagerImpl(
        camera_backends=[Broken(), SimCameraBackend()],
        mount_backends=[SimMountBackend()],
    )
    broken = manager.backends()[0]
    assert broken.name == "broken"
    assert not broken.available
    assert broken.reason is BackendReason.ERROR
    assert "boom" in broken.detail
    assert [c.camera_id for c in manager.cameras()] == ["sim:0"]


def test_unknown_ids_raise_a_device_error_with_a_stable_code():
    manager = _sim_only_manager()
    with pytest.raises(DeviceError) as exc:
        manager.open_camera("nope")
    assert exc.value.code == "unknown_camera"
    with pytest.raises(DeviceError) as exc:
        manager.open_mount("nope")
    assert exc.value.code == "unknown_mount"


def test_discovery_is_cached_so_the_health_panel_is_cheap():
    class Counting(SimCameraBackend):
        def __init__(self):
            super().__init__()
            self.probes = 0
            self.enumerations = 0

        def probe(self):
            self.probes += 1
            return super().probe()

        def cameras(self):
            self.enumerations += 1
            return super().cameras()

    backend = Counting()
    manager = DeviceManagerImpl(
        camera_backends=[backend], mount_backends=[SimMountBackend()],
    )
    manager.cameras()
    manager.cameras()
    manager.backends()
    manager.backends()
    assert backend.probes == 1
    assert backend.enumerations == 1


def test_mount_backend_availability_controls_its_mounts():
    def probe_unavailable():
        return BackendReason.SERVER_MISSING, "no server"

    backend = MountBackend(
        "indi", probe_unavailable,
        lambda: (_ for _ in ()).throw(AssertionError("must not enumerate")),
        lambda mount_id: None,
    )
    manager = DeviceManagerImpl(
        camera_backends=[SimCameraBackend()],
        mount_backends=[backend, SimMountBackend()],
    )
    infos = manager.backends()
    indi = next(b for b in infos if b.name == "indi")
    assert indi.reason is BackendReason.SERVER_MISSING
    assert [m.mount_id for m in manager.mounts()] == ["sim:mount0"]


def test_missing_indigo_server_hides_only_its_own_mount(monkeypatch):
    # ADR-019: INDIGO is an optional path. A missing indigo_server must report
    # SERVER_MISSING and leave the simulator (and every other backend) working.
    from solarscribe.devices.mount import default_mount_backends

    def refuse(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr("socket.create_connection", refuse)
    manager = DeviceManagerImpl(
        camera_backends=[SimCameraBackend()],
        mount_backends=default_mount_backends(),
    )
    infos = manager.backends()
    indigo = next(b for b in infos if b.name == "indigo")
    assert not indigo.available
    assert indigo.reason is BackendReason.SERVER_MISSING
    ids = [m.mount_id for m in manager.mounts()]
    assert "sim:mount0" in ids
    assert not any(mount_id.startswith("indigo:") for mount_id in ids)
