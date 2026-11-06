############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui polar and centring test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Two shg contracts the UI must not fake:
#   - the drift fit of the polar assistant, including the sign convention that
#     turns a number into "turn the knob west" or "lower the axis";
#   - the dead zone of the coarse centring, which the step must show instead of
#     pretending the residual is exact.

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from solarscribe.config import store  # noqa: E402
from solarscribe.shg.abc import CenteringResult, DecCenterMethod  # noqa: E402
from solarscribe.ui.main_window import MainWindow  # noqa: E402
from solarscribe.ui.session import Session  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _session(tmp_path):
    settings = store.default_settings()
    settings.values[("observatory", "latitude_deg")] = 40.0
    settings.values[("observatory", "longitude_deg")] = -3.0
    return Session(settings=settings, folder=tmp_path / "session", demo=True,
                   autosave=True, settings_path=tmp_path / "config.ini",
                   profile_path=tmp_path / "profile.json")


def test_polar_fit_recovers_the_error_and_its_direction(qapp, tmp_path):
    session = _session(tmp_path)
    harness = session.harness
    harness.stop_polar()
    finished = []
    harness.polarFinished.connect(finished.append)
    harness.start_polar(False)
    harness.stop_polar()             # drive the ticks by hand, no wall clock
    for _ in range(8):
        harness._polar_tick()        # noqa: SLF001 - deterministic simulator step
    first = finished[-1]
    assert first["azimuth_arcmin"] == pytest.approx(5.0, abs=0.1)
    assert first["altitude_arcmin"] == pytest.approx(3.0, abs=0.1)
    assert first["confirmed"] is False

    harness.start_polar(True)
    harness.stop_polar()
    finished.clear()
    for _ in range(8):
        harness._polar_tick()        # noqa: SLF001
    second = finished[-1]
    assert second["confirmed"] is True
    assert second["azimuth_arcmin"] < 1.0


def test_polar_panel_says_which_way_to_turn(qapp, tmp_path):
    session = _session(tmp_path)
    window = MainWindow(session, show_welcome=False)
    window._on_polar_finished({
        "azimuth_arcmin": 5.0, "altitude_arcmin": 3.0,
        "azimuth_sign": 300.0, "altitude_sign": 180.0,
        "second": False, "confirmed": False, "reason_code": "",
    })
    assert "west" in window.findChild(QLabel, "polarAzValue").text()
    assert "down" in window.findChild(QLabel, "polarAltValue").text()
    assert window.session.status_of("polar").value != "done"

    window._on_polar_finished({
        "azimuth_arcmin": 0.5, "altitude_arcmin": 0.3,
        "azimuth_sign": 30.0, "altitude_sign": 20.0,
        "second": True, "confirmed": True, "reason_code": "",
    })
    assert window.session.status_of("polar").value == "done"
    assert "Aligned" in window.findChild(QLabel, "polarStateValue").text()
    window.close()


def test_centring_result_shows_the_dead_zone(qapp, tmp_path):
    session = _session(tmp_path)
    window = MainWindow(session, show_welcome=False)
    result = CenteringResult(ok=True, dec_offset_arcsec=1.4,
                             method=DecCenterMethod.SYMMETRY,
                             dead_zone_arcsec=0.9)
    window.show_centering_result(result)
    assert session.status_of("find_sun").value == "done"
    assert "1.4" in window.findChild(QLabel, "decErrorValue").text()
    assert "0.9" in window.findChild(QLabel, "deadZoneValue").text()
    assert window.session.step_state("find_sun").metrics[
        "dead_zone_arcsec"] == pytest.approx(0.9)
    window.close()
