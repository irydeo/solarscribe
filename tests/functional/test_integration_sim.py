############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - simulator integration functional test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The end-to-end path the window wires, proved without Qt (ADR-005, ADR-015).
#
# The UI does not own business logic: it discovers a camera with
# DeviceManagerImpl, opens it, configures the real CaptureEngineImpl, and hands
# the same objects to SunCenteringImpl and ScanEngineImpl. This test composes
# exactly that chain through the public contracts, so a break in any of the four
# boundaries fails here before it reaches a user:
#
#   discovery -> open -> configure -> centring -> scan -> quick recon
#
# The simulator is the physical fixture: SimCamera(pattern="solar") draws a disk
# that follows the mount, so the real centring loop and the real limb stop have
# something to measure. The scan is a short sweep at 900"/s to keep the test
# inside a few seconds; the science is the same as in the reference scan.

import math
import time

import pytest

from solarscribe.capture.abc import CaptureParams, RoiModel
from solarscribe.capture.engine import CaptureEngineImpl
from solarscribe.devices.abc import BackendReason, Camera, Mount
from solarscribe.devices.manager import DeviceManagerImpl
from solarscribe.devices.sim.backend import SimCameraBackend, SimMountBackend
from solarscribe.devices.sim.frame import SolarPattern
from solarscribe.shg.abc import DecCenterMethod, ScanConfig, ScanStatus
from solarscribe.shg.centering import SunCenteringImpl
from solarscribe.shg.engine import ScanEngineImpl
from solarscribe.shg.recon import quick_recon

pytestmark = [pytest.mark.functional, pytest.mark.sim, pytest.mark.slow]

# Geometry of the solar simulator and of the reference optics. 0.5778"/px is
# the SHG-700 slit scale; 1920" is the solar diameter those pixels subtend.
SUN_RA_HOURS = 12.0
SUN_DEC_DEG = 0.0
SOLAR_DIAMETER_ARCSEC = 1920.0
SLIT_ARCSEC_PX = 0.5778
SLIT_ARCSEC = 2022.0
SIM_FPS = 60.0
SCAN_RATE_ARCSEC_S = 900.0

# The centring starts 20" north of the slit. It is enough for the symmetry loop
# to have work to do, and small enough that the fine stage converges in a few
# frames; the coarse histogram stage has its own unit tests.
CENTERING_OFFSET_ARCSEC = 20.0


# @args: none
# @return: the RA where the sweep must start to see the leading limb first
def _leading_limb_ra() -> float:
    return SUN_RA_HOURS + (SOLAR_DIAMETER_ARCSEC / 2.0) / (
        54000.0 * math.cos(math.radians(SUN_DEC_DEG))
    )


