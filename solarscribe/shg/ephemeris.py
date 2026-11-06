############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg ephemeris module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Local solar ephemeris (ADR-021: no network). It gives the Sun's apparent
# right ascension and declination, its apparent diameter, the local hour angle,
# the altitude and azimuth at the observatory, and the physical disk figures
# P, B0 and L0 for the sky calendar (Meeus ch. 29).
#
# Reference: USNO, "Computing Approximate Solar Coordinates"
# (https://aa.usno.navy.mil/faq/sun_approx), the same low-precision algorithm
# as The Astronomical Almanac page C5. It is good to about 1 arcminute for the
# coordinates and a few arcseconds for the diameter within two centuries of
# 2000, far better than what GOTO and the scan geometry need.
#
#   g = 357.529 + 0.98560028 D          mean anomaly, degrees
#   q = 280.459 + 0.98564736 D          mean longitude, degrees
#   L = q + 1.915 sin g + 0.020 sin 2g  apparent ecliptic longitude, degrees
#   R = 1.00014 - 0.01671 cos g - 0.00014 cos 2g   Earth-Sun distance, AU
#   e = 23.439 - 0.00000036 D           mean obliquity, degrees
#   tan RA = cos e sin L / cos L, sin Dec = sin e sin L
#   SD = 959.63" / R                    solar semidiameter at 1 AU
#
# The 959.63" semidiameter at 1 AU is the Astronomical Almanac value and the
# one the nightscribe-scan prototype uses (ephemeris_solar_diameter). The USNO
# page quotes SD = 0.2666 deg / R, which is 959.76"/R; the 0.13" difference is
# below the ephemeris accuracy and well below one pixel.
#
# The observatory location enters through the local sidereal time and the
# horizon conversion. The geocentric RA/Dec are location independent. The
# topocentric parallax (at most 8.8" at the horizon) is not applied: it is far
# below the GOTO pointing tolerance and the slit width.

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

__all__ = [
    "SolarEphemeris",
    "SolarPosition",
    "SolarRotation",
    "altitude_azimuth",
    "delta_t_seconds",
    "ephemeris_solar_diameter",
    "hour_angle_deg",
    "julian_date",
    "julian_date_components",
    "local_sidereal_time_hours",
    "solar_ephemeris",
    "solar_position",
    "solar_position_now",
    "solar_rotation",
]

# Solar semidiameter at 1 AU, arcseconds (Astronomical Almanac).
SOLAR_SEMIDIAMETER_1AU_ARCSEC = 959.63

# J2000.0 epoch, 2000 January 1.5 (Meeus, Astronomical Algorithms, ch. 7).
J2000_JD = 2451545.0


@dataclass(frozen=True)
class SolarEphemeris:
    # Geocentric apparent position of the Sun at one instant.
    julian_date: float
    ra_hours: float                 # 0 to 24
    dec_deg: float                  # -90 to +90
    diameter_arcsec: float          # apparent equatorial diameter
    distance_au: float
    mean_anomaly_deg: float
    ecliptic_longitude_deg: float
    obliquity_deg: float


@dataclass(frozen=True)
class SolarRotation:
    # Physical ephemeris for the Sun's disk (Meeus ch. 29, Carrington):
    #   P  - position angle of the solar north pole, measured eastwards from
    #        celestial north; positive east, negative west, |P| < 90 deg.
    #   B0 - heliographic latitude of the centre of the disk, positive north.
    #   L0 - heliographic longitude of the centre of the disk, 0 to 360 deg.
    # The UI needs them for the sky calendar's Sun tab (DESIGN.md 9): they say
    # how the solar rotation axis is tilted and where the disk centre sits in
    # Carrington coordinates.
    position_angle_deg: float
    heliographic_latitude_deg: float
    heliographic_longitude_deg: float
    delta_t_days: float


@dataclass(frozen=True)
class SolarPosition:
    # Everything the app needs to point at the Sun and to draw it: the
    # geocentric coordinates, the local hour angle, the horizon position and
    # the physical disk figures.
    julian_date: float
    ra_hours: float
    dec_deg: float
    diameter_arcsec: float
    distance_au: float
    local_sidereal_time_hours: float
    hour_angle_deg: float           # -180 to +180, positive west
    altitude_deg: float
    azimuth_deg: float              # 0 north, 90 east, 180 south, 270 west
    position_angle_deg: float = 0.0
    heliographic_latitude_deg: float = 0.0
    heliographic_longitude_deg: float = 0.0


