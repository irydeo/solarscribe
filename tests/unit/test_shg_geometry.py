############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg geometry test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Geometry anchors, external to the code:
#   - 206264.806" per radian; the small-angle plate scale 206265*pixel/focal.
#   - 1 h of RA = 15 deg = 54000" (Meeus, Astronomical Algorithms, ch. 1).
#   - a degree of RA at Dec d subtends cos(d) degrees on the sky.
#   - the chord of a circle: L = 2*sqrt(R^2 - e^2) (Pythagoras, ADR-006).
#   - 7 mm at 714 mm focal = 7/714 rad = 33.7' (ARCHITECTURE 3.2).

import math

import pytest

from solarscribe.shg import geometry


def test_pixel_scale_matches_the_reference_instrument():
    # 714 mm focal and a 2 um pixel: 206265*0.002/714 = 0.5778"/px, the
    # figure the prototype uses for the SHG-700.
    assert geometry.pixel_scale_arcsec_px(714.0, 2.0) == pytest.approx(
        0.5778, abs=1e-3)


def test_one_ra_hour_is_fifteen_degrees():
    assert geometry.ARCSEC_PER_RA_HOUR == 54000.0
    assert geometry.ra_diff_arcsec(0.1, 23.9) == pytest.approx(10800.0)
    assert geometry.ra_diff_arcsec(23.9, 0.1) == pytest.approx(-10800.0)


def test_cos_dec_factor_is_the_spherical_correction():
    assert geometry.cos_dec_factor(0.0) == pytest.approx(1.0)
    assert geometry.cos_dec_factor(60.0) == pytest.approx(2.0)
    # The floor keeps a near-pole read from dividing by zero.
    assert geometry.cos_dec_factor(89.9) == pytest.approx(2.0)


def test_ra_rate_and_sky_rate_are_inverses():
    assert geometry.ra_rate_from_sky_rate(50.0, 60.0) == pytest.approx(100.0)
    assert geometry.sky_rate_from_ra_rate(100.0, 60.0) == pytest.approx(50.0)


def test_chord_at_the_centre_is_the_diameter_and_at_the_limb_is_zero():
    diameter = 1920.0
    slit = 1444.0
    assert geometry.chord_arcsec(0.0, slit, diameter) == pytest.approx(diameter)
    # Inside the dead zone |q| < S/2 the chord does not change.
    assert geometry.chord_arcsec(0.5 * slit, slit, diameter) == pytest.approx(diameter)
    assert geometry.chord_arcsec(-0.5 * slit, slit, diameter) == pytest.approx(diameter)
    # Beyond the slit half-length the chord is shorter.
    q = 0.5 * slit + 0.5 * diameter / 2.0
    expected = 2.0 * math.sqrt((diameter / 2.0) ** 2 - (q - slit / 2.0) ** 2)
    assert geometry.chord_arcsec(q, slit, diameter) == pytest.approx(expected)
    assert geometry.chord_arcsec(-q, slit, diameter) == pytest.approx(expected)
    # Slit fully off the disk.
    assert geometry.chord_arcsec(2.0 * diameter, slit, diameter) == 0.0


def test_chord_inverse_recovers_the_offset():
    diameter = 1920.0
    slit = 1444.0
    for q in (900.0, 1200.0, 1500.0):
        chord = geometry.chord_arcsec(q, slit, diameter)
        q_abs, edge = geometry.offset_from_chord(chord, slit, diameter)
        assert q_abs == pytest.approx(q, abs=1e-9)
        assert edge == pytest.approx(q - slit / 2.0, abs=1e-9)


def test_dead_zone_is_half_the_slit():
    assert geometry.dead_zone_arcsec(1444.0) == pytest.approx(722.0)


def test_effective_slit_is_the_seven_millimetre_anchor():
    # 7 mm at 714 mm focal is 7/714 rad = 2021.8". The ROI samples 3480 of the
    # 3500 sensor pixels the slit projects to, so the effective length is a
    # little shorter: 3480*0.5778 = 2010.7".
    effective = geometry.effective_slit_arcsec(7.0, 1.0, 2.0, 3480, 0.5778)
    assert effective == pytest.approx(3480 * 0.5778, rel=1e-9)
    full_slit = geometry.effective_slit_arcsec(7.0, 1.0, 2.0, 4000, 0.5778)
    assert full_slit == pytest.approx(3500 * 0.5778, rel=1e-9)
    assert full_slit == pytest.approx(7.0 / 714.0 * geometry.ARCSEC_PER_RAD, rel=1e-3)


def test_slit_image_scale_is_the_ratio_of_the_two_axes():
    # The 2026-11 reference data: the slit axis is compressed by ~1.28.
    assert geometry.slit_image_scale(0.5778, 0.4514) == pytest.approx(1.28, abs=1e-2)
    assert geometry.slit_image_scale(0.5778, 0.5778) == pytest.approx(1.0)
