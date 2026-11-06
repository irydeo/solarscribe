############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui steps test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# ADR-011 is a promise, not a layout: five steps, free navigation, silent
# autosave and "reopen step". These tests pin the promise at the Session and at
# the rail. The rail is where a newcomer decides whether the app is a wizard
# that blocks or a guide that does not, so the click on a pending step is a
# first-class test.

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from solarscribe.config import store  # noqa: E402
from solarscribe.config.schema import SESSION_STEPS, StepStatus  # noqa: E402
from solarscribe.ui.session import Session  # noqa: E402
from solarscribe.ui.step_rail import StepRail  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def session(tmp_path):
    settings = store.default_settings()
    return Session(settings=settings, folder=tmp_path / "session", demo=False,
                   autosave=True, settings_path=tmp_path / "config.ini",
                   profile_path=tmp_path / "profile.json")


def test_all_steps_start_pending_and_recommend_the_first(session):
    assert tuple(session.state.steps) == SESSION_STEPS
    assert all(session.status_of(step) is StepStatus.PENDING
               for step in SESSION_STEPS)
    assert session.recommended_step() == "find_sun"
    assert session.current_step() == "find_sun"


def test_free_navigation_never_gates(session):
    # Going straight to Scanning while Find the Sun is pending is allowed, and
    # it does not pretend the earlier step happened.
    session.select_step("scan")
    assert session.current_step() == "scan"
    assert session.status_of("scan") is StepStatus.CURRENT
    assert session.status_of("find_sun") is StepStatus.PENDING


def test_complete_and_reopen_a_step(session):
    session.complete_step("roi", tilt_deg=0.4, tilt_px=1.9)
    state = session.step_state("roi")
    assert state.status is StepStatus.DONE
    assert state.metrics["tilt_deg"] == pytest.approx(0.4)
    assert state.metrics["tilt_px"] == pytest.approx(1.9)

    # Reopen means the observer can do it again; the numbers stay as a hint.
    session.reopen_step("roi")
    assert session.current_step() == "roi"
    assert session.status_of("roi") is StepStatus.CURRENT
    assert session.step_state("roi").metrics["tilt_deg"] == pytest.approx(0.4)


def test_autosave_is_silent_and_restorable(tmp_path):
    settings = store.default_settings()
    folder = tmp_path / "session"
    first = Session(settings=settings, folder=folder, demo=False,
                    autosave=True, settings_path=tmp_path / "config.ini",
                    profile_path=tmp_path / "profile.json")
    first.complete_step("find_sun", dec_error_arcsec=0.3)
    state_file = folder / "session_state.json"
    assert state_file.is_file()

    second = Session.load(folder, settings=settings, demo=False,
                          settings_path=tmp_path / "config.ini",
                          profile_path=tmp_path / "profile.json")
    assert second.status_of("find_sun") is StepStatus.DONE
    assert second.step_state("find_sun").metrics["dec_error_arcsec"] == pytest.approx(0.3)
    assert second.recommended_step() == "polar"


def test_autosave_can_be_turned_off(tmp_path):
    settings = store.default_settings()
    session = Session(settings=settings, folder=tmp_path / "session", demo=False,
                      autosave=False, settings_path=tmp_path / "config.ini")
    session.complete_step("polar", azimuth_arcmin=5.0)
    assert not (tmp_path / "session" / "session_state.json").exists()


def test_recommendation_walks_all_five_steps(session):
    assert session.recommended_step() == "find_sun"
    session.complete_step("find_sun")
    assert session.recommended_step() == "polar"
    session.complete_step("polar")
    assert session.recommended_step() == "focus"
    session.complete_step("focus")
    assert session.recommended_step() == "roi"
    session.complete_step("roi")
    assert session.recommended_step() == "scan"
    session.complete_step("scan")
    assert session.recommended_step() == "scan"


def test_rail_shows_five_chips_with_words_not_only_colours(qapp, session):
    rail = StepRail()
    rail.set_state(session.state, "find_sun")
    assert rail.steps() == SESSION_STEPS
    first = rail.button("find_sun")
    assert "1." in first.text()
    assert "Find Sun" in first.text()
    assert "Pending" in first.text()
    # ADR-026: one line, 28 px, not the old two-line 64 px rail.
    assert "\n" not in first.text()
    assert first.maximumHeight() <= 28
    # A pending step must be clickable: that is the whole point of ADR-011.
    assert first.isEnabled()


def test_rail_click_emits_and_selects_even_when_pending(qapp, session):
    rail = StepRail()
    rail.set_state(session.state, "find_sun")
    seen = []
    rail.stepActivated.connect(seen.append)
    rail.button("roi").click()
    assert seen == ["roi"]
    assert rail.button("roi").isChecked()
    assert not rail.button("find_sun").isChecked()


def test_rail_spells_each_status(qapp, session):
    session.complete_step("find_sun")
    session.skip_step("polar")
    session.select_step("roi")
    rail = StepRail()
    rail.set_state(session.state, "roi")
    assert "Done" in rail.button("find_sun").text()
    assert "Skipped" in rail.button("polar").text()
    assert "Pending" in rail.button("scan").text()
    assert rail.button("find_sun").property("stepStatus") == "done"
    assert rail.button("roi").property("stepStatus") == "current"