# @args: year, month, day, hour, minute, second - UTC calendar components
# @return: Julian date (UTC), days
# Meeus ch. 7. The integer shifts put January and February in the previous
# year, and b is the Gregorian correction. The epoch check is the external
# anchor: 2000-01-01 12:00 UTC must give exactly 2451545.0.
def julian_date_components(year: int, month: int, day: int,
                           hour: int = 0, minute: int = 0,
                           second: float = 0.0) -> float:
    y = year
    mo = month
    if mo <= 2:
        y -= 1
        mo += 12
    a = y // 100
    b = 2 - a + a // 4
    jd = (int(365.25 * (y + 4716)) + int(30.6001 * (mo + 1)) + day + b
          - 1524.5)
    day_fraction = (hour + minute / 60.0 + second / 3600.0) / 24.0
    return jd + day_fraction


# @args: when - a datetime; a naive one is taken as UTC, an aware one is
#              converted to UTC
# @return: Julian date (UTC)
def julian_date(when: datetime) -> float:
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    return julian_date_components(
        when.year, when.month, when.day,
        when.hour, when.minute, when.second + when.microsecond / 1e6,
    )


# @args: jd - Julian date (UTC)
# @return: the geocentric apparent position and the apparent diameter
def solar_ephemeris(jd: float) -> SolarEphemeris:
    d = jd - J2000_JD
    g = (357.529 + 0.98560028 * d) % 360.0
    q = (280.459 + 0.98564736 * d) % 360.0
    g_rad = math.radians(g)
    longitude = (q + 1.915 * math.sin(g_rad)
                 + 0.020 * math.sin(2.0 * g_rad)) % 360.0
    distance = (1.00014 - 0.01671 * math.cos(g_rad)
                - 0.00014 * math.cos(2.0 * g_rad))
    obliquity = 23.439 - 0.00000036 * d
    lon_rad = math.radians(longitude)
    obl_rad = math.radians(obliquity)
    ra_deg = math.degrees(math.atan2(
        math.cos(obl_rad) * math.sin(lon_rad), math.cos(lon_rad)))
    dec_deg = math.degrees(math.asin(
        math.sin(obl_rad) * math.sin(lon_rad)))
    return SolarEphemeris(
        julian_date=jd,
        ra_hours=(ra_deg % 360.0) / 15.0,
        dec_deg=dec_deg,
        diameter_arcsec=2.0 * SOLAR_SEMIDIAMETER_1AU_ARCSEC / distance,
        distance_au=distance,
        mean_anomaly_deg=g,
        ecliptic_longitude_deg=longitude,
        obliquity_deg=obliquity,
    )


# @args: jd - Julian date (UTC)
#        longitude_deg - observatory longitude, east positive
# @return: Greenwich mean sidereal time plus the longitude, in hours [0, 24)
# The standard expansion GMST = 18.697374558 + 24.06570982441908 D hours
# (USNO; Meeus 12.4). D is days from J2000.0. At J2000 12:00 UT it gives
# 18.697374558 h = 18h 41m 50.55s, the published value. The Sun's apparent RA
# already includes the equation of the equinoxes to the precision we need, so
# mean sidereal time is enough; the nutation term is below 1.2 s of time.
def local_sidereal_time_hours(jd: float, longitude_deg: float) -> float:
    d = jd - J2000_JD
    gmst = (18.697374558 + 24.06570982441908 * d) % 24.0
    return (gmst + longitude_deg / 15.0) % 24.0


# @args: lst_hours - local sidereal time, hours
#        ra_hours - right ascension, hours
# @return: local hour angle in degrees, [-180, +180), positive west
def hour_angle_deg(lst_hours: float, ra_hours: float) -> float:
    ha = ((lst_hours - ra_hours) * 15.0 + 180.0) % 360.0 - 180.0
    return ha


