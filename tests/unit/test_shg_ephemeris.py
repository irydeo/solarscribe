############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg ephemeris test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# External anchors: the USNO "Computing Approximate Solar Coordinates" page
# (the algorithm this module ports) and JPL Horizons DE441, queried for the
# geocentric apparent RA/Dec and angular diameter at the instants below. The
# low-precision algorithm is good to ~1 arcmin, so the tolerances are 3 s of
# time in RA, 20" in Dec and 2" in diameter; the diameter is anchored to the
# Astronomical Almanac semidiameter at 1 AU (959.63").

from datetime import datetime, timezone

import pytest

from solarscribe.shg import ephemeris

# (UTC, apparent RA hours, apparent Dec deg, diameter arcsec) from Horizons.
HORIZONS = [
    ("2000-01-01T12:00:00", 18 + 45 / 60 + 6.81 / 3600, -23.03242, 1950.990),
    ("2026-01-03T12:00:00", 18 + 56 / 60 + 59.77 / 3600, -22.79158, 1951.041),
    ("2026-03-20T14:46:00", 23 + 59 / 60 + 59.99 / 3600, 0.00008, 1926.327),
    ("2026-06-21T12:00:00", 6 + 0 / 60 + 37.36 / 3600, 23.43786, None),
    ("2026-07-04T00:00:00", 6 + 52 / 60 + 26.72 / 3600, 22.89064, 1887.083),
    ("2026-12-21T20:50:00", 17 + 59 / 60 + 59.95 / 3600, -23.43742, 1950.190),
]


