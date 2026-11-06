############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg polar module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Solar polar alignment assistant (ADR-007).
#
# Polaris is not visible by day, but the Sun on the slit gives a precise Dec
# reference. With the mount tracking, a polar axis offset makes the Sun's Dec
# drift. The assistant samples the Dec every few minutes, subtracts the Sun's
# own Dec motion from the local ephemeris (ADR-021), and fits the drift.
#
# Physics, derived from the rotation vectors (and verified against the classic
# drift procedure, AstroPixels/F. Espenak, "Polar Alignment Using Drift
# Method"):
#
#   d(Dec)/dt = -omega * [ alpha * sin(H) + beta * cos(lat) * cos(H) ]
#
# where omega = 15.041067"/s (one sidereal day = 86164.0905 s), H is the local
# hour angle, alpha is the altitude error (positive = polar axis too high) and
# beta is the azimuth error (positive = axis east of the pole), both in radians.
# The two terms are why the classic procedure measures:
#   - azimuth near the meridian (H = 0): only beta contributes;
#   - altitude near the eastern or western horizon (H = +/-90 deg): only alpha
#     contributes.
# AstroPixels' tables agree on the signs: azimuth east drifts the star south
# at the meridian; altitude too high drifts it south at the western horizon and
# north at the eastern one.
#
# ADR-007's prose recommends the opposite pairing ("meridian for altitude,
# east/west for azimuth"). That sentence contradicts the rotation-vector
# derivation and the published drift procedure; the implementation follows the
# physics and recommends meridian for azimuth, east/west for altitude. The
# discrepancy is reported to the lead/docs agent; the ADR is not rewritten
# here (accepted ADRs are not edited).
#
# The fit uses the integrated form, not a straight line through the raw Dec:
#
#   y(t) = Dec_measured - Dec_ephemeris = y0 + alpha*cos(H) - beta*cos(lat)*sin(H)
#
# which is exact for a constant misalignment while H advances linearly. A
# straight line in time is only its small-angle limit and cannot separate the
# two errors. The basis (1, cos H, sin H) does separate them, but only if the
# samples span enough hour angle; the condition number of that basis is
# reported as `geometry_limit` when the session is too short, because the Sun's
# geometry limits what can be separated at any moment (ADR-007's consequence).

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np

from .abc import PolarProgress, PolarResult, PolarSample

__all__ = [
    "EARTH_ROTATION_ARCSEC_S",
    "PolarAlignmentSession",
    "drift_rate_arcsec_s",
    "fit_polar_alignment",
]

# Sidereal rotation rate: 360 deg / 86164.0905 s, in arcseconds per second.
# The external check: one sidereal day is 23h56m04.0905s, and the prototype's
# SIDEREAL constant is 15.04"/s per multiplier unit.
EARTH_ROTATION_ARCSEC_S = 360.0 * 3600.0 / 86164.0905

# 206264.806" per radian, to turn the arcsecond errors into radians.
_ARCSEC_PER_RAD = 206264.80624709636

# A correction inside 60" is a good daytime polar alignment for the SHG: the
# scan needs the Dec drift over a few minutes to stay below the slit width.
CONFIRMATION_TOLERANCE_ARCSEC = 60.0

# The condition number of the (1, cos H, sin H) basis above which the hour
# angles cannot separate the two errors. A 30-minute session near the meridian
# changes H by only ~7 deg, and the three columns are nearly collinear; the fit
# is still the best estimate but the UI must warn (reason_code
# "geometry_limit").
GEOMETRY_CONDITION_WARN = 30.0