# @args: dec_deg - declination, degrees
#        hour_angle_deg_value - hour angle, degrees
#        latitude_deg - observatory latitude, north positive
# @return: (altitude, azimuth) in degrees; azimuth from north through east
# Standard spherical astronomy (Meeus ch. 13 / any navigation almanac):
#   sin h = sin(lat) sin(dec) + cos(lat) cos(dec) cos(H)
#   sin A = -sin H cos dec / cos h
#   cos A = (sin dec - sin h sin lat) / (cos h cos lat)
# Writing it directly as atan2(y, x) needs no division by cos h, which would
# blow up at the zenith:
#   y = -sin H cos dec
#   x = sin dec cos lat - sin lat cos dec cos H
# At the meridian (H=0) in the northern hemisphere x < 0 for dec < lat, so the
# azimuth is 180 deg (south), which is the physical anchor the test uses.
def altitude_azimuth(dec_deg: float, hour_angle_deg_value: float,
                     latitude_deg: float) -> tuple[float, float]:
    dec = math.radians(dec_deg)
    ha = math.radians(hour_angle_deg_value)
    lat = math.radians(latitude_deg)
    sin_alt = (math.sin(lat) * math.sin(dec)
               + math.cos(lat) * math.cos(dec) * math.cos(ha))
    sin_alt = max(-1.0, min(1.0, sin_alt))
    altitude = math.degrees(math.asin(sin_alt))
    y = -math.sin(ha) * math.cos(dec)
    x = (math.sin(dec) * math.cos(lat)
         - math.sin(lat) * math.cos(dec) * math.cos(ha))
    azimuth = math.degrees(math.atan2(y, x)) % 360.0
    return altitude, azimuth


# @args: jd - Julian date (UTC)
# @return: an estimate of Delta T = TT - UT, seconds
# The rotation angle and L0 advance 0.9856 deg/day, so 70 s of Delta T move
# them only 0.0008 deg (3"). The estimate is still included because the
# published Meeus example uses TT and the difference is what makes L0 match
# 238.63 instead of 238.64. The polynomials are the NASA/Espenak fits quoted
# by Meeus ch. 10: 1986-2005 and 2005-2050, with the 2050-2150 branch and a
# 69 s fallback for dates outside the table. The fallback is exact enough for
# a calendar, never for a precise orbit.
def delta_t_seconds(jd: float) -> float:
    year = 2000.0 + (jd - J2000_JD) / 365.25
    t = year - 2000.0
    if 2005.0 <= year < 2050.0:
        return 62.92 + 0.32217 * t + 0.005589 * t * t
    if 1986.0 <= year < 2005.0:
        return (63.86 + 0.3345 * t - 0.060374 * t ** 2
                + 0.0017275 * t ** 3 + 0.000651814 * t ** 4
                + 0.00002373599 * t ** 5)
    if 2050.0 <= year < 2150.0:
        u = (year - 1820.0) / 100.0
        return -20.0 + 32.0 * u * u - 0.5628 * (2150.0 - year)
    return 69.0


