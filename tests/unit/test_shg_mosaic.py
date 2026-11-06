############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg mosaic test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# External anchors:
#   - the prototype's test_mosaic.py: step = strip*(1-overlap), the positions
#     are centred on the requested Dec as a group, and one row when the strip
#     covers the disk;
#   - 7 mm at 714 mm focal = 7/714 rad = 33.7' (ARCHITECTURE 3.2);
#   - the backlash approach always finishes towards +Dec, so the same target
#     lands in the same place regardless of the direction requested.

import math

import pytest

from solarscribe.shg import mosaic


def test_plan_step_and_centring_match_the_prototype():
    plan = mosaic.compute_mosaic_plan(
        center_dec_deg=20.0, solar_diameter_arcsec=1920.0,
        slit_arcsec=1444.0, overlap=0.15, margin_arcsec=100.0)
    assert plan.strip_arcsec == pytest.approx(1444.0)
    assert plan.step_arcsec == pytest.approx(1444.0 * (1.0 - 0.15))
    assert plan.rows >= 1
    assert len(plan.positions_dec_deg) == plan.rows
    mean = sum(plan.positions_dec_deg) / len(plan.positions_dec_deg)
    assert mean == pytest.approx(20.0)
    # The rows are ordered from south to north.
    assert list(plan.positions_dec_deg) == sorted(plan.positions_dec_deg)


def test_one_row_when_the_slit_covers_the_disk():
    plan = mosaic.compute_mosaic_plan(
       22.0, 1920.0, 2022.0, overlap=0.15, margin_arcsec=100.0)
    assert plan.rows == 1
    assert plan.positions_dec_deg == (22.0,)


def test_uncertainty_enlarges_the_margin():
    tight = mosaic.compute_mosaic_plan(
        10.0, 1920.0, 1000.0, uncertainty_arcsec=0.0)
    loose = mosaic.compute_mosaic_plan(
        10.0, 1920.0, 1000.0, uncertainty_arcsec=500.0)
    assert loose.margin_arcsec == pytest.approx(500.0)
    assert loose.rows >= tight.rows


def test_effective_slit_anchor_is_the_seven_millimetre_slit():
    # 7/714 rad = 2021.8"; the ROI samples 3480 px of the 3500 the slit
    # projects to, so 3480*0.5778 = 2010.7".
    effective = mosaic.effective_slit_arcsec(7.0, 1.0, 2.0, 3480, 0.5778)
    full = 7.0 / 714.0 * 206264.806
    assert effective == pytest.approx(3480 * 0.5778)
    assert effective == pytest.approx(full, rel=1e-2)


def test_backlash_approach_finishes_upwards():
    # The last position is always the target and the sequence is increasing.
    sequence = mosaic.backlash_approach(10.0, 10.0 + 120.0 / 3600.0, 30.0)
    assert sequence[-1] == pytest.approx(10.0 + 120.0 / 3600.0)
    assert all(b >= a for a, b in zip(sequence, sequence[1:]))
    # Already below the backoff (target 40" away): no pointless reversal, and
    # the move still finishes upwards.
    sequence = mosaic.backlash_approach(10.0, 10.0 + 40.0 / 3600.0, 30.0)
    assert sequence == (10.0 + 40.0 / 3600.0,)


def test_plan_rejects_an_impossible_overlap():
    with pytest.raises(ValueError):
        mosaic.compute_mosaic_plan(0.0, 1920.0, 1000.0, overlap=1.0)


def test_plan_rows_cover_the_disk_plus_margin():
    plan = mosaic.compute_mosaic_plan(
        0.0, 1920.0, 1000.0, overlap=0.15, margin_arcsec=100.0)
    # The top and bottom rows must reach the disk limb plus the margin.
    south = plan.positions_dec_deg[0] * 3600.0 - plan.strip_arcsec / 2.0
    north = plan.positions_dec_deg[-1] * 3600.0 + plan.strip_arcsec / 2.0
    assert south <= -(1920.0 / 2.0 + 100.0) + 1e-6
    assert north >= (1920.0 / 2.0 + 100.0) - 1e-6