# @args: altitude_error_arcsec - polar axis altitude error, positive too high
#        azimuth_error_arcsec - polar axis azimuth error, positive east
#        hour_angle_deg - local hour angle of the Sun
#        latitude_deg - observatory latitude
# @return: the Dec drift rate, arcseconds per second
# The vector derivation above, with the errors converted from arcseconds to
# radians. At H=0 the azimuth term is the only one; at H=+90 deg the altitude
# term is negative (south drift) for a too-high axis, which is AstroPixels'
# western-horizon rule.
def drift_rate_arcsec_s(altitude_error_arcsec: float,
                        azimuth_error_arcsec: float,
                        hour_angle_deg: float,
                        latitude_deg: float) -> float:
    ha = math.radians(hour_angle_deg)
    lat = math.radians(latitude_deg)
    alpha = altitude_error_arcsec / _ARCSEC_PER_RAD
    beta = azimuth_error_arcsec / _ARCSEC_PER_RAD
    return -EARTH_ROTATION_ARCSEC_S * (
        alpha * math.sin(ha) + beta * math.cos(lat) * math.cos(ha)
    )


# @args: samples - measured samples with their hour angles and ephemeris Dec
#        latitude_deg - observatory latitude; its cosine scales the azimuth
# @return: the fitted PolarResult
# The design matrix is [1, cos H, sin H]. The least-squares coefficients give
# alpha = c_cos and beta = -c_sin / cos(lat). The fit is done on the
# ephemeris-corrected Dec, so the Sun's own motion does not leak into alpha or
# beta.
def fit_polar_alignment(samples: Sequence[PolarSample],
                        latitude_deg: float) -> PolarResult:
    count = len(samples)
    if count < 3:
        return PolarResult(False, 0.0, 0.0, 0.0, 0.0, count,
                           reason_code="not_enough_samples")
    hours = np.radians(np.asarray([s.hour_angle_deg for s in samples],
                                  dtype=float))
    times = np.asarray([s.time_s for s in samples], dtype=float)
    dec = np.asarray([s.dec_deg for s in samples], dtype=float)
    dec_ephemeris = np.asarray([s.dec_ephemeris_deg for s in samples],
                               dtype=float)
    # Dec is in degrees, the errors are wanted in arcseconds.
    y = (dec - dec_ephemeris) * 3600.0
    design = np.column_stack([np.ones(count), np.cos(hours), np.sin(hours)])
    # A tiny ridge keeps a degenerate session from producing infinities; it
    # does not bias a well-conditioned fit, where the term is 1e-9 of the norm.
    normal = design.T @ design + 1e-9 * np.eye(3)
    try:
        coefficients = np.linalg.solve(normal, design.T @ y)
    except np.linalg.LinAlgError:
        return PolarResult(False, 0.0, 0.0, 0.0, 0.0, count,
                           reason_code="geometry_limit")

    cos_lat = math.cos(math.radians(latitude_deg))
    if abs(cos_lat) < 1e-6:
        return PolarResult(False, 0.0, 0.0, 0.0, 0.0, count,
                           reason_code="geometry_limit")
    altitude_error = float(coefficients[1])
    azimuth_error = float(-coefficients[2] / cos_lat)
    predicted = design @ coefficients
    residual = float(np.sqrt(np.mean((y - predicted) ** 2)))

    # The linear drift rate in the log is the slope of the corrected Dec over
    # time, in arcsec/min. It is a diagnostic of what the assistant saw, not
    # the number used to guide the knobs.
    if count >= 2 and float(np.max(times) - np.min(times)) > 0:
        slope = float(np.polyfit(times, y, 1)[0]) * 60.0
    else:
        slope = 0.0

    # The condition number of the normalised basis says whether the session
    # can separate the two errors. Scaling each column to unit norm makes the
    # figure independent of the units.
    norms = np.linalg.norm(design, axis=0)
    scaled = design / np.where(norms > 0, norms, 1.0)
    condition = float(np.linalg.cond(scaled))
    reason = "geometry_limit" if condition > GEOMETRY_CONDITION_WARN else ""
    if not (math.isfinite(altitude_error) and math.isfinite(azimuth_error)):
        return PolarResult(False, 0.0, 0.0, 0.0, 0.0, count,
                           reason_code="geometry_limit")
    return PolarResult(
        ok=True,
        azimuth_error_arcsec=azimuth_error,
        altitude_error_arcsec=altitude_error,
        drift_rate_arcsec_min=slope,
        residual_arcsec=residual,
        samples=count,
        reason_code=reason,
    )


