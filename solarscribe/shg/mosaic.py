############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg mosaic module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Mosaic geometry: the effective slit length, the row step, the number of rows
# and the Dec backlash approach.
#
# The slit is the hard limit on the spatial (Dec) axis. Its angular length is
# set by the focal length and the re-imaging magnification, and the camera may
# sample only part of it. A single row covers the strip the slit projects; a
# mosaic stacks enough rows to cover the disk plus a margin.
#
# External anchors:
#   - 7 mm at 714 mm focal subtends 7/714 rad = 33.7', just over the ~32' solar
#     diameter (ARCHITECTURE 3.2).
#   - Adjacent rows overlap by a fraction of the strip, so step = strip*(1 -
#     overlap); the prototype's compute_mosaic_plan and its test use exactly
#     this.
#   - The rows are centred on the requested Dec as a group: the mean of the
#     positions equals the centre, so the mosaic is symmetric about the disk.
#   - Dec backlash is taken up by always finishing a move from below the target
#     (a +Dec approach), which makes the final position repeatable regardless
#     of the direction requested. That is mechanical, but the requirement is
#     geometric: the same target must land in the same place every time.

from __future__ import annotations

import math
from dataclasses import dataclass

from .geometry import effective_slit_arcsec

__all__ = [
    "MosaicPlan",
    "backlash_approach",
    "compute_mosaic_plan",
    "effective_slit_arcsec",
]

# Prototype defaults (nightscribe-scan section 5).
MOSAIC_OVERLAP = 0.15
MOSAIC_MARGIN_ARCSEC = 100.0
MOSAIC_DEC_BACKLASH = 30.0
MOSAIC_CENTER_RESIDUAL_ARCSEC = 300.0


@dataclass(frozen=True)
class MosaicPlan:
    # What the mosaic will do. `positions_dec_deg` is the signed Dec of every
    # row, centred on the requested centre. `step_arcsec` is the Dec distance
    # between rows and `strip_arcsec` the sky covered by one row.
    strip_arcsec: float
    step_arcsec: float
    rows: int
    positions_dec_deg: tuple[float, ...]
    margin_arcsec: float
    overlap: float
    uncertainty_arcsec: float


# @args: center_dec_deg - Dec of the disk centre, degrees
#        solar_diameter_arcsec - apparent solar diameter
#        slit_arcsec - effective slit length on the sky
#        overlap - fraction of the strip shared by adjacent rows, [0, 1)
#        margin_arcsec - extra sky above and below the disk
#        uncertainty_arcsec - known bound on the centring error; the margin
#                             becomes max(margin, uncertainty)
#        rows - explicit row count, 0 means compute it
#        row_step_arcsec - explicit Dec step, 0 means strip*(1-overlap)
# @return: the row plan
# A strip longer than the disk needs one row: adding rows to satisfy a margin
# would only record empty sky, which is what the prototype avoids.
def compute_mosaic_plan(center_dec_deg: float,
                        solar_diameter_arcsec: float,
                        slit_arcsec: float,
                        overlap: float = MOSAIC_OVERLAP,
                        margin_arcsec: float = MOSAIC_MARGIN_ARCSEC,
                        uncertainty_arcsec: float = 0.0,
                        rows: int = 0,
                        row_step_arcsec: float = 0.0) -> MosaicPlan:
    if solar_diameter_arcsec <= 0:
        raise ValueError("solar diameter must be positive")
    if slit_arcsec <= 0:
        raise ValueError("slit length must be positive")
    if not 0.0 <= overlap < 1.0:
        raise ValueError("overlap must be in [0, 1)")

    strip = float(slit_arcsec)
    step = float(row_step_arcsec) if row_step_arcsec > 0 else strip * (1.0 - overlap)
    if step <= 0:
        raise ValueError("the row step must be positive")
    margin = max(float(margin_arcsec), float(uncertainty_arcsec))

    if rows > 0:
        count = int(rows)
    elif strip >= solar_diameter_arcsec:
        # One strip already covers the disk; centring uncertainty is irrelevant
        # here, so do not add rows just to satisfy the margin.
        count = 1
    else:
        span = solar_diameter_arcsec + 2.0 * margin
        count = int(math.ceil((span - strip) / step)) + 1
        count = max(1, count)

    positions = tuple(
        center_dec_deg + ((i - (count - 1) / 2.0) * step) / 3600.0
        for i in range(count)
    )
    return MosaicPlan(
        strip_arcsec=strip,
        step_arcsec=step,
        rows=count,
        positions_dec_deg=positions,
        margin_arcsec=margin,
        overlap=float(overlap),
        uncertainty_arcsec=float(uncertainty_arcsec),
    )


# @args: current_dec_deg - where the mount is, degrees
#        target_dec_deg - where it must end, degrees
#        backlash_arcsec - arcsec to back off before the final approach
# @return: the Dec positions to visit in order, ending at the target
# The last move is always towards +Dec, so the gear engages the same face
# every time. If the mount is already below target - backlash, going there
# first would be a pointless reversal; the list then starts above the current
# position and still finishes upwards.
def backlash_approach(current_dec_deg: float, target_dec_deg: float,
                      backlash_arcsec: float = MOSAIC_DEC_BACKLASH) -> tuple[float, ...]:
    if backlash_arcsec <= 0:
        return (target_dec_deg,)
    backoff = target_dec_deg - backlash_arcsec / 3600.0
    if current_dec_deg < backoff:
        return (target_dec_deg,)
    if abs(current_dec_deg - target_dec_deg) < 1e-9:
        # Already there: one +Dec nudge of the backlash and back would be
        # noise for the mount; the caller can skip it.
        return (target_dec_deg,)
    return (backoff, target_dec_deg)