def test_discovery_to_recon_runs_end_to_end_on_the_solar_simulator():
    # The manager is the same class the window builds: the injected backends
    # only choose the simulator size and pattern, which is what the app's
    # default sim backend offers with pattern="solar" in the integrated build.
    manager = DeviceManagerImpl(
        camera_backends=[SimCameraBackend(
            pattern="solar", fps=SIM_FPS,
            solar=SolarPattern(sun_ra_hours=SUN_RA_HOURS,
                               sun_dec_deg=SUN_DEC_DEG),
        )],
        mount_backends=[SimMountBackend(
            # Centring starts with the disk near the slit centre: the symmetry
            # stage measures a full chord, which is how the Find step runs. The
            # sweep then moves to the leading limb explicitly, below.
            ra_hours=SUN_RA_HOURS,
            dec_deg=SUN_DEC_DEG
            + CENTERING_OFFSET_ARCSEC / 3600.0,
        )],
    )

    # Discovery: the simulator is a first-class backend, always available.
    sim_backends = [item for item in manager.backends() if item.name == "sim"]
    assert {item.kind.value for item in sim_backends} == {"camera", "mount"}
    for info in sim_backends:
        assert info.available, info.reason
        assert info.reason is BackendReason.AVAILABLE

    cameras = manager.cameras()
    mounts = manager.mounts()
    assert cameras and cameras[0].backend == "sim"
    assert mounts and mounts[0].backend == "sim"

    # open: the manager returns the device unopened; the caller decides.
    camera = manager.open_camera(cameras[0].camera_id)
    mount = manager.open_mount(mounts[0].mount_id)
    assert isinstance(camera, Camera)
    assert isinstance(mount, Mount)
    assert not camera.is_open()

    mount.connect()
    camera.bind_mount(mount)        # the solar disk follows the mount
    camera.open()
    assert camera.is_open()

    try:
        # The solar pattern renders the reference strip; the ROI and the band
        # are the ones the ROI step would hand to the engines.
        capture = camera.effective_area()
        assert (capture[2], capture[3]) == (3480, 248)
        roi = RoiModel(
            capture=capture,
            band=(0, 40, 3480, 160),
            constraints=camera.info().caps.roi,
        )

        # configure: the real engine opens the stream and owns the counters.
        engine = CaptureEngineImpl(start_timeout_s=5.0)
        engine.configure(
            camera, roi,
            CaptureParams(auto_exposure=False, queue_budget_mb=64.0),
        )
        engine.start()
        try:
            # Let the first frames land before measuring; the centring service
            # waits for a fresh frame after each move, but a cold stream would
            # spend its timeout doing nothing useful.
            time.sleep(0.3)
            assert engine.counters().frames_received > 0

            # 1. Centring: the real fine loop, on a disk 20" off the slit.
            centring = SunCenteringImpl(
                mount, engine,
                band=roi.band,
                slit_arcsec=SLIT_ARCSEC,
                solar_diameter_arcsec=SOLAR_DIAMETER_ARCSEC,
                slit_arcsec_px=SLIT_ARCSEC_PX,
                method=DecCenterMethod.SYMMETRY,
                coarse=False,
            )
            centred = centring.center(lambda _status: None)
            assert centred.ok, centred.reason_code
            assert centred.method is DecCenterMethod.SYMMETRY
            assert abs(centred.dec_offset_arcsec) <= 1.5
            _ra, dec = mount.position()
            assert abs(dec - SUN_DEC_DEG) * 3600.0 <= 1.5

            # 2. Scan: a real sweep. The mount goes back to the leading limb
            # because centring moves Dec and the sweep must cross the disk from
            # its edge; this is what the UI does between cycles.
            mount.slew(_leading_limb_ra(), SUN_DEC_DEG)
            scan = ScanEngineImpl(mount, engine)
            scan.set_optics(
                pixel_scale=SLIT_ARCSEC_PX,
                solar_diameter_arcsec=SOLAR_DIAMETER_ARCSEC,
                fps=SIM_FPS,
                slit_arcsec_px=SLIT_ARCSEC_PX,
            )
            scan.set_slit_arcsec(SLIT_ARCSEC)
            config = ScanConfig(
                capture=roi.capture,
                band=roi.band,
                analysis={"limb": roi.band},
                rate_arcsec_s=SCAN_RATE_ARCSEC_S,
                padding_s=0.2,
                adaptive_stop=True,
            )
            plan = scan.plan(config)

            # 3. Recon input: the frames the capture engine actually delivered
            # during the sweep. A cap keeps the test's memory bounded; the real
            # UI paints a downsampled preview, not every frame.
            frames = []

            # @args: frame - one live frame from the capture engine
            def collect(frame):
                if len(frames) < 80:
                    frames.append(frame)

            engine.on_frame(collect)
            result = scan.run(plan, lambda _progress: None, recorder=None)

            assert result.status is ScanStatus.COMPLETED
            assert result.rows_completed == 1
            assert result.frames_written > 0
            assert result.reason_code == ""

            # 4. Recon: shg's light, screen-only preview over the real frames.
            recon = quick_recon([frames], band=roi.band)
            assert recon.ok, recon.reason_code
            assert recon.frames_used >= 20
            assert recon.image.size > 0
            assert recon.image.shape[1] == 256
            contrast = float(recon.image.max() - recon.image.min())
            assert contrast > 0.1, f"the recon has no contrast: {contrast}"
        finally:
            engine.stop()
    finally:
        camera.close()
        mount.close()
