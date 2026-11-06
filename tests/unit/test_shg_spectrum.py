############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - shg spectrum test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Strict TDD for the native line identification. The synthetic spectra are a
# flat continuum plus Gaussian absorption dips at known pixels; the catalog
# wavelengths are the published Fraunhofer / Moore values, so a line placed at
# the pixel the dispersion formula predicts must be named with the same
# wavelength. The flipped case and the misplaced-anchor refinement are the two
# cases that catch a sign or an offset error.

from dataclasses import FrozenInstanceError, fields

import numpy as np
import pytest

from solarscribe.shg import spectrum

from .test_shg_support import FakeFrame


def _spectrum(pixels, depths, length=1600, continuum=1000.0,
              sigma=1.5) -> np.ndarray:
    # A flat continuum with Gaussian absorption dips. The continuum is high
    # and the dips are negative, so the profile is a real absorption spectrum.
    x = np.arange(length, dtype=float)
    profile = np.full(length, continuum, dtype=float)
    for pixel, depth in zip(pixels, depths):
        profile -= continuum * depth * np.exp(
            -0.5 * ((x - pixel) / sigma) ** 2)
    return profile


def _pixels(anchor_pixel, anchor_wavelength, dispersion, lines, flip=False):
    sign = -1.0 if flip else 1.0
    return [anchor_pixel + (wavelength - anchor_wavelength)
            / (dispersion * sign) for wavelength, depth in lines]


def _window_lines():
    return [(6562.81, 0.30), (6569.224, 0.15), (6575.037, 0.12)]


def test_detect_absorption_lines_finds_known_dips():
    profile = _spectrum([300.0, 700.0, 1200.0], [0.10, 0.30, 0.20])
    lines = spectrum.detect_absorption_lines(profile)
    assert len(lines) == 3
    assert [line.pixel for line in lines] == pytest.approx(
        [300.0, 700.0, 1200.0], abs=0.5)
    # The 3 px box smoothing reduces the depth by a few percent; the ordering
    # and the magnitude are what the detector reports, not the input depth.
    assert lines[0].depth == pytest.approx(0.09, abs=0.03)
    assert lines[1].depth == pytest.approx(0.26, abs=0.03)
    assert lines[2].depth == pytest.approx(0.17, abs=0.03)
    assert lines[0].intensity < 1000.0


def test_detect_ignores_dips_below_the_threshold():
    profile = _spectrum([500.0], [0.01])
    assert spectrum.detect_absorption_lines(profile) == []


def test_detect_ignores_emission_peaks():
    # A bright Gaussian bump is a local maximum, not an absorption dip.
    x = np.arange(1000, dtype=float)
    profile = 1000.0 + 300.0 * np.exp(-0.5 * ((x - 500.0) / 1.5) ** 2)
    assert spectrum.detect_absorption_lines(profile) == []


def test_detect_handles_short_profiles():
    assert spectrum.detect_absorption_lines([]) == []
    assert spectrum.detect_absorption_lines([1.0, 2.0]) == []


def test_identify_h_alpha_window_matches_the_catalog():
    anchor_pixel, anchor_wavelength, dispersion = 500.0, 6562.81, 0.1
    lines = _window_lines()
    pixels = _pixels(anchor_pixel, anchor_wavelength, dispersion, lines)
    profile = _spectrum(pixels, [depth for _, depth in lines], length=2000)
    result = spectrum.identify_lines(
        profile, dispersion, target_wavelength=anchor_wavelength)
    assert result.ok
    assert result.reason_code == ""
    assert result.anchor_pixel == pytest.approx(anchor_pixel, abs=0.5)
    assert result.anchor_wavelength == pytest.approx(anchor_wavelength)
    assert result.detected == 3
    assert result.matched == 3
    assert result.confidence == pytest.approx(1.0)
    names = [line.name for line in result.lines]
    assert names == ["H-alpha", "Fe I 6569.224", "Fe I 6575.037"]
    assert [line.wavelength_angstrom for line in result.lines] == pytest.approx(
        [6562.81, 6569.224, 6575.037])
    assert [line.pixel for line in result.lines] == pytest.approx(pixels, abs=0.5)
    assert all(line.kind == "solar" for line in result.lines)
    assert all(line.distance_angstrom <= 0.05 for line in result.lines)


