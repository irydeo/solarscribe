############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices native frame module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Owned frame and statistics shared by the native SDK drivers.
#
# The SDK reuses its own buffer as soon as the callback returns, so every frame
# that escapes a driver must own its pixels (ADR-001, ARCHITECTURE 4). The
# wrapper copies once, and this class is that copy plus the `devices.Frame`
# contract: the same cut-on-sub-region rule as the simulator, so consumers can
# treat every backend alike.

from __future__ import annotations

import numpy as np

from solarscribe.devices.abc import ROI

__all__ = ["SdkFrame", "SdkStats"]


class SdkStats:
    # The two FrameStats numbers, computed once per frame.

    # @args: mean, std - the two measurements
    # @return: none
    def __init__(self, mean: float, std: float) -> None:
        self.mean = mean
        self.std = std


class SdkFrame:
    # Owned frame on the devices.Frame contract.

    # @args: array - C-contiguous image the SDK wrapper already copied
    #        roi - SENSOR ROI this frame came from
    #        sequence - driver counter; a hole means a dropped frame
    #        timestamp - seconds, taken on receipt
    def __init__(self, array: np.ndarray, roi: ROI, sequence: int,
                 timestamp: float) -> None:
        self._array = np.ascontiguousarray(array)
        self.data = memoryview(self._array)
        self.height, self.width = self._array.shape
        self.dtype = self._array.dtype
        self.roi = roi
        self.sequence = sequence
        self.timestamp = timestamp
        self._stats_cache = None

    # @return: mean and standard deviation of the whole frame
    def stats(self):
        if self._stats_cache is None:
            self._stats_cache = SdkStats(
                float(self._array.mean()), float(self._array.std()),
            )
        return self._stats_cache

    # @args: roi - sub-region in FRAME pixels
    # @return: the sub-region as an owned frame; a full-width strip stays a
    #          zero-copy view, anything narrower is copied so the memoryview
    #          has no row strides (np.frombuffer needs that)
    def cut_roi(self, roi: ROI):
        x, y, width, height = roi
        if x == 0 and width == self.width:
            sub = self._array[y:y + height, :]
        else:
            sub = np.ascontiguousarray(self._array[y:y + height, x:x + width])
        return SdkFrame(sub, self.roi, self.sequence, self.timestamp)
