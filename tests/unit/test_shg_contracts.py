############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg contracts test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The three pending contracts of ARCHITECTURE 2.3, now formalised in shg/abc.py:
# analysis_regions, the Find-the-Sun centring service and the solar polar
# alignment assistant. They must be importable, runtime checkable where they are
# protocols, and their value types must build with the documented units.

import pytest

from solarscribe.shg import abc as shg_abc


def test_analysis_regions_contract_exists():
    # The contract module declares the shape; the implementation is in
    # shg/analysis.py because a contract module holds no algorithm (ADR-023).
    assert callable(shg_abc.analysis_regions)
    assert shg_abc.ANALYSIS_KEYS == ("left", "right", "limb")
    from solarscribe.shg.analysis import analysis_regions
    regions = analysis_regions((0, 0, 3480, 248), (0, 40, 3480, 160))
    assert regions["left"] == (0, 40, 1740, 160)
    assert regions["right"] == (1740, 40, 1740, 160)
    assert regions["limb"] == (0, 40, 3480, 160)


def test_centering_value_types_build():
    status = shg_abc.CenteringStatus(phase="fine", progress=0.5)
    assert status.dec_offset_arcsec is None
    result = shg_abc.CenteringResult(
        ok=True, dec_offset_arcsec=10.0,
        method=shg_abc.DecCenterMethod.SYMMETRY, dead_zone_arcsec=0.0)
    assert result.method == shg_abc.DecCenterMethod.SYMMETRY
    assert result.dead_zone_arcsec == 0.0


def test_polar_value_types_build_with_the_fixed_units():
    sample = shg_abc.PolarSample(
        time_s=0.0, hour_angle_deg=0.0, dec_deg=20.0,
        dec_ephemeris_deg=20.0)
    assert sample.dec_deg == 20.0
    progress = shg_abc.PolarProgress(
        samples=1, required=10, progress=0.1, hour_angle_deg=0.0,
        elapsed_s=0.0)
    assert progress.progress == pytest.approx(0.1)
    result = shg_abc.PolarResult(
        ok=True, azimuth_error_arcsec=10.0, altitude_error_arcsec=-5.0,
        drift_rate_arcsec_min=0.1, residual_arcsec=0.2, samples=5)
    assert result.confirmation is False
    assert result.reason_code == ""


def test_the_three_new_protocols_are_runtime_checkable():
    class CenteringStub:
        def center(self, cb):
            return shg_abc.CenteringResult(
                ok=True, dec_offset_arcsec=0.0,
                method=shg_abc.DecCenterMethod.AUTO)

    class PolarStub:
        def add_sample(self, sample, cb=None):
            return shg_abc.PolarProgress(0, 0, 0.0, 0.0, 0.0)

        def result(self):
            return shg_abc.PolarResult(True, 0.0, 0.0, 0.0, 0.0, 0)

        def confirm(self, samples, cb=None):
            return shg_abc.PolarResult(True, 0.0, 0.0, 0.0, 0.0, 0)

    assert isinstance(CenteringStub(), shg_abc.SunCenteringService)
    assert isinstance(PolarStub(), shg_abc.PolarAlignmentAssistant)
    # The pre-existing contracts are still there (the layer test guards the
    # full surface; this is the local reminder).
    for name in ("ScanEngine", "TiltMeter", "FrameSource", "RowRecorder"):
        assert hasattr(shg_abc, name)
