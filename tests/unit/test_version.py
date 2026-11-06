############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - version test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""The package version is the installed distribution version.

The fallback "0.0.0" is only true when the source tree was never installed.
An installed venv must not show it: that was the bug behind `solarscribe
--version` and session_meta.json disagreeing with the installer (ADR-017).
"""

import importlib.metadata
import json

import solarscribe


def test_version_is_non_empty_and_matches_the_installed_distribution():
    # @return: None; the assertions are the contract
    assert isinstance(solarscribe.__version__, str)
    assert solarscribe.__version__
    try:
        installed = importlib.metadata.version("solarscribe")
    except importlib.metadata.PackageNotFoundError:
        # A bare source tree: there is no dist-info to read, and the fallback
        # is the only honest answer.
        assert solarscribe.__version__ == "0.0.0"
    else:
        assert solarscribe.__version__ == installed


def test_session_meta_records_the_package_version(tmp_path):
    # @return: None; writes session_meta.json and reads it back
    from solarscribe.shg import logs
    from solarscribe.shg.abc import ScanConfig, ScanMode, ScanPlan, ScanRow

    config = ScanConfig(capture=(0, 0, 3480, 248), band=(0, 40, 3480, 160))
    plan = ScanPlan(
        mode=ScanMode.SIMPLE, rate_arcsec_s=69.3,
        rows=(ScanRow(0, 0.0, 12.0, 11.96, 29.7),),
        duration_s=29.7, frames_estimate=3564, padding_s=1.0, preload_s=0.3)
    meta = logs.build_session_meta(
        config, plan, {"focal_length_mm": 714.0}, solarscribe.__version__)
    path = tmp_path / "session_meta.json"
    logs.write_session_meta(meta, path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["app_version"] == solarscribe.__version__
