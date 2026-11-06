############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg spectrum module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Spectral line identification on the live spectrum, native and offline.
#
# The approach follows JSol'Ex (GPL-3, the same licence as SolarScribe) but is
# written here from its problem statement, not copied: a captured spectrum has
# a known dispersion (angstroms per pixel) and the grating is tuned to a known
# target line, so one pixel can be anchored to one wavelength. Every other
# detected dip is then named by its distance from the anchor, using a curated
# catalog. No network, no JSol'Ex, no dependency beyond numpy.
#
# Why it is a preview and not a measurement: the anchor (the target line) and
# the dispersion are inputs. If the grating is not tuned where the config says,
# or the dispersion is wrong, the names slide. The confidence says how many of
# the strong catalog lines in the window were found and how many of the detected
# dips were named; it is a pattern match, not a wavelength calibration. The
# Doppler shift of the solar lines is not removed, so a line can sit a few
# hundredths of an angstrom away from its rest wavelength.
#
# Reference for the catalog wavelengths: the Fraunhofer line table (the same
# values as the JSol'Ex interesting-lines list) and the Moore solar line list.
# The MVP keeps the strong, well-separated lines; a blend that cannot be
# resolved at the working dispersion is merged (the Ca I / Fe I G pair).
#
# The detection and identification are cheap enough for the capture thread's
# budget: a moving maximum for the continuum, one convolution for the
# smoothing, and a match loop over a few dozen catalog lines and a few dozen
# dips. The identification is meant to run at a lower rate than the frames.

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from solarscribe.devices.abc import ROI, Frame

from .analysis import frame_array

__all__ = [
    "CATALOG",
    "CatalogLine",
    "IdentificationResult",
    "IdentifiedLine",
    "LineCandidate",
    "catalog_lines_between",
    "detect_absorption_lines",
    "dispersion_profile",
    "identify_lines",
]

# Matching tolerance. The JSol'Ex catalog uses 0.5 A, and that is also the
# scale at which a low-resolution SHG can tell neighbouring lines apart.
DEFAULT_TOLERANCE_ANGSTROM = 0.5

# A match below this F1 score is a pattern that does not support the naming.
DEFAULT_MIN_CONFIDENCE = 0.35

# The anchor search is small on purpose: it absorbs a wavelength calibration
# error of a couple of pixels, not a wrong dispersion.
DEFAULT_ANCHOR_SEARCH_PX = 2.0
DEFAULT_ANCHOR_SEARCH_STEPS = 9


@dataclass(frozen=True)
class CatalogLine:
    # One curated line. `kind` distinguishes the solar photosphere from the
    # Earth's atmosphere: a telluric line does not move with the Sun, so the UI
    # can label it as a marker instead of a solar feature.
    name: str
    wavelength_angstrom: float
    kind: str = "solar"          # "solar" or "telluric"
    note: str = ""               # Fraunhofer letter or a short description


