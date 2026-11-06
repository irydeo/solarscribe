############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui camera and engine wiring test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The follow-up that closed the demo-only gap: these tests prove the window now
# drives the real DeviceManager, CaptureEngine, SunCentering and ScanEngine
# instead of painting a fake. The simulator is still the camera, but it is a
# Camera contract behind the real pipeline, and the scene is coupled to the
# mount so the real centring maths can converge.

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import solarscribe.ui.engines as engines  # noqa: E402
from solarscribe.capture.abc import (  # noqa: E402
    RoiModel, StreamCounters, WriterCounters,
)
from solarscribe.config import store  # noqa: E402
from solarscribe.config.schema import (  # noqa: E402
    CameraData, Profile, RoiPreset, TelescopeData,
)
from solarscribe.devices.abc import RoiConstraints  # noqa: E402
from solarscribe.devices.manager import DeviceManagerImpl  # noqa: E402
from solarscribe.devices.sim.backend import SimCameraBackend  # noqa: E402
from solarscribe.shg.abc import (  # noqa: E402
    CenteringResult, DecCenterMethod, RowCounters,
)
from solarscribe.shg.engine import ScanEngineImpl  # noqa: E402
from solarscribe.ui.adapters import DisplayBridge, RowRecorderAdapter  # noqa: E402
from solarscribe.ui.camera_panel import CameraPanel  # noqa: E402
from solarscribe.ui.session import Session  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _manager(width=2000, height=220):
    return DeviceManagerImpl(
        camera_backends=[SimCameraBackend(width=width, height=height, fps=20,
                                          pattern="solar")],
        mount_backends=[],
    )


def _session(tmp_path, profile=None, demo=True):
    settings = store.default_settings()
    settings.values[("observatory", "latitude_deg")] = 40.0
    settings.values[("observatory", "longitude_deg")] = -3.0
    return Session(settings=settings, profile=profile or Profile(),
                   folder=tmp_path / "session", demo=demo,
                   settings_path=tmp_path / "config.ini",
                   profile_path=tmp_path / "profile.json")


def test_camera_panel_discovers_the_simulator_and_returns_it(qapp):
    manager = _manager()
    panel = CameraPanel(manager)
    panel.refresh_sync()
    assert panel.combo.count() == 1
    info = panel.current_info()
    assert info is not None
    assert info.backend == "sim"
    assert info.caps.roi.max_width == 2000

    chosen = []
    panel.cameraChosen.connect(lambda i, c: chosen.append((i, c)))
    panel._open()
    assert chosen and chosen[0][0].camera_id == info.camera_id
    assert chosen[0][1].info().caps.roi.max_width == 2000
    panel.set_current(info, simulated=True, streaming=True)
    assert "Simulator" in panel.state_label.text()
    panel.set_counters(StreamCounters(fps=19.0))
    assert "19" in panel.rate_value.text()


def test_preset_is_restored_when_a_camera_connects(qapp, tmp_path):
    profile = Profile(
        telescope=TelescopeData(),
        camera=CameraData(),
        roi_presets=(
            RoiPreset(name="default"),
            RoiPreset(name="wide", capture=(0, 0, 1200, 200),
                      band=(0, 40, 1200, 120)),
        ),
    )
    session = _session(tmp_path, profile=profile)
    # The named preset wins over the INI ROI keys when the camera connects.
    session.set_value("roi", "preset", "wide")
    manager = _manager()
    info = manager.cameras()[0]
    camera = manager.open_camera(info.camera_id)
    assert session.use_camera(camera, info)
    assert session.roi.capture == (0, 0, 1200, 200)
    assert session.roi.band == (0, 40, 1200, 120)
    assert session.has_camera()
    assert session.is_simulated()
    session.close_camera()


def test_apply_roi_calls_the_real_capture_engine(qapp, tmp_path):
    session = _session(tmp_path)
    harness = session.harness
    assert harness.start()
    calls = []
    original = harness.engine.configure

    def spy(camera, roi, params):
        calls.append((camera, roi.capture, roi.band, params.binning))
        return original(camera, roi, params)

    harness.engine.configure = spy
    session.set_roi((0, 0, 1200, 200), (0, 40, 1200, 120), persist=False)
    assert session.apply_roi()
    assert calls, "CaptureEngine.configure was never called"
    assert calls[-1][1] == (0, 0, 1200, 200)
    assert calls[-1][2] == (0, 40, 1200, 120)
    harness.engine.configure = original
    harness.stop()


