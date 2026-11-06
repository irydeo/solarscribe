############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg geometry module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Geometry of the scan: plate scale, the 1/cos(Dec) RA-rate correction and the
# chord of the solar disk at a slit offset.
#
# Units follow ARCHITECTURE 2: RA in hours, Dec in degrees, angles in
# arcseconds, rates in arcseconds per second. The functions here are pure and
# take numbers, so they are tested without a mount or a camera.
#
# External references for every formula:
#   - 206264.806" is the number of arcseconds in a radian (the small-angle
#     formula s = f * theta); 206265 is the rounded value used by the
#     nightscribe-scan prototype and by every plate-scale calculator.
#   - One hour of RA is 15 degrees = 54000 arcseconds (Meeus, Astronomical
#     Algorithms, ch. 1: 24 h = 360 deg).
#   - A degree of RA at declination d subtends cos(d) degrees on the sky; this
#     is the spherical right triangle that gives the 1/cos(Dec) correction.
#   - The chord of a circle of radius R at a perpendicular distance e from the
#     centre is L = 2*sqrt(R^2 - e^2) (Pythagoras, the same relation ADR-006
#     quotes). The slit has length S, so its nearest edge to the disk centre is
#     e = max(0, |q| - S/2) for a slip centre offset q.

from __future__ import annotations

import math

__all__ = [
    "ARCSEC_PER_RAD",
    "ARCSEC_PER_RA_HOUR",
    "chord_arcsec",
    "cos_dec_correction",
    "cos_dec_factor",
    "dead_zone_arcsec",
    "effective_slit_arcsec",
    "expected_chord_arcsec",
    "measure_slit_scale",
    "offset_from_chord",
    "pixel_scale_arcsec_px",
    "ra_diff_arcsec",
    "ra_rate_from_sky_rate",
    "sky_rate_from_ra_rate",
    "slit_image_scale",
    "slit_plate_scale_arcsec_px",
]

# 360*3600/(2*pi). The prototype rounds it to 206265; the difference is 4e-6
# relative, far below the 2 um pixel and the 714 mm focal tolerances.
ARCSEC_PER_RAD = 206264.80624709636

# One hour of right ascension: 15 degrees, each of 3600 arcseconds.
ARCSEC_PER_RA_HOUR = 15.0 * 3600.0


# @args: focal_length_mm - effective focal length at the sensor
#        pixel_size_um - camera pixel pitch
# @return: arcseconds of sky per pixel at the focal plane
# Small-angle formula: a pixel of p metres at focal length f subtends p/f rad.
# Reference instrument: 714 mm and 2 um give 0.5778"/px, the figure the
# prototype uses for the SHG-700.
def pixel_scale_arcsec_px(focal_length_mm: float, pixel_size_um: float) -> float:
    if focal_length_mm <= 0 or pixel_size_um <= 0:
        raise ValueError("focal length and pixel size must be positive")
    return ARCSEC_PER_RAD * (pixel_size_um / 1000.0) / focal_length_mm


# @args: solar_diameter_arcsec - apparent diameter from the ephemeris
#        extent_px - illuminated extent along the slit, in pixels
# @return: arcseconds per pixel along the slit axis
# When the disk is centred on the slit, the illuminated extent is the full
# diameter, so the slit-axis plate scale is D/extent. ADR-006 and the prototype
# (measure_slit_scale) use exactly this.
def slit_plate_scale_arcsec_px(solar_diameter_arcsec: float,
                               extent_px: float) -> float:
    if extent_px <= 0:
        raise ValueError("extent must be positive")
    return solar_diameter_arcsec / extent_px


# @args: scan_arcsec_px - plate scale along the scan (RA) axis
#        slit_arcsec_px - plate scale along the slit (Dec) axis
# @return: slit re-imaging magnification, sensor pixels per mm of slit
# The prototype measures this as PIXEL_SCALE / S_Y. A factor of 1 means the
# spectrograph re-images the slit 1:1; the 2026-11 reference data needed ~1.28
# because the slit axis is compressed in the recon, and using 1.0 made the row
# step tile the mosaic wrongly.
def slit_image_scale(scan_arcsec_px: float, slit_arcsec_px: float) -> float:
    if slit_arcsec_px <= 0:
        raise ValueError("slit plate scale must be positive")
    return scan_arcsec_px / slit_arcsec_px


# @args: slit_length_mm - physical length of the slit
#        image_scale - slit re-imaging magnification (1.0 = 1:1)
#        pixel_size_um - camera pixel pitch
#        roi_width_px - width of the captured frame along the slit
#        scan_arcsec_px - plate scale along the scan axis
# @return: angular length of the slit actually sampled by the ROI, arcsec
# The physical slit projects to slit_length_mm*image_scale/pixel_size_um sensor
# pixels. The camera may only sample part of it (the ROI width). The sky angle
# per slit pixel is scan_arcsec_px/image_scale because the slit axis is
# magnified by image_scale relative to the scan axis.
# Reference: 7 mm at 714 mm focal subtends 7/714 rad = 33.7', just over the
# ~32' solar diameter (ARCHITECTURE 3.2), which is why one row can cover it.
def effective_slit_arcsec(slit_length_mm: float, image_scale: float,
                          pixel_size_um: float, roi_width_px: int,
                          scan_arcsec_px: float) -> float:
    if slit_length_mm <= 0 or image_scale <= 0 or pixel_size_um <= 0:
        raise ValueError("slit length, image scale and pixel size must be positive")
    slit_px = slit_length_mm * image_scale * 1000.0 / pixel_size_um
    sampled_px = min(float(roi_width_px), slit_px)
    return sampled_px * scan_arcsec_px / image_scale