# The data table. It covers the visible range an SHG uses, from the high
# Balmer lines to the far-red O2 bands. Grouped by what the observer looks for.
# Wavelengths are air wavelengths, the convention of the Fraunhofer table and
# of the JSol'Ex interesting-lines list.
_CATALOG_ENTRIES: tuple[CatalogLine, ...] = (
    # Hydrogen Balmer series (the high members, then the classical Fraunhofer
    # letters down to H-alpha).
    CatalogLine("H-eta", 3835.397, "solar", "Balmer eta, Ba-eta"),
    CatalogLine("H-zeta", 3889.064, "solar", "Balmer zeta, Ba-zeta"),
    CatalogLine("H-epsilon", 3970.075, "solar", "Balmer epsilon, Ba-epsilon"),
    CatalogLine("H-delta", 4101.75, "solar", "Fraunhofer h"),
    CatalogLine("H-gamma", 4340.47, "solar", "Fraunhofer G'"),
    CatalogLine("H-beta", 4861.34, "solar", "Fraunhofer F"),
    CatalogLine("H-alpha", 6562.81, "solar", "Fraunhofer C; the usual SHG target"),

    # Calcium H and K, the violet doublet that defines the SHG passband.
    CatalogLine("Ca II K", 3933.66, "solar", "Fraunhofer K"),
    CatalogLine("Ca II H", 3968.47, "solar", "Fraunhofer H"),

    # Iron lines used to focus the spectrograph and to check the dispersion.
    CatalogLine("Fe I e", 4383.55, "solar", "Fraunhofer e"),
    CatalogLine("Fe I d", 4668.14, "solar", "Fraunhofer d"),
    CatalogLine("Fe I c", 4957.61, "solar", "Fraunhofer c"),
    CatalogLine("Fe I E2", 5270.39, "solar", "Fraunhofer E2"),
    CatalogLine("Fe I 6569.224", 6569.224, "solar", "near H-alpha; Fe I"),
    CatalogLine("Fe I 6575.037", 6575.037, "solar", "near H-alpha; Fe I"),

    # The Ca I / Fe I G pair is 0.16 A wide, below the resolution of a low
    # dispersion SHG, so it is kept as one blended entry instead of two lines
    # that can never be matched separately.
    CatalogLine("Ca I / Fe I G", 4307.82, "solar", "Fraunhofer G blend"),

    # Magnesium b triplet; the Fe I b3 line sits inside the triplet.
    CatalogLine("Mg I b4", 5167.33, "solar", "Mg b triplet"),
    CatalogLine("Fe I b3", 5168.91, "solar", "inside the Mg b triplet"),
    CatalogLine("Mg I b2", 5172.70, "solar", "Mg b triplet"),
    CatalogLine("Mg I b1", 5183.62, "solar", "Mg b triplet"),

    # Helium D3 and the sodium doublet: the yellow region.
    CatalogLine("He I D3", 5875.618, "solar", "Fraunhofer D3"),
    CatalogLine("Na I D2", 5889.95, "solar", "Fraunhofer D2"),
    CatalogLine("Na I D1", 5895.92, "solar", "Fraunhofer D1"),

    # Telluric oxygen bands: fixed to the Earth, useful as wavelength markers.
    CatalogLine("O2 a", 6276.61, "telluric", "telluric O2, Fraunhofer a"),
    CatalogLine("O2 B", 6867.19, "telluric", "telluric O2 B band"),
    CatalogLine("O2 A", 7593.70, "telluric", "telluric O2 A band, Fraunhofer A"),
    CatalogLine("O2 Z", 8226.96, "telluric", "telluric O2, Fraunhofer Z"),
    CatalogLine("O2 y", 8987.65, "telluric", "telluric O2, Fraunhofer y"),

    # Water vapour: broad telluric bands, not sharp solar lines. The entry is a
    # marker; the matcher prefers a sharp solar line when both are in range.
    CatalogLine("H2O (telluric)", 7185.6, "telluric",
                "broad water-vapour band head, a marker not a sharp line"),

    # The red calcium triplet line, reachable with a red grating.
    CatalogLine("Ca II 8542.16", 8542.16, "solar", "Ca II infrared triplet"),
)

# The public table is sorted by wavelength even though the source above is
# grouped by what the observer looks for: the ordering makes the window search
# and the UI list predictable without giving up the grouped comments.
CATALOG: tuple[CatalogLine, ...] = tuple(sorted(
    _CATALOG_ENTRIES, key=lambda line: line.wavelength_angstrom))


@dataclass(frozen=True)
class LineCandidate:
    # One detected absorption dip. `pixel` is sub-pixel, `depth` is the
    # relative depth below the local continuum (0..1) and `intensity` is the
    # smoothed value at the dip, for the UI.
    pixel: float
    depth: float
    intensity: float


@dataclass(frozen=True)
class IdentifiedLine:
    # A detected dip matched to a catalog line. `distance_angstrom` is the
    # residual between the measured wavelength and the catalog rest wavelength;
    # it says how well this individual line supports the naming.
    name: str
    wavelength_angstrom: float
    pixel: float
    depth: float
    distance_angstrom: float
    kind: str = "solar"


@dataclass(frozen=True)
class IdentificationResult:
    # The outcome of one identification. `confidence` is the F1 score of the
    # pattern match: the balance between the catalog lines found and the
    # detected dips named. It is not a wavelength uncertainty.
    ok: bool
    lines: tuple[IdentifiedLine, ...]
    anchor_wavelength: float
    dispersion_a_px: float
    confidence: float
    reason_code: str = ""
    anchor_pixel: float = 0.0
    detected: int = 0
    matched: int = 0
    flip: bool = False