def test_the_real_centering_service_is_used(qapp, tmp_path, monkeypatch):
    session = _session(tmp_path)
    harness = session.harness
    assert harness.start()
    used = []

    class FakeCentering:
        def __init__(self, mount, frames, **kwargs):
            used.append((mount, kwargs))

        def center(self, cb):
            return CenteringResult(ok=True, dec_offset_arcsec=1.2,
                                   method=DecCenterMethod.SYMMETRY,
                                   dead_zone_arcsec=0.0)

    monkeypatch.setattr(engines, "SunCenteringImpl", FakeCentering)
    done = []
    harness.centeringFinished.connect(done.append)
    assert harness.center_sun()
    for _ in range(200):
        qapp.processEvents()
        if done:
            break
        import time
        time.sleep(0.01)
    assert done and done[0].dec_offset_arcsec == pytest.approx(1.2)
    assert used and "band" in used[0][1] and "slit_arcsec" in used[0][1]
    harness.stop()


def test_the_real_scan_engine_is_constructed(qapp, tmp_path):
    session = _session(tmp_path)
    harness = session.harness
    assert harness.start()
    scan = harness._new_scan_engine()
    assert isinstance(scan, ScanEngineImpl)
    harness.stop()


def test_row_recorder_adapter_speaks_both_contracts(qapp, tmp_path):
    class FakeEngine:
        def __init__(self):
            self.header = None
            self.path = None
            self.stopped = False

        def start_recording(self, path, header):
            self.path, self.header = path, header

        def stop_recording(self):
            self.stopped = True
            return WriterCounters(frames_written=42,
                                  frames_dropped_queue=2,
                                  queue_high_water_mb=64.0)

        def counters(self):
            return StreamCounters(frames_received=50, frames_dropped_sdk=3,
                                  sequence_gaps=1, fps=19.0)

    model = RoiModel(capture=(0, 0, 3480, 248), band=(0, 40, 3480, 160),
                     constraints=RoiConstraints(max_width=3480,
                                                max_height=248))
    engine = FakeEngine()
    adapter = RowRecorderAdapter(engine, model, bit_depth=16)
    adapter.start_row(Path("/tmp/row.ser"))
    assert engine.header.width == 3480
    assert engine.header.height == 248
    assert engine.header.roi == (0, 0, 3480, 248)
    counters = adapter.stop_row()
    assert isinstance(counters, RowCounters)
    assert counters.frames_written == 42
    assert counters.frames_dropped_sdk == 3
    assert counters.sequence_gaps == 1


def test_sky_calendar_data_uses_the_real_ephemeris(qapp, tmp_path):
    session = _session(tmp_path, demo=False)
    info = session.sun_info()
    assert info["diameter_arcmin"] > 30.0
    assert 0.0 <= info["ra_hours"] < 24.0
    assert -24.0 < info["dec_deg"] < 24.0
    assert isinstance(info["rotation"], float)
    assert "B0" in info["heliographic"] and "L0" in info["heliographic"]


def test_display_bridge_keeps_only_the_newest_frame(qapp):
    bridge = DisplayBridge()
    bridge.push("old")
    bridge.push("new")
    assert bridge.take() == "new"
    assert bridge.take() is None
    assert bridge.replaced == 1
    assert bridge.pushed == 2
    assert bridge.taken == 1


def test_no_demo_starts_empty_and_can_attach_a_camera_later(qapp, tmp_path):
    session = _session(tmp_path, demo=False)
    assert not session.has_camera()
    manager = _manager()
    info = manager.cameras()[0]
    camera = manager.open_camera(info.camera_id)
    assert session.use_camera(camera, info)
    assert session.has_camera()
    assert session.is_simulated()
    session.close_camera()
    assert not session.has_camera()


def test_named_preset_is_restored_at_startup(qapp, tmp_path):
    profile = Profile(
        telescope=TelescopeData(),
        camera=CameraData(),
        roi_presets=(
            RoiPreset(name="default"),
            RoiPreset(name="wide", capture=(0, 0, 1200, 200),
                      band=(0, 40, 1200, 120)),
        ),
    )
    settings = store.default_settings()
    settings.values[("roi", "preset")] = "wide"
    session = Session(settings=settings, profile=profile,
                      folder=tmp_path / "session", demo=True,
                      settings_path=tmp_path / "config.ini",
                      profile_path=tmp_path / "profile.json")
    assert session.roi.capture == (0, 0, 1200, 200)
    assert session.roi.band == (0, 40, 1200, 120)
    session.close_camera()


def test_apply_roi_writes_the_edited_preset_back_to_the_profile(qapp, tmp_path):
    session = _session(tmp_path)
    assert session.has_camera()
    session.set_roi((0, 0, 1200, 200), (0, 40, 1200, 120), persist=False)
    assert session.apply_roi()
    saved = store.load_profile(tmp_path / "profile.json")
    preset = saved.preset("default")
    assert preset is not None
    assert preset.capture == (0, 0, 1200, 200)
    assert preset.band == (0, 40, 1200, 120)
    session.close_camera()
