############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - capture auto exposure module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Auto-exposure loop (parity row 10 of NIGHTSCRIBE-SCAN-PARITY).
#
# The prototype aimed a high percentile of the histogram at ~88% of full scale,
# because the continuum peak of the spectrum sits well above the mean and a
# mean-driven loop would push that peak into the clipping rail. The capture
# contract only carries a mean and a standard deviation (FrameStats), so this
# loop targets a fraction of full scale that leaves headroom for the bright
# chromospheric features: CaptureParams.auto_exposure_target defaults to 0.25.
#
# Why the correction is multiplicative and clamped: camera response is roughly
# linear in exposure, so new = old * target / measured. Clamping the ratio to
# [0.5, 2.0] means one noisy or blocked frame cannot send the exposure to an
# extreme; the loop converges over a few frames instead. If the signal is zero
# the ratio would be infinite, so the loop gives up and reverts to the exposure
# it started with, which is the safe value the observer chose.
#
# The loop is pure logic: it returns the exposure to apply, and the engine calls
# camera.set_param(EXPOSURE, ...) on the capture thread. It never sleeps and
# never touches a device, so it is tested without hardware.

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["AutoExposureConfig", "AutoExposureLoop"]


@dataclass(frozen=True)
class AutoExposureConfig:
    # @args: target_fraction - wanted mean as a fraction of full scale
    #        tolerance_fraction - |mean - target| / full scale that counts as done
    #        max_attempts - corrections before giving up and reverting
    #        interval_s - minimum time between two corrections (one frame may be
    #                     too soon for the new exposure to take effect)
    #        min_ratio, max_ratio - clamp for one correction
    #        min_mean_adu - below this there is no signal, not a dark frame
    target_fraction: float = 0.25
    tolerance_fraction: float = 0.05
    max_attempts: int = 10
    interval_s: float = 0.3
    min_ratio: float = 0.5
    max_ratio: float = 2.0
    min_mean_adu: float = 1.0

    # @args: full_scale_adu - 255 for 8 bit, 65535 for 16 bit
    # @return: the mean the loop is trying to reach
    def target_adu(self, full_scale_adu: float) -> float:
        return self.target_fraction * full_scale_adu

    # @args: full_scale_adu - 255 or 65535
    # @return: the half-width of the "converged" window in ADU
    def tolerance_adu(self, full_scale_adu: float) -> float:
        return self.tolerance_fraction * full_scale_adu


class AutoExposureLoop:
    # Stateful correction loop fed with one mean per frame.

    # @args: config - target, tolerance and limits
    #        initial_exposure_us - the exposure to fall back to on failure
    def __init__(
        self,
        config: AutoExposureConfig | None = None,
        *,
        initial_exposure_us: float = 1000.0,
    ) -> None:
        self.config = config or AutoExposureConfig()
        self._start_exposure = float(initial_exposure_us)
        self._exposure = float(initial_exposure_us)
        self._last_change = float("-inf")
        self._attempts = 0
        self._converged = False
        self._failed = False
        self._reverted = False

    # @args: exposure_us - current exposure when the loop is (re)armed
    # @return: none
    def reset(self, exposure_us: float) -> None:
        self._start_exposure = float(exposure_us)
        self._exposure = float(exposure_us)
        self._last_change = float("-inf")
        self._attempts = 0
        self._converged = False
        self._failed = False
        self._reverted = False

    # @args: mean_adu - frame mean from FrameStats
    #        full_scale_adu - 255 or 65535
    #        now_s - monotonic seconds; the engine passes frame.timestamp
    # @return: the exposure to apply now, or None when no correction is due
    def observe(self, mean_adu: float, full_scale_adu: float,
                now_s: float) -> float | None:
        if self._failed or self._converged:
            return None

        target = self.config.target_adu(full_scale_adu)
        tolerance = self.config.tolerance_adu(full_scale_adu)
        if abs(mean_adu - target) <= tolerance:
            self._converged = True
            return None

        if now_s - self._last_change < self.config.interval_s:
            return None

        if mean_adu < self.config.min_mean_adu:
            # No signal: a ratio would be infinite. Count the attempt, and when
            # the budget is spent revert once to the starting exposure.
            self._attempts += 1
            if self._attempts >= self.config.max_attempts and not self._reverted:
                self._failed = True
                self._reverted = True
                self._exposure = self._start_exposure
                return self._start_exposure
            return None

        ratio = target / mean_adu
        ratio = max(self.config.min_ratio, min(self.config.max_ratio, ratio))
        new_exposure = self._exposure * ratio
        # A one-ADU difference is noise, not a correction worth a USB round trip.
        if abs(new_exposure - self._exposure) < 1.0:
            self._converged = True
            return None

        self._exposure = new_exposure
        self._last_change = now_s
        self._attempts += 1
        if self._attempts >= self.config.max_attempts:
            # The budget ran out without convergence: revert rather than leave
            # a possibly bad value in the camera.
            self._failed = True
            self._exposure = self._start_exposure
            return self._start_exposure
        return new_exposure

    # @return: the exposure the loop currently believes is in the camera
    def exposure(self) -> float:
        return self._exposure

    # @return: whether the target window was reached
    def converged(self) -> bool:
        return self._converged

    # @return: whether the loop gave up and reverted
    def failed(self) -> bool:
        return self._failed

    # @return: corrections applied so far
    def attempts(self) -> int:
        return self._attempts