# @args: frame - a delivered Frame
#        band - the spectral band in FRAME pixels, or None for the whole frame
# @return: the mean over the slit axis for each dispersion row
# The slit axis is X (frame width) and the dispersion axis is Y (frame height),
# the convention of the SHG frames and of the focus module. Collapsing over X
# keeps the absorption lines, which run along X, and removes the surface detail.
def dispersion_profile(frame: Frame, band: ROI | None = None) -> np.ndarray:
    array = frame_array(frame)
    if band is None:
        x0, y0, x1, y1 = 0, 0, frame.width, frame.height
    else:
        x0 = max(0, int(band[0]))
        y0 = max(0, int(band[1]))
        x1 = min(frame.width, x0 + int(band[2]))
        y1 = min(frame.height, y0 + int(band[3]))
    if x1 <= x0 or y1 <= y0:
        return np.zeros(0, dtype=float)
    return np.mean(array[y0:y1, x0:x1].astype(float), axis=1)


# @args: values - 1D profile
#        window - smoothing window in pixels
# @return: the box-smoothed profile
# A box is enough for a preview and has no dependency. An even window is
# rounded up to odd so the output stays centred on the sample.
def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    size = max(1, int(window))
    if size <= 1:
        return values.copy()
    if size % 2 == 0:
        size += 1
    kernel = np.ones(size, dtype=float) / size
    return np.convolve(values, kernel, mode="same")


