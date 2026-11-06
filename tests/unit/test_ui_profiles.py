############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui profiles test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The profile bar is the visible half of the named-profile feature and the
# adapter is the only door to the ADR-027 store. These tests use the real
# profiles.json API in a temporary folder, plus a fallback store with none of
# it, so the UI is proven against both.

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QComboBox, QListWidget, QToolButton, QWidget,
)

from solarscribe.config import store  # noqa: E402
from solarscribe.config.schema import (  # noqa: E402
    Profile, TelescopeData,
)
from solarscribe.config.store import ProfileStore  # noqa: E402
from solarscribe.ui.main_window import MainWindow  # noqa: E402
from solarscribe.ui.profile_manager import ProfileManagerDialog  # noqa: E402
from solarscribe.ui.profiles import ProfileAdapter, ProfileStoreError  # noqa: E402
from solarscribe.ui.session import Session  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FallbackStore:
    def __init__(self):
        self.saved = []

    def load_profile(self, path):
        return Profile()

    def save_profile(self, profile, path):
        self.saved.append((profile, path))


# @args: none
# @return: a profile with a distinctive focal length, to prove the startup load
def _wide_profile() -> Profile:
    return Profile(telescope=TelescopeData(focal_length_mm=900.0))


def _write_store(path, active="Wide"):
    store.save_profiles(ProfileStore(
        active=active,
        profiles={"Wide": _wide_profile(), "Narrow": Profile()}), path)


def _window(tmp_path):
    settings = store.default_settings()
    settings.values[("session", "session_dir")] = str(tmp_path / "sessions")
    session = Session(settings=settings, folder=tmp_path / "session", demo=False,
                      autosave=True, settings_path=tmp_path / "config.ini",
                      profile_path=tmp_path / "profile.json")
    window = MainWindow(session, show_welcome=False)
    window.resize(1280, 820)
    window.show()
    return window


def test_adapter_reads_and_writes_the_named_store(tmp_path):
    path = tmp_path / "profiles.json"
    adapter = ProfileAdapter(profiles_path=path,
                             legacy_path=tmp_path / "profile.json",
                             fallback_profile=Profile())
    assert adapter.available
    assert adapter.names() == ("default",)
    assert adapter.active() == "default"
    assert adapter.load("default") is not None

    adapter.save("Wide", _wide_profile(), make_active=True)
    assert "Wide" in adapter.names()
    assert adapter.active() == "Wide"
    assert adapter.load("Wide").telescope.focal_length_mm == 900.0
    saved = store.load_profiles(path)
    assert store.profile_names(saved) == ("default", "Wide")
    assert saved.active == "Wide"

    adapter.set_active("default")
    assert adapter.active() == "default"
    assert store.load_profiles(path).active == "default"

    adapter.rename("Wide", "Renamed")
    assert "Renamed" in adapter.names()
    adapter.delete("Renamed")
    assert "Renamed" not in adapter.names()
    assert "Renamed" not in store.profile_names(store.load_profiles(path))


def test_adapter_falls_back_to_one_default_profile(tmp_path):
    fallback = FallbackStore()
    adapter = ProfileAdapter(store_module=fallback,
                             profiles_path=tmp_path / "profiles.json",
                             legacy_path=tmp_path / "profile.json",
                             fallback_profile=Profile())
    assert not adapter.available
    assert adapter.names() == ("default",)
    assert adapter.active() == "default"
    assert adapter.load("default") is not None
    adapter.save("default", Profile())
    assert fallback.saved
    with pytest.raises(ProfileStoreError) as error:
        adapter.save("Other", Profile())
    assert error.value.reason == "named_store_missing"
    with pytest.raises(ProfileStoreError):
        adapter.delete("default")


def test_manager_lists_names_marks_the_active_and_uses_one(qapp, tmp_path):
    path = tmp_path / "profiles.json"
    _write_store(path)
    adapter = ProfileAdapter(profiles_path=path,
                             legacy_path=tmp_path / "profile.json",
                             fallback_profile=Profile())
    dialog = ProfileManagerDialog(adapter, Profile(), "Wide")
    listing = dialog.findChild(QListWidget, "profileList")
    assert listing is not None and listing.count() == 2
    texts = [listing.item(index).text() for index in range(2)]
    assert texts == ["Wide (active)", "Narrow"]
    listing.setCurrentRow(1)
    seen = []
    dialog.profileChosen.connect(seen.append)
    use = dialog.findChild(QWidget, "profileUseButton")
    use.click()
    assert seen == ["Narrow"]
    assert adapter.active() == "Narrow"
    assert store.load_profiles(path).active == "Narrow"


def test_window_shows_the_profile_bar_and_opens_the_manager(qapp, tmp_path):
    window = _window(tmp_path)
    try:
        combo = window.findChild(QComboBox, "profileCombo")
        assert combo is not None and combo.currentText() == "default"
        assert window.findChild(QToolButton, "profileSaveButton") is not None
        assert window.findChild(QToolButton, "profileManageButton") is not None
        assert "Optics" in window.findChild(QWidget, "profileHint").text()
        window.manage_profiles()
        dialog = window._profile_manager_dialog
        assert dialog is not None and dialog.isVisible()
        listing = dialog.findChild(QListWidget, "profileList")
        assert listing is not None and listing.count() == 1
        assert "default" in listing.item(0).text()
        hint = dialog.findChild(QWidget, "profileManagerStoreHint")
        assert hint is not None and hint.isHidden()
        new_button = dialog.findChild(QWidget, "profileNewButton")
        assert new_button is not None and new_button.isEnabled()
        dialog.close()
    finally:
        window.close()


def test_window_loads_the_active_named_profile_at_startup(qapp, tmp_path):
    _write_store(tmp_path / "profiles.json")
    window = _window(tmp_path)
    try:
        assert window._active_profile == "Wide"
        assert window.session.profile.telescope.focal_length_mm == 900.0
        combo = window.findChild(QComboBox, "profileCombo")
        assert combo.currentText() == "Wide"
    finally:
        window.close()
