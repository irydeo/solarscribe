############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg geometry alias test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# nightscribe-scan parity row 14: the prototype calls the 1/cos(Dec)
# correction `cos_dec_correction`. SolarScribe implements it as
# `cos_dec_factor` and keeps the prototype name as an alias, so a reader coming
# from the old script finds it and the parity note is honest. The canonical
# function already has its own test; this one calls the alias by name and ties
# it to the two public rate conversions.

import math

import pytest

from solarscribe.shg import geometry


def test_cos_dec_correction_alias_is_the_astronomical_factor():
    # The alias is the same object, not a re-implementation that could drift.
    assert geometry.cos_dec_correction is geometry.cos_dec_factor

    # One degree of RA is cos(Dec) degrees on the sky.
    assert geometry.cos_dec_correction(0.0) == pytest.approx(1.0)
    assert geometry.cos_dec_correction(60.0) == pytest.approx(2.0)
    dec = 35.0
    assert geometry.cos_dec_correction(dec) == pytest.approx(
        1.0 / math.cos(math.radians(dec))
    )

    # Near the pole the 0.5 floor keeps the coordinate rate finite; the alias
    # must honour the same floor argument as the canonical function.
    assert geometry.cos_dec_correction(89.9) == pytest.approx(2.0)
    assert geometry.cos_dec_correction(89.9, 0.9) == pytest.approx(1.0 / 0.9)


def test_the_alias_is_the_factor_used_by_the_rate_conversions():
    # At Dec 60 the mount must run twice as fast in RA to move the sky at the
    # requested rate. The alias is the factor the conversions expose.
    sky_rate = 100.0
    factor = geometry.cos_dec_correction(60.0)
    assert geometry.ra_rate_from_sky_rate(sky_rate, 60.0) == pytest.approx(
        sky_rate * factor
    )
    assert geometry.sky_rate_from_ra_rate(sky_rate * factor, 60.0) == pytest.approx(
        sky_rate
    )