def test_identify_refines_a_misplaced_anchor():
    # The true anchor is 500, but the caller says 498. With a tight tolerance
    # only the correct offset matches, so the refinement must move to 500.
    true_anchor, anchor_wavelength, dispersion = 500.0, 6562.81, 0.1
    lines = _window_lines()
    pixels = _pixels(true_anchor, anchor_wavelength, dispersion, lines)
    profile = _spectrum(pixels, [depth for _, depth in lines], length=2000)
    result = spectrum.identify_lines(
        profile, dispersion,
        anchor_pixel=498.0, anchor_wavelength=anchor_wavelength,
        tolerance_angstrom=0.05, refine=True,
        anchor_search_px=2.0, anchor_search_steps=9)
    assert result.ok, result.reason_code
    assert result.anchor_pixel == pytest.approx(true_anchor, abs=0.3)
    assert result.confidence > 0.9
    assert len(result.lines) == 3


def test_identify_flipped_dispersion():
    anchor_pixel, anchor_wavelength, dispersion = 1500.0, 6562.81, 0.1
    lines = _window_lines()
    pixels = _pixels(anchor_pixel, anchor_wavelength, dispersion, lines,
                     flip=True)
    # The pixels decrease as the wavelength grows: the flip is real.
    assert pixels == sorted(pixels, reverse=True)
    profile = _spectrum(pixels, [depth for _, depth in lines], length=2000)
    result = spectrum.identify_lines(
        profile, dispersion, target_wavelength=anchor_wavelength, flip=True)
    assert result.ok, result.reason_code
    assert result.flip is True
    assert result.anchor_pixel == pytest.approx(anchor_pixel, abs=0.5)
    # The lines are sorted by pixel, so the flipped case reads them in
    # decreasing wavelength order; the set and the wavelengths are the test.
    assert {line.name for line in result.lines} == {
        "H-alpha", "Fe I 6569.224", "Fe I 6575.037"}
    assert sorted(line.wavelength_angstrom for line in result.lines) == pytest.approx(
        [6562.81, 6569.224, 6575.037])


def test_identify_reports_no_anchor():
    profile = _spectrum([500.0], [0.2])
    result = spectrum.identify_lines(profile, 0.1)
    assert not result.ok
    assert result.reason_code == "no_anchor"


def test_identify_reports_bad_dispersion():
    profile = _spectrum([500.0], [0.2])
    result = spectrum.identify_lines(profile, 0.0, target_wavelength=6562.81)
    assert not result.ok
    assert result.reason_code == "bad_dispersion"


def test_identify_reports_empty_profile():
    result = spectrum.identify_lines([], 0.1, target_wavelength=6562.81)
    assert not result.ok
    assert result.reason_code == "empty_profile"


def test_identify_reports_no_lines():
    profile = np.full(1000, 1000.0)
    result = spectrum.identify_lines(profile, 0.1, target_wavelength=6562.81)
    assert not result.ok
    assert result.reason_code == "no_lines"


def test_identify_reports_no_match():
    # The only dip is at 6567.81, 1.4 A from the nearest catalog line; with a
    # 0.5 A tolerance it cannot be named.
    profile = _spectrum([550.0], [0.3], length=2000)
    result = spectrum.identify_lines(
        profile, 0.1, anchor_pixel=500.0,
        anchor_wavelength=6562.81, refine=False)
    assert not result.ok
    assert result.reason_code == "no_match"


def test_identify_reports_low_confidence_on_a_noisy_window():
    # One real H-alpha line and five unknown dips: the name is right, but the
    # pattern is weak, so the confidence must say so.
    pixels = [100.0, 200.0, 300.0, 400.0, 500.0, 700.0]
    depths = [0.10, 0.10, 0.10, 0.10, 0.30, 0.10]
    profile = _spectrum(pixels, depths, length=2000)
    result = spectrum.identify_lines(
        profile, 0.1, anchor_pixel=500.0,
        anchor_wavelength=6562.81, refine=False)
    assert result.ok
    assert result.reason_code == "low_confidence"
    assert result.confidence < spectrum.DEFAULT_MIN_CONFIDENCE
    assert any(line.name == "H-alpha" for line in result.lines)