def _when(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def test_julian_date_epoch_is_the_external_anchor():
    # Meeus, Astronomical Algorithms, ch. 7: 2000 Jan 1.5 is JD 2451545.0.
    assert ephemeris.julian_date_components(2000, 1, 1, 12, 0, 0) == pytest.approx(
        2451545.0, abs=1e-9)


@pytest.mark.parametrize("text,ra_hours,dec_deg,diameter", HORIZONS)
def test_solar_position_matches_jpl_horizons(text, ra_hours, dec_deg, diameter):
    when = _when(text)
    body = ephemeris.solar_ephemeris(ephemeris.julian_date(when))
    # RA wraps at 0/24 h; compare on the short arc.
    ra_error_seconds = abs(geometry_ra_diff(body.ra_hours, ra_hours)) * 3600.0
    assert ra_error_seconds < 3.0
    assert body.dec_deg == pytest.approx(dec_deg, abs=20.0 / 3600.0)
    if diameter is not None:
        assert body.diameter_arcsec == pytest.approx(diameter, abs=2.0)


def geometry_ra_diff(ra1: float, ra2: float) -> float:
    # Local short-arc difference in hours, so a 0/24 wrap does not fail the
    # comparison (the same trick as geometry.ra_diff_arcsec).
    diff = ra1 - ra2
    if diff > 12:
        diff -= 24
    elif diff < -12:
        diff += 24
    return diff


def test_diameter_runs_between_perihelion_and_aphelion():
    # The apparent diameter is ~1887" at aphelion and ~1951" at perihelion
    # (Horizons, 2026): the annual 3% variation the prototype tracks.
    perihelion = ephemeris.solar_ephemeris(
        ephemeris.julian_date(_when("2026-01-03T12:00:00")))
    aphelion = ephemeris.solar_ephemeris(
        ephemeris.julian_date(_when("2026-07-04T00:00:00")))
    assert 1948.0 < perihelion.diameter_arcsec < 1954.0
    assert 1884.0 < aphelion.diameter_arcsec < 1890.0
    assert perihelion.diameter_arcsec > aphelion.diameter_arcsec
    # The prototype-name alias must agree with the dataclass path.
    assert ephemeris.ephemeris_solar_diameter(
        _when("2026-01-03T12:00:00")) == pytest.approx(
            perihelion.diameter_arcsec)


def test_greenwich_sidereal_time_at_j2000():
    # Meeus 12.4 / USNO: GMST at 2000 Jan 1 12h UT = 18h 41m 50.55s.
    gmst = ephemeris.local_sidereal_time_hours(2451545.0, 0.0)
    assert gmst == pytest.approx(18.697374558, abs=1e-9)
    assert gmst * 3600.0 == pytest.approx(18 * 3600 + 41 * 60 + 50.55, abs=0.1)


def test_hour_angle_wraps_to_the_short_arc():
    assert ephemeris.hour_angle_deg(0.1, 23.9) == pytest.approx(3.0)  # 0.2h*15
    assert ephemeris.hour_angle_deg(23.9, 0.1) == pytest.approx(-3.0)


def test_altitude_azimuth_at_the_meridian_is_a_physical_anchor():
    # At H=0 the Sun is due south in the northern hemisphere and its altitude
    # is 90 - |lat - dec|; with dec=0 and lat=40 that is 50 deg, azimuth 180.
    altitude, azimuth = ephemeris.altitude_azimuth(0.0, 0.0, 40.0)
    assert altitude == pytest.approx(50.0, abs=1e-9)
    assert azimuth == pytest.approx(180.0, abs=1e-9)
    # At the eastern horizon (H=-90) the azimuth is east (90 deg).
    _alt, az_east = ephemeris.altitude_azimuth(0.0, -90.0, 40.0)
    assert az_east == pytest.approx(90.0, abs=1e-9)


def test_solar_position_at_madrid_midsummer_is_high_and_south():
    # Madrid (40.4 N, 3.7 W) on 2026-06-21 at 12:00 UTC: the Sun is near the
    # meridian, high (altitude > 60 deg) and south (azimuth ~180 deg).
    when = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    position = ephemeris.solar_position(when, 40.4, -3.7)
    assert position.altitude_deg > 60.0
    assert 150.0 < position.azimuth_deg < 210.0
    assert position.diameter_arcsec > 1880.0


def test_solar_rotation_matches_meeus_example_29a():
    # Meeus, Astronomical Algorithms, 2nd ed., Example 29.a: 1992 October 13
    # at 0h UT (JD 2448908.5) gives P = 26.27 deg, B0 = +5.99 deg,
    # L0 = 238.63 deg. The example uses TT; 0.00068 day is its TT-UT.
    jd = ephemeris.julian_date(
        datetime(1992, 10, 13, 0, 0, tzinfo=timezone.utc))
    rotation = ephemeris.solar_rotation(jd, delta_t_days=0.00068)
    assert rotation.position_angle_deg == pytest.approx(26.27, abs=0.02)
    assert rotation.heliographic_latitude_deg == pytest.approx(5.99, abs=0.02)
    assert rotation.heliographic_longitude_deg == pytest.approx(238.63, abs=0.02)


def test_solar_rotation_stays_inside_the_physical_bounds():
    # The solar axis is inclined 7.25 deg to the ecliptic normal, so B0 never
    # leaves +/-7.25 and P never leaves the ~30 deg between the solar axis and
    # the celestial pole. L0 is a longitude and lives in [0, 360).
    for text in ("2026-01-03T12:00:00", "2026-06-21T12:00:00",
                 "2026-12-21T20:50:00"):
        rotation = ephemeris.solar_rotation(
            ephemeris.julian_date(_when(text)))
        assert abs(rotation.position_angle_deg) <= 31.0
        assert abs(rotation.heliographic_latitude_deg) <= 7.25
        assert 0.0 <= rotation.heliographic_longitude_deg < 360.0


def test_solar_position_carries_the_rotation_figures():
    when = _when("2026-06-21T12:00:00")
    position = ephemeris.solar_position(when, 40.4, -3.7)
    rotation = ephemeris.solar_rotation(ephemeris.julian_date(when))
    assert position.position_angle_deg == pytest.approx(
        rotation.position_angle_deg)
    assert position.heliographic_latitude_deg == pytest.approx(
        rotation.heliographic_latitude_deg)
    assert position.heliographic_longitude_deg == pytest.approx(
        rotation.heliographic_longitude_deg)


def test_delta_t_is_physical_for_the_modern_era():
    # TT-UT is ~59 s in 1992 and ~75 s in 2026 (NASA/Espenak fits). The exact
    # second is not the point: a 10 s error moves L0 by 0.0001 deg.
    jd_1992 = ephemeris.julian_date(
        datetime(1992, 10, 13, 0, 0, tzinfo=timezone.utc))
    jd_2026 = ephemeris.julian_date(_when("2026-06-21T12:00:00"))
    assert 50.0 < ephemeris.delta_t_seconds(jd_1992) < 65.0
    assert 60.0 < ephemeris.delta_t_seconds(jd_2026) < 90.0
