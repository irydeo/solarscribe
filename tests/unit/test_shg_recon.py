############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg recon test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The synthetic scan is a disk cut into chords: at scan position x the lit
# slit length is 2*sqrt(R^2 - x^2) (ADR-006). Stacking those chords must give a
# disk back, which is the mathematical anchor of the quick recon. The tests
# also pin the honest limits: small output, normalised 0..1, and the reason
# codes for no frames, an empty band and a flat frame.

import math

import numpy as np
import pytest

from solarscribe.shg import recon

from .test_shg_support import FakeFrame


def _chord_row(frames: int = 64, width: int = 128, band_h: int = 8,
               radius: float = 48.0) -> list[FakeFrame]:
    result = []
    for index in range(frames):
        x = -radius + 2.0 * radius * index / (frames - 1)
        half = math.sqrt(max(0.0, radius * radius - x * x))
        centre = width / 2.0
        start = max(0, int(round(centre - half)))
        stop = min(width, int(round(centre + half)))
        data = np.zeros((band_h, width), dtype=np.uint16)
        data[:, start:stop] = 1000
        result.append(FakeFrame(data))
    return result


def test_quick_recon_of_chords_reconstructs_a_disk():
    frames = _chord_row()
    result = recon.quick_recon([frames], band=(0, 0, 128, 8),
                               width=128, max_height=64)
    assert result.ok, result.reason_code
    assert result.frames_used == 64
    assert result.rows == 1
    assert result.image.shape == (64, 128)
    assert result.image.dtype == np.float32
    assert result.image.min() == pytest.approx(0.0)
    assert result.image.max() == pytest.approx(1.0)
    # Centre bright, corners dark, and the middle row spans about the diameter.
    assert result.image[32, 64] > 0.9
    assert result.image[0, 0] == pytest.approx(0.0)
    lit = np.count_nonzero(result.image[32] > 0.5)
    assert 85 <= lit <= 110


def test_quick_recon_caps_the_output_size():
    frames = _chord_row(frames=128, width=256, band_h=8, radius=96.0)
    result = recon.quick_recon([frames], band=(0, 0, 256, 8),
                               width=64, max_height=32)
    assert result.ok
    assert result.image.shape == (32, 64)


def test_quick_recon_stacks_mosaic_rows_with_a_step():
    row = _chord_row(frames=32, width=128, band_h=8, radius=48.0)
    result = recon.quick_recon([row, row], band=(0, 0, 128, 8),
                               width=128, max_height=128)
    assert result.ok
    assert result.rows == 2
    assert result.image.shape[0] == 64

    overlapped = recon.quick_recon([row, row], band=(0, 0, 128, 8),
                                   width=128, max_height=128,
                                   row_step_px=16)
    assert overlapped.ok
    assert overlapped.rows == 2
    assert overlapped.image.shape[0] == 48


def test_quick_recon_reports_no_frames():
    result = recon.quick_recon([])
    assert not result.ok
    assert result.reason_code == "no_frames"
    assert result.image.size == 0


def test_quick_recon_reports_an_empty_band():
    frame = FakeFrame(np.zeros((8, 128), dtype=np.uint16))
    result = recon.quick_recon([[frame]], band=(200, 0, 10, 10),
                               width=128, max_height=64)
    assert not result.ok
    assert result.reason_code == "band_empty"
    assert result.frames_used == 1


def test_quick_recon_marks_a_flat_frame_low_contrast():
    frame = FakeFrame(np.full((8, 128), 500, dtype=np.uint16))
    result = recon.quick_recon([[frame]], band=(0, 0, 128, 8),
                               width=128, max_height=64)
    assert result.ok
    assert result.reason_code == "low_contrast"
    assert result.image.max() == pytest.approx(0.0)


def test_frame_profile_is_the_mean_over_the_band_rows():
    data = np.zeros((8, 16), dtype=np.uint16)
    data[0:4, :] = 1000          # bright half of the band
    data[4:8, :] = 0             # dark half
    frame = FakeFrame(data)
    profile = recon.frame_profile(frame, (0, 0, 16, 8))
    assert profile is not None
    assert profile.shape == (16,)
    assert np.allclose(profile, 500.0)


def test_quick_recon_accepts_a_plain_numpy_frame():
    data = np.zeros((8, 16), dtype=np.uint16)
    data[:, 4:12] = 1000
    frames = [data for _ in range(8)]
    result = recon.quick_recon([frames], band=(0, 0, 16, 8),
                               width=16, max_height=8)
    assert result.ok
    assert result.image.shape == (8, 16)
    assert result.image[4, 8] > 0.9
