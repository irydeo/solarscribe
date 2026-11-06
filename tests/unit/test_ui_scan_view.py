############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui scan view test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# ADR-020 asks for three things on screen: the captured strip, the slit line and
# the percentage. The percentage must be of the planned sweep, and the quick recon
# must be visibly non-authoritative. These tests pin both, plus the wiring from
# ScanProgress to the widget.

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QProgressBar  # noqa: E402

from solarscribe.config import store  # noqa: E402
from solarscribe.shg.recon import ReconResult  # noqa: E402
from solarscribe.shg.abc import (  # noqa: E402
    ScanProgress, ScanResult, ScanState, ScanStatus,
)
from solarscribe.ui.main_window import MainWindow  # noqa: E402
from solarscribe.ui.scan_view import ScanVisualisation  # noqa: E402
from solarscribe.ui.session import Session  # noqa: E402
from solarscribe.ui.sun_disc import QuickRecon  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _progress(value=0.42, state=ScanState.RUNNING):
    return ScanProgress(state=state, row=1, progress=value, frames_written=1234,
                        frames_dropped=2, ra_hours=12.0, dec_deg=-10.0,
                        dec_error_arcsec=0.4, elapsed_s=30.0)


def test_scan_view_turns_progress_into_geometry_and_a_word(qapp):
    view = ScanVisualisation()
    view.set_progress_from(_progress(0.42))
    assert view.percentage() == 42
    assert view.captured_fraction() == pytest.approx(0.42)
    view.set_rows(3)
    assert view.rows() == 3


def test_completed_result_says_what_finished(qapp):
    view = ScanVisualisation()
    result = ScanResult(status=ScanStatus.COMPLETED, frames_written=5000,
                        frames_dropped=0, duration_s=129.0, rate_arcsec_s=15.04,
                        rows_completed=1, dec_error_arcsec=0.3)
    view.set_result_from(result)
    assert view.percentage() == 100
    assert "Completed" in view.result()
    assert "5000" in view.result()


def test_aborted_result_preserves_the_frames(qapp):
    view = ScanVisualisation()
    result = ScanResult(status=ScanStatus.ABORTED, frames_written=900,
                        frames_dropped=0, duration_s=20.0, rate_arcsec_s=15.0,
                        rows_completed=0, dec_error_arcsec=0.0,
                        reason_code="aborted")
    view.set_result_from(result)
    assert "Stopped" in view.result()
    assert "kept" in view.result()


def test_failed_result_translates_the_reason_code(qapp):
    view = ScanVisualisation()
    result = ScanResult(status=ScanStatus.FAILED, frames_written=0,
                        frames_dropped=0, duration_s=0.0, rate_arcsec_s=0.0,
                        rows_completed=0, dec_error_arcsec=0.0,
                        reason_code="no_limb")
    view.set_result_from(result)
    assert "limb" in view.result()
    assert "no_limb" not in view.result()


def test_quick_recon_paints_the_shg_preview(qapp):
    recon = QuickRecon()
    assert not recon.has_image()
    # shg.quick_recon returns float32 in 0..1; the widget owns the 8-bit copy.
    image = np.linspace(0.0, 1.0, 64 * 96, dtype=np.float32).reshape(64, 96)
    recon.set_image(image)
    assert recon.has_image()
    painted = recon.image()
    assert painted is not None
    assert painted.width() == 96 and painted.height() == 64
    recon.clear()
    assert not recon.has_image()


def test_window_explains_each_recon_reason(qapp, tmp_path):
    settings = store.default_settings()
    session = Session(settings=settings, folder=tmp_path / "session", demo=False,
                      autosave=True, settings_path=tmp_path / "config.ini",
                      profile_path=tmp_path / "profile.json")
    window = MainWindow(session, show_welcome=False)
    message = window.findChild(QLabel, "reconMessage")

    window._on_recon_result(ReconResult(
        False, np.zeros((0, 0), dtype=np.float32), 0, 0, 0, 0, "no_frames"))
    assert "No frames" in message.text()
    window._on_recon_result(ReconResult(
        False, np.zeros((0, 0), dtype=np.float32), 0, 0, 0, 0, "band_empty"))
    assert "band" in message.text().lower()
    window._on_recon_result(ReconResult(
        True, np.zeros((32, 32), dtype=np.float32), 32, 32, 10, 1,
        "low_contrast"))
    assert "contrast" in message.text().lower()

    image = np.ones((32, 32), dtype=np.float32)
    window._on_recon_result(ReconResult(True, image, 32, 32, 120, 1, ""))
    assert window.recon.has_image()
    assert "120" in message.text()
    window.close()


def test_window_paints_progress_and_marks_the_step_done(qapp, tmp_path):
    settings = store.default_settings()
    session = Session(settings=settings, folder=tmp_path / "session", demo=True,
                      autosave=True, settings_path=tmp_path / "config.ini",
                      profile_path=tmp_path / "profile.json")
    window = MainWindow(session, show_welcome=False)
    window.select_step("scan")

    window._on_scan_progress(_progress(0.4))
    assert window.scan_view.percentage() == 40
    bar = window.findChild(QProgressBar, "scanProgressBar")
    assert bar is not None and bar.value() == 40
    status = window.findChild(QLabel, "scanStatusValue")
    assert "40%" in status.text()
    dropped = window.findChild(QLabel, "scanDroppedValue")
    assert "2 of 1236" in dropped.text()

    result = ScanResult(status=ScanStatus.COMPLETED, frames_written=1234,
                        frames_dropped=2, duration_s=30.0, rate_arcsec_s=15.04,
                        rows_completed=1, dec_error_arcsec=0.4)
    window._on_scan_finished(result)
    assert session.status_of("scan").value == "done"
    assert "1234" in window.findChild(QLabel, "scanResultValue").text()
    window.close()