# @args: dec_deg - declination of the observed point
#        floor - lower bound of cos(Dec), to keep a near-pole mount sane
# @return: the factor that converts a sky rate to an RA coordinate rate
# A degree of RA is cos(Dec) degrees on the sky. Near the pole cos(Dec) goes to
# zero and the coordinate rate explodes, so the prototype clamps it at 0.5
# (Dec ~60 deg); the scan never goes there, but a bad Dec read must not divide
# by zero.
def cos_dec_factor(dec_deg: float, floor: float = 0.5) -> float:
    return 1.0 / max(floor, math.cos(math.radians(dec_deg)))


# @args: sky_rate_arcsec_s - desired rate on the sky, arcsec/s
#        dec_deg - declination of the sweep
#        floor - lower bound of cos(Dec)
# @return: the RA coordinate rate the mount must be given, arcsec/s
# The mount's RA rate is a coordinate rate. At Dec 60 deg it must run twice as
# fast to move the sky at the same angular rate.
def ra_rate_from_sky_rate(sky_rate_arcsec_s: float, dec_deg: float,
                          floor: float = 0.5) -> float:
    return sky_rate_arcsec_s * cos_dec_factor(dec_deg, floor)


# @args: ra_rate_arcsec_s - RA coordinate rate
#        dec_deg - declination
#        floor - lower bound of cos(Dec)
# @return: the rate on the sky, arcsec/s
def sky_rate_from_ra_rate(ra_rate_arcsec_s: float, dec_deg: float,
                          floor: float = 0.5) -> float:
    return ra_rate_arcsec_s / cos_dec_factor(dec_deg, floor)


# @args: ra1_h - first right ascension, hours
#        ra2_h - second right ascension, hours
# @return: signed (ra1 - ra2) in arcseconds, shortest arc across 0/24 h
# A naive 23.9 h - 0.1 h gives 23.8 h, but the short arc is 0.2 h. One hour is
# 54000". The prototype (ra_diff_arcsec) uses the same +/-12 h wrap.
def ra_diff_arcsec(ra1_h: float, ra2_h: float) -> float:
    diff = ra1_h - ra2_h
    if diff > 12.0:
        diff -= 24.0
    elif diff < -12.0:
        diff += 24.0
    return diff * ARCSEC_PER_RA_HOUR


# @args: dec_offset_arcsec - signed Dec offset of the slit centre from the disk
#                            centre
#        slit_arcsec - effective slit length on the sky
#        solar_diameter_arcsec - apparent solar diameter
# @return: the on-disk RA chord the slit can cross, arcsec (0 when off disk)
# The slit is a segment of length S along Dec. The point of the slit closest to
# the disk centre is at e = max(0, |q| - S/2). The longest chord the scan can
# meet is 2*sqrt(R^2 - e^2). Inside |q| < S/2 the chord is the full diameter:
# that is the dead zone ADR-006 warns about.
def chord_arcsec(dec_offset_arcsec: float, slit_arcsec: float,
                 solar_diameter_arcsec: float) -> float:
    radius = solar_diameter_arcsec / 2.0
    edge = max(0.0, abs(dec_offset_arcsec) - slit_arcsec / 2.0)
    if edge >= radius:
        return 0.0
    return 2.0 * math.sqrt(max(radius * radius - edge * edge, 0.0))


# @args: chord_arcsec_value - measured chord, arcsec
#        slit_arcsec - effective slit length on the sky
#        solar_diameter_arcsec - apparent solar diameter
# @return: (absolute slit offset, nearest slit edge distance), arcsec
# The inverse of chord_arcsec: e = sqrt(R^2 - (L/2)^2) and |q| = e + S/2.
# It gives the MAGNITUDE only; the sign needs a probe (the chord is symmetric
# in q), which is what centering.chord_center does.
def offset_from_chord(chord_arcsec_value: float, slit_arcsec: float,
                      solar_diameter_arcsec: float) -> tuple[float, float]:
    radius = solar_diameter_arcsec / 2.0
    half = min(chord_arcsec_value / 2.0, radius)
    edge = math.sqrt(max(radius * radius - half * half, 0.0))
    return edge + max(slit_arcsec, 0.0) / 2.0, edge


# @args: slit_arcsec - effective slit length on the sky
# @return: the half-width of the chord dead zone, arcsec
# Inside |q| < S/2 the chord is the full diameter and cannot resolve the
# offset: the derivative of 2*sqrt(R^2 - q^2) is zero at q = 0. The UI must
# state this figure next to the fine centring result.
def dead_zone_arcsec(slit_arcsec: float) -> float:
    return max(slit_arcsec, 0.0) / 2.0


# Prototype names, kept as aliases so a reader coming from nightscribe-scan
# finds the function under the name the parity note uses.
cos_dec_correction = cos_dec_factor
expected_chord_arcsec = chord_arcsec
measure_slit_scale = slit_plate_scale_arcsec_px
