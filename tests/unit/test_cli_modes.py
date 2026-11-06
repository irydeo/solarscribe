############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - cli modes test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The CLI is what runs over SSH and in CI: no Qt, no display, no hardware. The
# dry run must refuse a ROI that cannot be scanned without writing anything, and
# the diagnostic must say honestly whether the device layer is in the build.

import os
import subprocess
import sys
from pathlib import Path

import pytest

from solarscribe.cli import run
from solarscribe.config import store

REPO_ROOT = Path(__file__).resolve().parents[2]


def _settings_file(tmp_path, **values):
    settings = store.default_settings()
    for key, value in values.items():
        section, name = key.split(".", 1)
        settings.values[(section, name)] = value
    path = tmp_path / "config.ini"
    store.save_settings(settings, path)
    return path


def test_dry_run_is_valid_with_the_schema_defaults(tmp_path, capsys):
    settings = _settings_file(tmp_path)
    code = run(["--dry-run", "--settings", str(settings),
                "--profile", str(tmp_path / "profile.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "DRY RUN" in out
    assert "capture 0, 0, 3480 x 248" in out
    assert "band    0, 40, 3480 x 160" in out
    assert "The geometry is consistent" in out
    assert "Result: the dry run is valid" in out


def test_dry_run_writes_no_session_file(tmp_path, capsys):
    settings = _settings_file(tmp_path)
    session = tmp_path / "would_be_session"
    run(["--dry-run", "--settings", str(settings), "--session", str(session)])
    assert not session.exists()
    assert "would be created" not in capsys.readouterr().out


def test_dry_run_rejects_a_roi_that_cannot_be_scanned(tmp_path, capsys):
    settings = _settings_file(tmp_path, **{"roi.capture_height": 100})
    code = run(["--dry-run", "--settings", str(settings)])
    out = capsys.readouterr().out
    assert code == 1
    assert "ERROR" in out
    assert "cannot be scanned" in out
    assert "160" in out and "100" in out


def test_diagnostics_reports_the_paths_and_the_device_layer(tmp_path, capsys):
    settings = _settings_file(tmp_path)
    code = run(["--diagnostics", "--settings", str(settings)])
    out = capsys.readouterr().out
    assert code == 0
    assert "SolarScribe" in out
    assert "Python" in out
    assert "Config dir" in out
    assert "Device layer:" in out
    assert "not in this build" in out or "present" in out
    assert "Unknown INI keys: none" in out


def test_diagnostics_flags_unknown_ini_keys(tmp_path, capsys):
    path = tmp_path / "config.ini"
    path.write_text("[general]\nlanguage = en\nmade_up_key = 1\n",
                    encoding="utf-8")
    code = run(["--diagnostics", "--settings", str(path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "general.made_up_key" in out
    assert "WARNING" in out


def test_unknown_command_prints_usage(capsys):
    assert run([]) == 2
    assert "Usage:" in capsys.readouterr().out


def test_cli_imports_no_qt():
    # A subprocess is the only honest check: another test in this process has
    # already imported Qt, so sys.modules would lie.
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c",
         "import solarscribe.cli, sys; print('PySide6' in sys.modules)"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_the_package_entry_point_dispatches_the_cli(tmp_path):
    # __main__ sends every argument to ui.app.run; the dry run must come out the
    # other side without opening a window.
    settings = _settings_file(tmp_path)
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-m", "solarscribe", "--dry-run",
         "--settings", str(settings)],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
