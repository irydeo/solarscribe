############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui dialogs test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The dialogs carry the explanations: the settings tooltips are the schema's
# "why", the logs are the diagnosis, the sky calendar refuses to guess and the
# focus aid admits what it cannot measure. These tests read the words, not the
# pixels.

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QLabel, QLineEdit, QPushButton,
)

from solarscribe.config import store  # noqa: E402
from solarscribe.config.schema import SCHEMA, RoiPreset  # noqa: E402
from solarscribe.ui.focus_aid import FocusAidDialog  # noqa: E402
from solarscribe.ui.logs_viewer import LogsViewer  # noqa: E402
from solarscribe.ui.roi_manager import RoiManagerDialog  # noqa: E402
from solarscribe.ui.settings_dialog import SettingsDialog  # noqa: E402
from solarscribe.ui.sky_calendar import SkyCalendarDialog  # noqa: E402
from solarscribe.ui.sun_disc import SunDiscWidget  # noqa: E402
from solarscribe.ui.welcome import WelcomeBanner  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_settings_dialog_is_built_from_the_schema_and_explains_each_key(qapp):
    dialog = SettingsDialog(store.default_settings())
    editor = dialog.editor("camera", "exposure_us")
    assert editor is not None
    why = next(key.why for key in SCHEMA
               if key.section == "camera" and key.name == "exposure_us")
    assert editor.toolTip() == why
    assert "microseconds" in why

    dialog.set_value("camera", "exposure_us", 2500.0)
    assert dialog.value("camera", "exposure_us") == pytest.approx(2500.0)
    values = dialog.values()
    assert values.get("camera", "exposure_us") == pytest.approx(2500.0)

    dialog.restore_defaults()
    assert dialog.value("camera", "exposure_us") == pytest.approx(1000.0)


def test_settings_filter_hides_rows_that_do_not_match(qapp):
    dialog = SettingsDialog(store.default_settings())
    edit = dialog.findChild(QLineEdit, "filterEdit")
    edit.setText("exposure")
    assert dialog.editor("camera", "exposure_us").parentWidget().isVisibleTo(dialog)
    assert not dialog.editor("camera", "gain").parentWidget().isVisibleTo(dialog)


def test_logs_viewer_reads_filters_and_follows(qapp, tmp_path):
    log = tmp_path / "solarscribe.log"
    log.write_text(
        "2026-11-06 10:00:00 INFO session started\n"
        "2026-11-06 10:00:01 WARNING low disk\n"
        "2026-11-06 10:00:02 ERROR camera lost\n",
        encoding="utf-8")
    viewer = LogsViewer(log)
    assert "session started" in viewer.text()
    assert "camera lost" in viewer.text()
    viewer.filter_combo.setCurrentIndex(2)      # Errors only
    assert "camera lost" in viewer.text()
    assert "session started" not in viewer.text()
    viewer.filter_combo.setCurrentIndex(1)      # Warnings and errors
    assert "low disk" in viewer.text()
    assert str(log) == str(viewer.path())


def test_logs_viewer_handles_a_missing_file(qapp, tmp_path):
    viewer = LogsViewer(tmp_path / "nope.log")
    assert viewer.text() == ""
    assert "No log" in viewer.path_label.text()


def test_sky_calendar_refuses_to_guess_without_an_ephemeris(qapp):
    dialog = SkyCalendarDialog({})
    empty = dialog.findChild(QLabel, "sunEmptyState")
    assert not empty.isHidden()
    assert "not available" in empty.text()
    assert dialog.findChild(SunDiscWidget, "sunDiscHost") is not None

    dialog.set_sun_info({
        "date": "2026-11-06",
        "diameter_arcmin": 32.27,
        "ra_hours": 14.79,
        "dec_deg": -16.15,
        "rotation": None,
        "heliographic": None,
        "source": "ephemeris",
    })
    assert empty.isHidden()
    assert "2026-11-06" in dialog.findChild(QLabel, "sunDateValue").text()
    assert "32.27" in dialog.findChild(QLabel, "sunDiameterValue").text()
    assert "14.79" in dialog.findChild(QLabel, "sunRaValue").text()
    assert "Not available" in dialog.findChild(
        QLabel, "sunHeliographicValue").text()

    dialog.set_sun_info({
        "date": "2026-11-06", "diameter_arcmin": 32.27,
        "ra_hours": 14.79, "dec_deg": -16.15,
        "rotation": 26.27,
        "heliographic": "B0 +5.99 deg, L0 238.63 deg",
        "source": "ephemeris",
    })
    assert "+26.27" in dialog.findChild(QLabel, "sunRotationValue").text()
    assert "B0" in dialog.findChild(QLabel, "sunHeliographicValue").text()


def test_roi_manager_lists_presets_and_returns_the_chosen_one(qapp):
    presets = (RoiPreset(name="default"),
               RoiPreset(name="wide", capture=(0, 0, 3480, 300),
                         band=(0, 60, 3480, 180)))
    dialog = RoiManagerDialog(presets)
    assert dialog.count() == 2
    assert dialog.table.rowCount() == 2
    seen = []
    dialog.presetChosen.connect(seen.append)
    dialog.table.selectRow(1)
    dialog._use_current()
    assert seen and seen[0].name == "wide"
    assert dialog.result() == dialog.DialogCode.Accepted


def test_focus_aid_shows_percentages_of_the_range(qapp):
    dialog = FocusAidDialog()
    dialog.set_stats(0.25, 0.042)
    mean, std = dialog.texts()
    assert "25.0%" in mean
    assert "4.20%" in std
    assert "full range" in mean


def test_welcome_banner_emits_the_location(qapp):
    banner = WelcomeBanner()
    banner.set_location(40.0, -3.0)
    assert banner.location() == (pytest.approx(40.0), pytest.approx(-3.0))
    banner.set_device_status("Simulator", "Simulator")
    seen = []
    banner.answered.connect(lambda *args: seen.append(args))
    check = banner.findChild(QCheckBox, "welcomeDontAskCheck")
    check.setChecked(True)
    save = banner.findChild(QPushButton, "welcomeSaveButton")
    save.click()
    assert seen == [(40.0, -3.0, True)]