class PolarAlignmentSession:
    # The PolarAlignmentAssistant contract (shg/abc.py). The caller builds it
    # with the observatory latitude and the number of samples it intends to
    # take, feeds add_sample() and reads result(); confirm() takes the second
    # measurement after the correction.

    # @args: latitude_deg - observatory latitude, north positive
    #        required_samples - samples the caller intends to take
    #        tolerance_arcsec - confirmation threshold
    def __init__(self, latitude_deg: float, required_samples: int = 10,
                 tolerance_arcsec: float = CONFIRMATION_TOLERANCE_ARCSEC) -> None:
        if required_samples <= 0:
            raise ValueError("required_samples must be positive")
        self.latitude_deg = float(latitude_deg)
        self.required_samples = int(required_samples)
        self.tolerance_arcsec = float(tolerance_arcsec)
        self.samples: list[PolarSample] = []
        self._confirmation: PolarResult | None = None

    # @args: sample - one measured Dec with its hour angle and ephemeris
    #        cb - optional progress callback
    # @return: the progress after this sample
    def add_sample(self, sample: PolarSample,
                   cb: Callable[[PolarProgress], None] | None = None) -> PolarProgress:
        if not all(math.isfinite(value) for value in
                   (sample.time_s, sample.hour_angle_deg, sample.dec_deg,
                    sample.dec_ephemeris_deg)):
            raise ValueError("the sample has a non-finite value")
        self.samples.append(sample)
        progress = self._progress(len(self.samples), sample)
        if cb is not None:
            cb(progress)
        return progress

    # @args: count - samples gathered; sample - the last one
    # @return: the progress value
    def _progress(self, count: int, sample: PolarSample) -> PolarProgress:
        elapsed = sample.time_s - self.samples[0].time_s if self.samples else 0.0
        return PolarProgress(
            samples=count,
            required=self.required_samples,
            progress=min(1.0, count / float(self.required_samples)),
            hour_angle_deg=sample.hour_angle_deg,
            elapsed_s=elapsed,
        )

    # @return: the fit with the samples gathered so far
    def result(self) -> PolarResult:
        return fit_polar_alignment(self.samples, self.latitude_deg)

    # @args: samples - the second measurement, taken after the correction;
    #                  None means use the samples already gathered
    #        cb - optional progress callback
    # @return: the confirmation fit; confirmation=True when both errors are
    #          inside the tolerance and the fit is usable
    def confirm(self, samples: Sequence[PolarSample] | None = None,
                cb: Callable[[PolarProgress], None] | None = None) -> PolarResult:
        if samples is None:
            samples = list(self.samples)
        samples = list(samples)
        if cb is not None and samples:
            for index, sample in enumerate(samples, start=1):
                cb(PolarProgress(
                    samples=index,
                    required=len(samples),
                    progress=index / float(max(1, len(samples))),
                    hour_angle_deg=sample.hour_angle_deg,
                    elapsed_s=sample.time_s - samples[0].time_s,
                ))
        fitted = fit_polar_alignment(samples, self.latitude_deg)
        inside = (abs(fitted.azimuth_error_arcsec) <= self.tolerance_arcsec
                  and abs(fitted.altitude_error_arcsec) <= self.tolerance_arcsec)
        result = PolarResult(
            ok=fitted.ok,
            azimuth_error_arcsec=fitted.azimuth_error_arcsec,
            altitude_error_arcsec=fitted.altitude_error_arcsec,
            drift_rate_arcsec_min=fitted.drift_rate_arcsec_min,
            residual_arcsec=fitted.residual_arcsec,
            samples=fitted.samples,
            confirmation=bool(fitted.ok and inside),
            reason_code=fitted.reason_code,
        )
        self._confirmation = result
        return result

    # @return: the last confirmation result, or None before confirm()
    def last_confirmation(self) -> PolarResult | None:
        return self._confirmation
