############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg polar test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# External anchors:
#   - the sidereal rotation 15.041067"/s (360 deg / 86164.0905 s);
#   - the drift relation MDR = omega_rad * epsilon (Canburytech, "Drift
#     alignment equations"): a 60" offset gives a maximum drift of
#     15.041*60/206265 = 0.00437"/s = 0.262"/min;
#   - AstroPixels/F. Espenak, "Polar Alignment Using Drift Method": azimuth is
#     measured near the meridian and altitude near the east/west horizon, and
#     the north/south drift signs are the ones asserted below.
#
# Note: ADR-007's prose pairs the recommendations the other way round; the
# rotation-vector derivation and the published procedure agree with the code,
# so the code recommends meridian for azimuth and east/west for altitude. The
# discrepancy is reported to the docs agent, not hidden.

import math

import pytest

from solarscribe.shg import polar
from solarscribe.shg.abc import PolarSample


def _sample(time_s: float, hour_angle: float, dec_deg: float,
            dec_ephemeris: float = 0.0, altitude: float = 0.0) -> PolarSample:
    return PolarSample(time_s=time_s, hour_angle_deg=hour_angle,
                       dec_deg=dec_deg, dec_ephemeris_deg=dec_ephemeris,
                       altitude_deg=altitude)


def test_earth_rotation_rate_matches_the_sidereal_day():
    # 360 deg / 86164.0905 s = 15.041067"/s; the prototype uses 15.04.
    assert polar.EARTH_ROTATION_ARCSEC_S == pytest.approx(15.041067, abs=1e-5)


def test_maximum_drift_rate_matches_the_published_relation():
    # Canburytech: MDR = omega_rad * epsilon. A 60" axis offset gives
    # 15.041*60/206265 = 0.00437"/s = 0.262"/min.
    rate = polar.drift_rate_arcsec_s(60.0, 0.0, 90.0, 0.0)
    assert rate == pytest.approx(-0.004375, abs=1e-6)
    assert abs(rate) * 60.0 == pytest.approx(0.2625, abs=1e-3)


def test_azimuth_error_drifts_at_the_meridian_and_altitude_at_the_horizon():
    # At H=0 only the azimuth term survives; at H=+90 only the altitude term.
    assert polar.drift_rate_arcsec_s(0.0, 60.0, 0.0, 0.0) == pytest.approx(
        -0.004375, abs=1e-6)
    assert polar.drift_rate_arcsec_s(60.0, 0.0, 90.0, 0.0) == pytest.approx(
        -0.004375, abs=1e-6)
    # The other term is zero there.
    assert polar.drift_rate_arcsec_s(60.0, 0.0, 0.0, 0.0) == pytest.approx(0.0, abs=1e-12)
    assert polar.drift_rate_arcsec_s(0.0, 60.0, 90.0, 0.0) == pytest.approx(0.0, abs=1e-12)


def test_drift_signs_follow_the_published_tables():
    # AstroPixels: azimuth east drifts the star south at the meridian; an axis
    # too high drifts it south at the western horizon and north at the eastern.
    assert polar.drift_rate_arcsec_s(0.0, 60.0, 0.0, 0.0) < 0.0
    assert polar.drift_rate_arcsec_s(60.0, 0.0, 90.0, 0.0) < 0.0
    assert polar.drift_rate_arcsec_s(60.0, 0.0, -90.0, 0.0) > 0.0


def test_latitude_scales_the_azimuth_term():
    # An azimuth rotation beta moves the polar axis by beta*cos(lat) on the
    # sky, so the meridian drift scales with cos(latitude).
    assert polar.drift_rate_arcsec_s(0.0, 60.0, 0.0, 40.0) == pytest.approx(
        -0.004375 * math.cos(math.radians(40.0)), abs=1e-6)


def _synthetic_samples(alpha: float, beta: float, latitude: float,
                       hour_angles, y0: float = 0.0):
    # The integrated model: y = y0 + alpha*cosH - beta*cos(lat)*sinH.
    samples = []
    for index, hour_angle in enumerate(hour_angles):
        h = math.radians(hour_angle)
        y = y0 + alpha * math.cos(h) - beta * math.cos(math.radians(latitude)) * math.sin(h)
        samples.append(_sample(
            time_s=index * 180.0,
            hour_angle=hour_angle,
            dec_deg=20.0 + y / 3600.0,
            dec_ephemeris=20.0,
        ))
    return samples


def test_fit_recovers_a_known_altitude_and_azimuth_error():
    latitude = 40.0
    alpha, beta = 30.0, -20.0
    samples = _synthetic_samples(alpha, beta, latitude,
                                 [-70.0, -35.0, 0.0, 35.0, 70.0])
    result = polar.fit_polar_alignment(samples, latitude)
    assert result.ok
    assert result.altitude_error_arcsec == pytest.approx(alpha, abs=1e-6)
    assert result.azimuth_error_arcsec == pytest.approx(beta, abs=1e-6)
    assert result.residual_arcsec < 1e-6
    assert result.samples == 5
    assert result.reason_code == ""


def test_fit_reports_a_geometry_limit_near_the_meridian():
    # A few samples all within 4 deg of H=0 cannot separate cosH from 1, so
    # the fit is the best estimate but the reason code must warn (ADR-007's
    # "the Sun's geometry limits which error can be separated").
    latitude = 40.0
    samples = _synthetic_samples(30.0, -20.0, latitude,
                                 [-4.0, -2.0, 0.0, 2.0, 4.0])
    result = polar.fit_polar_alignment(samples, latitude)
    assert result.ok
    assert result.reason_code == "geometry_limit"


def test_fit_needs_three_samples():
    result = polar.fit_polar_alignment(
        _synthetic_samples(10.0, 10.0, 40.0, [0.0, 10.0]), 40.0)
    assert not result.ok
    assert result.reason_code == "not_enough_samples"


def test_session_progress_and_confirmation():
    latitude = 40.0
    session = polar.PolarAlignmentSession(latitude, required_samples=5)
    samples = _synthetic_samples(40.0, 10.0, latitude,
                                 [-70.0, -35.0, 0.0, 35.0, 70.0])
    progress = []
    for sample in samples:
        progress.append(session.add_sample(sample, progress.append))
    assert progress[-1].samples == 5
    assert progress[-1].progress == pytest.approx(1.0)
    first = session.result()
    assert first.ok
    assert first.altitude_error_arcsec == pytest.approx(40.0, abs=1e-6)

    # After the correction the second measurement must confirm the alignment.
    corrected = _synthetic_samples(0.0, 0.0, latitude,
                                   [-70.0, -35.0, 0.0, 35.0, 70.0])
    second = session.confirm(corrected)
    assert second.ok
    assert second.confirmation
    assert abs(second.azimuth_error_arcsec) < 1e-6


def test_session_confirmation_fails_when_the_error_is_still_large():
    latitude = 40.0
    session = polar.PolarAlignmentSession(latitude, required_samples=5,
                                          tolerance_arcsec=10.0)
    samples = _synthetic_samples(120.0, 0.0, latitude,
                                 [-70.0, -35.0, 0.0, 35.0, 70.0])
    result = session.confirm(samples)
    assert result.ok
    assert not result.confirmation