# @args: values - 1D profile
#        window - continuum window in pixels
# @return: the moving upper quartile over the window
# The local continuum is the upper quartile, the same normalisation JSol'Ex
# uses in its line locator: a narrow absorption dip (or a narrow emission
# bump) does not own the quartile of a window several times wider than the
# line, so the blaze and the illumination gradient cancel without the line
# itself becoming the continuum. A moving maximum would let the foot of a
# narrow emission bump look like an absorption dip.
def _local_continuum(values: np.ndarray, window: int) -> np.ndarray:
    size = max(1, int(window))
    if size <= 1 or values.size == 0:
        return values.copy()
    if size % 2 == 0:
        size += 1
    half = size // 2
    padded = np.pad(values, (half, half), mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(padded, size)
    index = min(size - 1, max(0, int(0.75 * size)))
    return np.partition(view, index, axis=1)[:, index]


# @args: profile - 1D dispersion profile (higher = brighter)
#        smooth_px - smoothing window, pixels
#        continuum_window_px - local continuum window, pixels
#        depth_fraction - minimum relative depth, 0..1
#        min_separation_px - two dips closer than this are one
# @return: the detected absorption dips, sorted by pixel
# Detection is a local minimum whose relative depth below the moving maximum
# exceeds `depth_fraction`. The smoothing suppresses the sensor noise; the
# greedy separation keeps the deepest dip of a blended pair. The sub-pixel
# position is the vertex of a parabola through the three samples around the
# minimum, the standard estimator for a smooth line.
def detect_absorption_lines(profile, *, smooth_px: int = 3,
                            continuum_window_px: int = 31,
                            depth_fraction: float = 0.02,
                            min_separation_px: int = 2) -> list[LineCandidate]:
    values = np.asarray(profile, dtype=float).ravel()
    if values.size < 3:
        return []
    smooth = _smooth(values, smooth_px)
    continuum = _local_continuum(smooth, continuum_window_px)
    relative = (continuum - smooth) / np.maximum(continuum, 1e-12)
    left = smooth[1:-1] <= smooth[:-2]
    right = smooth[1:-1] < smooth[2:]
    deep = relative[1:-1] >= depth_fraction
    indices = np.flatnonzero(left & right & deep) + 1
    if indices.size == 0:
        return []

    # Keep the deepest dip of a cluster: a line wider than min_separation_px
    # would otherwise be reported twice by the two shoulders of its minimum.
    candidates = sorted(((int(index), float(relative[index]))
                         for index in indices), key=lambda item: -item[1])
    kept: list[tuple[int, float]] = []
    for index, depth in candidates:
        if all(abs(index - other) >= min_separation_px for other, _ in kept):
            kept.append((index, depth))
    kept.sort(key=lambda item: item[0])

    result: list[LineCandidate] = []
    for index, depth in kept:
        first = smooth[index - 1]
        middle = smooth[index]
        last = smooth[index + 1]
        denominator = first - 2.0 * middle + last
        offset = 0.0
        if abs(denominator) > 1e-12:
            offset = 0.5 * (first - last) / denominator
            offset = max(-0.5, min(0.5, offset))
        result.append(LineCandidate(
            pixel=index + offset,
            depth=depth,
            intensity=float(middle),
        ))
    return result


# @args: min_angstrom, max_angstrom - inclusive wavelength bounds
# @return: the catalog lines in the range, sorted by wavelength
def catalog_lines_between(min_angstrom: float,
                          max_angstrom: float) -> tuple[CatalogLine, ...]:
    if max_angstrom < min_angstrom:
        min_angstrom, max_angstrom = max_angstrom, min_angstrom
    return tuple(line for line in CATALOG
                 if min_angstrom <= line.wavelength_angstrom <= max_angstrom)


# @args: detected - detected dips
#        length - profile length in pixels
#        anchor_pixel - pixel of the anchor line
#        anchor_wavelength - wavelength of the anchor line, angstroms
#        dispersion_a_px - angstroms per pixel, positive
#        flip - True when the wavelength decreases with the pixel index
#        tolerance_angstrom - how far a detected line may be from a catalog line
# @return: (matched lines, confidence, catalog lines in range, detected count)
# The score is an F1: the harmonic mean of the fraction of catalog lines found
# (recall) and the fraction of detected dips named (precision). A window with
# one catalog line and one detection that match scores 1; a window with many
# unmatched noise dips scores low even if the one real line is named.
def _match(detected: list[LineCandidate], length: int, anchor_pixel: float,
           anchor_wavelength: float, dispersion_a_px: float, flip: bool,
           tolerance_angstrom: float) -> tuple[list[IdentifiedLine], float, int, int]:
    sign = -1.0 if flip else 1.0
    start = anchor_wavelength + (0.0 - anchor_pixel) * dispersion_a_px * sign
    end = anchor_wavelength + (length - 1 - anchor_pixel) * dispersion_a_px * sign
    min_angstrom = min(start, end) - tolerance_angstrom
    max_angstrom = max(start, end) + tolerance_angstrom
    in_range = [line for line in CATALOG
                if min_angstrom <= line.wavelength_angstrom <= max_angstrom]
    if not detected:
        return [], 0.0, len(in_range), 0

    detected_wavelengths = [
        anchor_wavelength + (line.pixel - anchor_pixel) * dispersion_a_px * sign
        for line in detected
    ]
    used: set[int] = set()
    matched: list[IdentifiedLine] = []
    # Strongest dips first: if two dips fall inside the same catalog tolerance,
    # the deeper one keeps the name and the weaker one stays unnamed.
    order = sorted(range(len(detected)),
                   key=lambda index: -detected[index].depth)
    for index in order:
        wavelength = detected_wavelengths[index]
        best: int | None = None
        best_distance = tolerance_angstrom
        for catalog_index, line in enumerate(in_range):
            if catalog_index in used:
                continue
            distance = abs(line.wavelength_angstrom - wavelength)
            if distance <= best_distance:
                best_distance = distance
                best = catalog_index
        if best is None:
            continue
        used.add(best)
        line = in_range[best]
        matched.append(IdentifiedLine(
            name=line.name,
            wavelength_angstrom=line.wavelength_angstrom,
            pixel=detected[index].pixel,
            depth=detected[index].depth,
            distance_angstrom=best_distance,
            kind=line.kind,
        ))
    matched.sort(key=lambda line: line.pixel)

    precision = len(matched) / len(detected) if detected else 0.0
    recall = len(used) / len(in_range) if in_range else 0.0
    if precision + recall <= 0:
        confidence = 0.0
    else:
        confidence = 2.0 * precision * recall / (precision + recall)
    return matched, confidence, len(in_range), len(detected)


# @args: profile - 1D dispersion profile
#        dispersion_a_px - angstroms per pixel, positive
#        anchor_pixel - pixel of the known line, or None to use the strongest
#        anchor_wavelength - wavelength of the anchor, or None to use the target
#        target_wavelength - the tuned line, used when the anchor has no value
#        flip - True when the wavelength decreases with the pixel index
#        tolerance_angstrom - matching tolerance
#        refine - search the anchor offset for a better catalog match
#        anchor_search_px - half-width of the anchor search
#        anchor_search_steps - offsets tried in the search
#        min_confidence - below this the result carries "low_confidence"
#        smooth_px, continuum_window_px, depth_fraction, min_separation_px -
#            detection parameters
# @return: the IdentificationResult
# The wavelength mapping is the contract:
#   wavelength(px) = anchor_wavelength + (px - anchor_pixel) * dispersion * sign
# with sign = -1 when flip is True. The anchor is the configured target line
# (the grating is tuned to it); without an anchor pixel the strongest dip is
# taken as that line, which is the MVP's assumption and its honest limit.
def identify_lines(profile, dispersion_a_px: float, *,
                   anchor_pixel: float | None = None,
                   anchor_wavelength: float | None = None,
                   target_wavelength: float | None = None,
                   flip: bool = False,
                   tolerance_angstrom: float = DEFAULT_TOLERANCE_ANGSTROM,
                   refine: bool = True,
                   anchor_search_px: float = DEFAULT_ANCHOR_SEARCH_PX,
                   anchor_search_steps: int = DEFAULT_ANCHOR_SEARCH_STEPS,
                   min_confidence: float = DEFAULT_MIN_CONFIDENCE,
                   smooth_px: int = 3,
                   continuum_window_px: int = 31,
                   depth_fraction: float = 0.02,
                   min_separation_px: int = 2) -> IdentificationResult:
    values = np.asarray(profile, dtype=float).ravel()
    if values.size < 3:
        return IdentificationResult(False, (), 0.0, dispersion_a_px, 0.0,
                                    "empty_profile", flip=flip)
    if dispersion_a_px <= 0:
        return IdentificationResult(False, (), 0.0, dispersion_a_px, 0.0,
                                    "bad_dispersion", flip=flip)

    used_wavelength = (anchor_wavelength if anchor_wavelength is not None
                       else target_wavelength)
    if used_wavelength is None:
        return IdentificationResult(False, (), 0.0, dispersion_a_px, 0.0,
                                    "no_anchor", flip=flip)

    detected = detect_absorption_lines(
        values, smooth_px=smooth_px,
        continuum_window_px=continuum_window_px,
        depth_fraction=depth_fraction,
        min_separation_px=min_separation_px)
    if not detected:
        return IdentificationResult(False, (), used_wavelength,
                                    dispersion_a_px, 0.0, "no_lines",
                                    flip=flip)
    if anchor_pixel is None:
        # MVP: the grating is tuned to the target, so the strongest dip is the
        # target line. This is an assumption, not a measurement.
        base_anchor = max(detected, key=lambda line: line.depth).pixel
    else:
        base_anchor = float(anchor_pixel)

    if refine:
        offsets = np.linspace(-abs(anchor_search_px), abs(anchor_search_px),
                              max(3, int(anchor_search_steps)))
    else:
        offsets = np.zeros(1, dtype=float)

    best_lines: list[IdentifiedLine] = []
    best_confidence = -1.0
    best_anchor = base_anchor
    best_counts = (0, 0)
    for offset in offsets:
        candidate_anchor = base_anchor + float(offset)
        lines, confidence, in_range, count = _match(
            detected, values.size, candidate_anchor, used_wavelength,
            dispersion_a_px, flip, tolerance_angstrom)
        # A tie keeps the smallest anchor correction, so the reported anchor
        # does not wander when the match is symmetric around the true pixel.
        if (confidence > best_confidence + 1e-12
                or (abs(confidence - best_confidence) <= 1e-12
                    and abs(offset) < abs(best_anchor - base_anchor))):
            best_lines = lines
            best_confidence = max(best_confidence, confidence)
            best_anchor = candidate_anchor
            best_counts = (in_range, count)

    if not best_lines:
        return IdentificationResult(False, (), used_wavelength,
                                    dispersion_a_px, 0.0, "no_match",
                                    anchor_pixel=best_anchor,
                                    detected=best_counts[1], matched=0,
                                    flip=flip)
    reason = "low_confidence" if best_confidence < min_confidence else ""
    return IdentificationResult(
        ok=True,
        lines=tuple(best_lines),
        anchor_wavelength=used_wavelength,
        dispersion_a_px=dispersion_a_px,
        confidence=best_confidence,
        reason_code=reason,
        anchor_pixel=best_anchor,
        detected=best_counts[1],
        matched=len(best_lines),
        flip=flip,
    )
