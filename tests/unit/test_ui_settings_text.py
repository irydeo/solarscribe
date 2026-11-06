############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui settings text test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The settings tooltips come from config/schema.py's `why`, which is developer
# documentation and never passes through translation. The generated table wraps
# every why in QT_TRANSLATE_NOOP("Settings", ...), and the dialog calls
# QCoreApplication.translate with the same context (ADR-016).
#
# The important test is the drift check: the committed settings_text.py must be
# exactly what the generator produces from the current SCHEMA. A new or changed
# key then fails the suite until the table is regenerated, which is what keeps
# the 111 tooltips current.

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from solarscribe.config.schema import SCHEMA  # noqa: E402
from solarscribe.config.store import default_settings  # noqa: E402
from solarscribe.ui import generate_settings_text as generator  # noqa: E402
from solarscribe.ui.settings_dialog import SettingsDialog  # noqa: E402
from solarscribe.ui.settings_text import SETTINGS_WHY  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_committed_table_matches_the_schema(qapp):
    # This is the drift gate: if a key is added, removed or its why edited, the
    # committed file no longer equals the render and the test names the fix.
    rendered = generator.render_module()
    committed = Path(generator.MODULE_PATH).read_text(encoding="utf-8")
    assert rendered == committed, (
        "solarscribe/ui/settings_text.py is stale: run "
        "python -m solarscribe.ui.generate_settings_text")

    expected = {(key.section, key.name): key.why for key in SCHEMA}
    assert SETTINGS_WHY == expected
    assert len(SETTINGS_WHY) == len(SCHEMA)


def test_every_key_is_marked_with_the_settings_context(qapp):
    # lupdate only sees strings in the source. The literal marker count is the
    # proof that no tooltip was left in the schema without a translatable copy.
    source = Path(generator.MODULE_PATH).read_text(encoding="utf-8")
    assert source.count('QT_TRANSLATE_NOOP("Settings"') == len(SCHEMA)
    for key in SCHEMA:
        assert SETTINGS_WHY[(key.section, key.name)] == key.why


def test_dialog_tooltips_use_the_settings_context(qapp, monkeypatch):
    # A patched translate makes the context visible. Without it the source text
    # is returned, which would not prove that the dialog asked the translator.
    monkeypatch.setattr(
        QCoreApplication, "translate",
        staticmethod(lambda context, text: f"[{context}] {text}"))
    dialog = SettingsDialog(default_settings())
    for key in SCHEMA:
        editor = dialog.editor(key.section, key.name)
        assert editor is not None
        assert editor.toolTip() == f"[Settings] {key.why}"