def test_identification_result_is_frozen_and_has_the_contract_fields():
    result = spectrum.identify_lines(
        _spectrum([500.0], [0.3], length=2000), 0.1,
        target_wavelength=6562.81)
    names = {field.name for field in fields(spectrum.IdentificationResult)}
    assert {
        "ok", "lines", "anchor_wavelength", "dispersion_a_px", "confidence",
        "reason_code",
    }.issubset(names)
    with pytest.raises(FrozenInstanceError):
        result.confidence = 0.0


def test_catalog_is_sorted_unique_and_in_the_visible_range():
    wavelengths = [line.wavelength_angstrom for line in spectrum.CATALOG]
    names = [line.name for line in spectrum.CATALOG]
    assert wavelengths == sorted(wavelengths)
    assert len(names) == len(set(names))
    assert all(3800.0 <= wavelength <= 9000.0 for wavelength in wavelengths)
    assert all(line.kind in ("solar", "telluric") for line in spectrum.CATALOG)


def test_catalog_contains_the_requested_groups():
    by_name = {line.name: line for line in spectrum.CATALOG}
    # Hydrogen Balmer series.
    for name in ("H-alpha", "H-beta", "H-gamma", "H-delta",
                 "H-epsilon", "H-zeta", "H-eta"):
        assert name in by_name
    # Calcium H and K.
    assert by_name["Ca II K"].wavelength_angstrom == pytest.approx(3933.66)
    assert by_name["Ca II H"].wavelength_angstrom == pytest.approx(3968.47)
    # Sodium and magnesium.
    assert by_name["Na I D2"].wavelength_angstrom == pytest.approx(5889.95)
    assert by_name["Na I D1"].wavelength_angstrom == pytest.approx(5895.92)
    assert by_name["Mg I b1"].wavelength_angstrom == pytest.approx(5183.62)
    # The iron pair near H-alpha.
    assert by_name["Fe I 6569.224"].wavelength_angstrom == pytest.approx(6569.224)
    assert by_name["Fe I 6575.037"].wavelength_angstrom == pytest.approx(6575.037)
    # Telluric oxygen bands.
    assert by_name["O2 A"].kind == "telluric"
    assert by_name["O2 B"].kind == "telluric"
    assert by_name["H2O (telluric)"].kind == "telluric"


def test_catalog_h_alpha_is_the_fraunhofer_c_value():
    # The usual SHG target: the Fraunhofer C line at 6562.81 A.
    h_alpha = [line for line in spectrum.CATALOG if line.name == "H-alpha"]
    assert len(h_alpha) == 1
    assert h_alpha[0].wavelength_angstrom == pytest.approx(6562.81)


def test_catalog_lines_between_is_sorted_and_inclusive():
    lines = spectrum.catalog_lines_between(6550.0, 6580.0)
    assert [line.name for line in lines] == [
        "H-alpha", "Fe I 6569.224", "Fe I 6575.037"]
    assert spectrum.catalog_lines_between(6580.0, 6550.0) == lines


def test_dispersion_profile_means_over_the_slit_axis():
    # Height = dispersion (Y), width = slit (X). Each row is a constant, so
    # the mean over X returns the row value.
    row_values = np.linspace(1000.0, 900.0, 60)
    # float32 keeps the fractional row values; a uint16 frame would round them
    # and the comparison would be against the rounded profile, not the input.
    data = np.tile(row_values[:, None], (1, 40)).astype(np.float32)
    frame = FakeFrame(data)
    profile = spectrum.dispersion_profile(frame)
    assert profile.shape == (60,)
    assert np.allclose(profile, row_values)


def test_dispersion_profile_crops_the_band():
    row_values = np.linspace(1000.0, 900.0, 60)
    data = np.tile(row_values[:, None], (1, 40)).astype(np.float32)
    frame = FakeFrame(data)
    profile = spectrum.dispersion_profile(frame, (10, 20, 20, 30))
    assert profile.shape == (30,)
    assert np.allclose(profile, row_values[20:50])


def test_dispersion_profile_of_an_empty_band_is_empty():
    frame = FakeFrame(np.zeros((20, 20), dtype=np.uint16))
    assert spectrum.dispersion_profile(frame, (50, 50, 10, 10)).size == 0