# @args: jd - Julian date (UTC)
#        delta_t_days - TT - UT in days; None estimates it with delta_t_seconds
# @return: the solar P, B0 and L0 figures for that instant
# Meeus, Astronomical Algorithms, 2nd ed., ch. 29, "Ephemeris for Physical
# Observations of the Sun" (the Carrington formulas):
#
#   theta = (JD - 2398220) * 360/25.38       Carrington rotation angle
#   K     = 73.6667 + 1.3958333 (JD - 2396758)/36525
#   x     = atan(-cos(lambda') tan(epsilon))  with lambda' apparent longitude
#   y     = atan(-cos(lambda - K) tan(7.25))
#   P     = x + y
#   sin B0 = sin(lambda - K) sin(7.25)
#   eta   = atan(tan(lambda - K) cos(7.25))
#   L0    = eta - theta, reduced to 0..360
#
# The Meeus example 29.a is the external anchor: 1992 October 13 0h UT
# (JD 2448908.5) gives P = 26.27 deg, B0 = +5.99 deg, L0 = 238.63 deg.
# Our low-precision solar longitude reproduces them to 0.01 deg (the test
# passes delta_t_days=0.00068, the example's TT-UT, so L0 lands on 238.63).
#
# The nutation in longitude is the main term, -0.004778 sin(Omega), and the
# apparent obliquity is epsilon = epsilon0 + 0.00256 cos(Omega): below the
# 0.01 deg the example prints, but included because both are the same Omega
# the solar-coordinate algorithm already carries.
def solar_rotation(jd: float,
                   delta_t_days: float | None = None) -> SolarRotation:
    if delta_t_days is None:
        delta_t_days = delta_t_seconds(jd) / 86400.0
    jde = jd + delta_t_days
    body = solar_ephemeris(jde)
    t = (jde - J2000_JD) / 36525.0
    omega = 125.04 - 1934.136 * t
    omega_rad = math.radians(omega)
    obliquity = body.obliquity_deg + 0.00256 * math.cos(omega_rad)
    longitude = body.ecliptic_longitude_deg
    # Apparent longitude for the P term: the USNO longitude already carries
    # aberration; add the main nutation term to make it the apparent one.
    apparent_longitude = longitude - 0.004778 * math.sin(omega_rad)
    inclination = math.radians(7.25)
    node = 73.6667 + 1.3958333 * (jde - 2396758.0) / 36525.0
    theta = (jde - 2398220.0) * 360.0 / 25.38

    x = math.degrees(math.atan(
        -math.cos(math.radians(apparent_longitude))
        * math.tan(math.radians(obliquity))))
    delta = longitude - node
    delta_rad = math.radians(delta)
    y = math.degrees(math.atan(
        -math.cos(delta_rad) * math.tan(inclination)))
    position_angle = x + y
    # The Sun's convention keeps |P| < 90 deg: the formula's principal atan
    # values can sum just outside that band, so fold it back.
    if position_angle > 90.0:
        position_angle -= 180.0
    elif position_angle < -90.0:
        position_angle += 180.0
    b0 = math.degrees(math.asin(
        math.sin(delta_rad) * math.sin(inclination)))
    eta = math.degrees(math.atan(
        math.tan(delta_rad) * math.cos(inclination)))
    l0 = (eta - theta) % 360.0
    return SolarRotation(
        position_angle_deg=position_angle,
        heliographic_latitude_deg=b0,
        heliographic_longitude_deg=l0,
        delta_t_days=delta_t_days,
    )


# @args: when - UTC datetime of the observation
#        latitude_deg, longitude_deg - observatory position, north and east
#                                       positive
#        elevation_m - observatory elevation, metres (kept for the caller and
#                      the log; the topocentric correction is not applied)
# @return: the solar position, diameter, hour angle, horizon coordinates and
#          the physical disk figures
def solar_position(when: datetime, latitude_deg: float,
                   longitude_deg: float,
                   elevation_m: float = 0.0) -> SolarPosition:
    jd = julian_date(when)
    body = solar_ephemeris(jd)
    rotation = solar_rotation(jd)
    lst = local_sidereal_time_hours(jd, longitude_deg)
    ha = hour_angle_deg(lst, body.ra_hours)
    altitude, azimuth = altitude_azimuth(body.dec_deg, ha, latitude_deg)
    return SolarPosition(
        julian_date=jd,
        ra_hours=body.ra_hours,
        dec_deg=body.dec_deg,
        diameter_arcsec=body.diameter_arcsec,
        distance_au=body.distance_au,
        local_sidereal_time_hours=lst,
        hour_angle_deg=ha,
        altitude_deg=altitude,
        azimuth_deg=azimuth,
        position_angle_deg=rotation.position_angle_deg,
        heliographic_latitude_deg=rotation.heliographic_latitude_deg,
        heliographic_longitude_deg=rotation.heliographic_longitude_deg,
    )


# @args: latitude_deg, longitude_deg - observatory position
#        elevation_m - observatory elevation
# @return: the solar position at the current UTC instant
def solar_position_now(latitude_deg: float, longitude_deg: float,
                       elevation_m: float = 0.0) -> SolarPosition:
    return solar_position(datetime.now(timezone.utc), latitude_deg,
                          longitude_deg, elevation_m)


# @args: when - UTC instant; None means now
# @return: the apparent solar diameter in arcseconds
# The prototype's ephemeris_solar_diameter, with the instant explicit so the
# result is reproducible and testable. It returns 0.0 only when the platform
# has no clock, which cannot happen with datetime.
def ephemeris_solar_diameter(when: datetime | None = None) -> float:
    moment = when or datetime.now(timezone.utc)
    return solar_ephemeris(julian_date(moment)).diameter_arcsec
