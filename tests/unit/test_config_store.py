############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - config store test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The INI schema reconciliation with nightscribe-scan and the contract of
# config/store.py (design/ARCHITECTURE.md 3.2, ADR-003, ADR-024).
#
# The first table is deliberately long: it is the parity contract. Every key the
# prototype declares must exist here with its exact section, spelling and
# default, because the user's existing nightscribe-scan.cfg and the existing
# post-processing depend on them. The rest of the file pins the tolerant reading
# that keeps a hand-edited file, or a profile written by another version, from
# stopping the app at start.

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from solarscribe.config import paths, store
from solarscribe.config.store import Settings, default_settings
from solarscribe.config.schema import (
    PROFILE_VERSION,
    SCHEMA,
    SESSION_STATE_FILE,
    SESSION_STEPS,
    CameraData,
    Profile,
    RoiPreset,
    SessionState,
    StepState,
    StepStatus,
    TelescopeData,
    default_value,
    keys_of,
)

# Every key of nightscribe-scan's CONFIG_SCHEMA, spelled exactly as its
# lowercase constant and with the default of its module constant. The one
# deliberate exception is documented next to it (ADR-024).
INHERITED = {
    "optics": {
        "focal_length": 714.0,
        "pixel_size": 2.0,
        "sidereal": 15.04,
        "use_ephemeris": True,
        "ephemeris_diameter_override": 0.0,
        "solar_diameter": 1920.0,
    },
    "scan": {
        "enable_capture": True,
        "enable_auto_exp": True,
        # ADR-024: spelling inherited, default raised from 1 to 3 because
        # DESIGN.md 7 asks for three cycles per session.
        "num_cycles": 3,
        "padded_duration": 3.0,
        "padded_arcsec": 100.0,
        "scan_preload_seconds": 0.3,
        "trailing_limb_stop": True,
        "trailing_margin_arcsec": 50.0,
        "trailing_stddev_fraction": 0.15,
        "return_multiplier": 32.0,
    },
    "fps": {
        "capture_fps": 0.0,
        "fps_samples": 5,
        "fps_sample_interval": 0.2,
        "fps_probe_seconds": 0.0,
        "capture_start_timeout": 5.0,
        "capture_start_settle": 0.1,
        "capture_stall_seconds": 3.0,
        "frames_short_tol": 0.1,
        "capture_min_free_gb": 1.0,
    },
    "limb": {
        "limb_search_speed": 4.0,
        "limb_sample_interval": 0.05,
        "limb_max_search": 120.0,
        "limb_stddev_min": 500.0,
        "on_disk_stddev": 2000.0,
        "limb_dark_mult": 5.0,
    },
    "dec": {
        "enable_dec_centering": True,
        "dec_interval": 2,
        "dec_center_tolerance": 0.03,
        "dec_max_corrections": 8,
        "dec_nudge_speed": 3.0,
        "dec_settle_time": 0.3,
        "dec_drift_tol_arcsec": 10.0,
    },
    "mosaic": {
        "enable_mosaic": False,
        "mosaic_slit_length_mm": 7.0,
        "mosaic_slit_image_scale": 1.0,
        "mosaic_overlap": 0.15,
        "mosaic_margin_arcsec": 100.0,
        "mosaic_scans_per_row": 5,
        "mosaic_auto_center_dec": True,
        "mosaic_center_max_iter": 3,
        "mosaic_center_residual_arcsec": 300.0,
        "mosaic_dec_speed": 3.0,
        "mosaic_dec_backlash": 30.0,
        "mosaic_dec_settle": 0.5,
        "mosaic_chord_speed": 16.0,
    },
    "exposure": {
        "exp_percentile": 0.995,
        "exp_target_level": 0.88,
        "exp_tolerance": 0.04,
        "exp_max_attempts": 6,
    },
    "calibration": {
        "calibrate_scan_rate": True,
        "calibration_samples": 1,
        "consistency_tol_xy": 0.03,
        "consistency_tol_extent": 0.03,
        "scan_retries": 1,
        "cos_dec_correction": True,
        "measure_slit_extent": True,
        "slit_extent_bands": 48,
    },
    "logging": {
        "scan_log_path": "",
        "scan_stats_path": "",
        "session_meta_path": "",
    },
}

# SolarScribe keys that predate the reconciliation and were renamed to the
# reference spelling. They stay in the schema because other agents may already
# name them, but the canonical key owns the behaviour (ADR-024).
LEGACY = {
    ("scan", "cycles"): ("scan", "num_cycles"),
    ("scan", "padding_s"): ("scan", "padded_duration"),
    ("scan", "preload_s"): ("scan", "scan_preload_seconds"),
    ("scan", "adaptive_stop"): ("scan", "trailing_limb_stop"),
    ("capture", "stall_timeout_s"): ("fps", "capture_stall_seconds"),
    ("capture", "min_free_disk_gb"): ("fps", "capture_min_free_gb"),
    ("camera", "auto_exposure"): ("scan", "enable_auto_exp"),
}


# @args: section, name - a key of the schema
# @return: the Key row, so a test can read its origin and kind
def key_of(section: str, name: str):
    for key in SCHEMA:
        if key.section == section and key.name == name:
            return key
    raise AssertionError(f"{section}.{name} is not in the schema")


@pytest.mark.parametrize(
    "section,name,default",
    [(section, name, default)
     for section, names in INHERITED.items()
     for name, default in names.items()],
)
def test_inherited_keys_keep_the_reference_spelling_and_default(section, name, default):
    # The parity contract: a nightscribe-scan.cfg key means the same thing here,
    # so the user's file keeps working untouched (ADR-003, ADR-024).
    assert default_value(section, name) == default
    assert key_of(section, name).origin == "scan"


def test_the_inherited_block_is_the_whole_prototype_schema():
    # 66 is the number of entries in the prototype's CONFIG_SCHEMA. A new key
    # marked "scan" would mean we invented an inheritance, and a missing one
    # means the user's file has a setting we silently ignore.
    assert sum(key.origin == "scan" for key in SCHEMA) == 66


def test_new_keys_are_marked_as_solarscribe():
    # Origin drives the settings dialog and the parity note: a key marked "new"
    # is ours and can change spelling without touching the user's habits.
    for section, name in (("roi", "capture_width"), ("mount", "backend"),
                          ("session", "base_name"), ("polar", "sample_interval_s"),
                          ("capture", "queue_budget_mb")):
        assert key_of(section, name).origin == "new"


def test_duplicate_behaviours_are_gone_and_the_legacy_names_survive():
    # general.dry_run and scan.mode duplicated scan.enable_capture and
    # scan.enable_mosaic: two truths for one switch. They were replaced, not
    # kept (ADR-024). The renamed keys stay as legacy aliases so no agent that
    # used their old name breaks.
    for section, name in (("general", "dry_run"), ("scan", "mode")):
        with pytest.raises(KeyError):
            default_value(section, name)

    for legacy, canonical in LEGACY.items():
        # Same type and the same default: the alias can never disagree with its
        # canonical key when the file is silent.
        assert key_of(*legacy).kind is key_of(*canonical).kind
        assert default_value(*legacy) == default_value(*canonical)


def test_legacy_keys_are_hidden_from_the_settings_dialog():
    # The dialog must show one control per behaviour, not a control and its
    # alias (ADR-024). A migration tool can ask for them explicitly.
    visible = keys_of("scan")
    assert "cycles" not in {key.name for key in visible}
    assert "num_cycles" in {key.name for key in visible}
    everything = keys_of("scan", include_legacy=True)
    assert "cycles" in {key.name for key in everything}

    # Settings.section() is the dialog's view of the file, so it hides the
    # aliases the same way.
    settings = default_settings()
    assert "cycles" not in settings.section("scan")
    assert "cycles" in settings.section("scan", include_legacy=True)


def test_settings_defaults_cover_every_key(tmp_path):
    # A missing INI is not an error: every key answers with its default, so the
    # app always starts (ADR-003).
    settings = store.load_settings(tmp_path / "missing.ini")
    for key in SCHEMA:
        assert settings.get(key.section, key.name) == key.default
    assert settings.unknown == ()
    with pytest.raises(KeyError):
        settings.get("scan", "not_a_key")


def test_settings_read_a_hand_written_ini(tmp_path):
    # Comments, ':' separators, odd case and the fixed boolean vocabulary all
    # have to behave: the file is meant to be edited by hand on both platforms.
    path = tmp_path / "config.ini"
    path.write_text(
        "; a comment line\n"
        "[OPTICS]\n"
        "focal_length: 900   # measured on the recon\n"
        "pixel_size = 3\n"
        "\n"
        "[scan]\n"
        "enable_capture = off\n"
        "enable_auto_exp = YES\n"
        "num_cycles = 7\n"
        "padded_duration = 2.5\n"
        "\n"
        "[fps]\n"
        "capture_stall_seconds = 4\n"
        "capture_min_free_gb = 2\n"
        "\n"
        "[dec]\n"
        "dec_interval = 4\n",
        encoding="utf-8",
    )
    settings = store.load_settings(path)
    assert settings.get("optics", "focal_length") == 900.0
    assert settings.get("optics", "pixel_size") == 3.0
    assert settings.get("scan", "enable_capture") is False
    assert settings.get("scan", "enable_auto_exp") is True
    assert settings.get("scan", "num_cycles") == 7
    assert settings.get("scan", "padded_duration") == 2.5
    assert settings.get("fps", "capture_stall_seconds") == 4.0
    assert settings.get("fps", "capture_min_free_gb") == 2.0
    assert settings.get("dec", "dec_interval") == 4
    # A key absent from the file still answers its default.
    assert settings.get("limb", "limb_stddev_min") == 500.0


def test_boolean_vocabulary_is_fixed_and_garbage_keeps_the_default(tmp_path):
    # Windows and Linux editors disagree on everything else; a word outside the
    # vocabulary must fall back to the default instead of raising or reading
    # True (ADR-024).
    path = tmp_path / "config.ini"
    path.write_text(
        "[scan]\n"
        "enable_capture = 1\n"
        "enable_auto_exp = true\n"
        "trailing_limb_stop = maybe\n"
        "[mosaic]\n"
        "enable_mosaic = OFF\n"
        "mosaic_auto_center_dec = 0\n",
        encoding="utf-8",
    )
    settings = store.load_settings(path)
    assert settings.get("scan", "enable_capture") is True
    assert settings.get("scan", "enable_auto_exp") is True
    assert settings.get("scan", "trailing_limb_stop") is True      # default
    assert settings.get("mosaic", "enable_mosaic") is False
    assert settings.get("mosaic", "mosaic_auto_center_dec") is False


def test_bad_numbers_and_unknown_keys_do_not_stop_the_reader(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text(
        "[scan]\n"
        "num_cycles = many\n"
        "padded_arcsec = 120\n"
        "[invented]\n"
        "surprise = 1\n",
        encoding="utf-8",
    )
    settings = store.load_settings(path)
    assert settings.get("scan", "num_cycles") == 3      # default, not a crash
    assert settings.get("scan", "padded_arcsec") == 120.0
    assert settings.unknown == ("invented.surprise",)


def test_settings_accept_a_latin1_file(tmp_path):
    # The prototype's panel could write cp1252; a stray accent in a comment must
    # not make the whole configuration unreadable.
    path = tmp_path / "config.ini"
    path.write_bytes("[optics]\n# medido en el a\u00f1o 2026\nfocal_length = 800\n".encode("latin-1"))
    settings = store.load_settings(path)
    assert settings.get("optics", "focal_length") == 800.0


def test_legacy_key_feeds_the_canonical_one(tmp_path):
    # A SolarScribe INI written before the reconciliation says cycles; the
    # engine reads num_cycles. The alias must translate, and both names must
    # answer the same value afterwards (ADR-024).
    path = tmp_path / "config.ini"
    path.write_text("[scan]\ncycles = 5\n", encoding="utf-8")
    settings = store.load_settings(path)
    assert settings.get("scan", "num_cycles") == 5
    assert settings.get("scan", "cycles") == 5


def test_canonical_key_wins_over_its_legacy_alias(tmp_path):
    # If both are in the file the inherited spelling is the contract; the alias
    # must not be able to contradict it.
    path = tmp_path / "config.ini"
    path.write_text("[scan]\ncycles = 5\nnum_cycles = 2\n", encoding="utf-8")
    settings = store.load_settings(path)
    assert settings.get("scan", "num_cycles") == 2
    assert settings.get("scan", "cycles") == 2


def test_settings_save_round_trip_writes_the_canonical_names(tmp_path):
    settings = default_settings()
    values = dict(settings.values)
    values[("scan", "num_cycles")] = 4
    values[("optics", "focal_length")] = 850.0
    values[("scan", "enable_capture")] = False
    written = Settings(values=values, unknown=())
    path = tmp_path / "deep" / "config.ini"

    store.save_settings(written, path)

    text = path.read_text(encoding="utf-8")
    assert "[scan]" in text
    assert "num_cycles = 4" in text
    assert "focal_length = 850" in text
    assert "enable_capture = false" in text
    # The alias is never written as a key: one truth in the file. The check is
    # line-anchored because "num_cycles = 4" contains "cycles = 4".
    assert "\ncycles = 4" not in text
    # The why travels with the key: the file is self-documenting.
    assert "#" in text
    assert not list(path.parent.glob("*.tmp"))

    loaded = store.load_settings(path)
    assert loaded.get("scan", "num_cycles") == 4
    assert loaded.get("optics", "focal_length") == 850.0
    assert loaded.get("scan", "enable_capture") is False
    assert loaded.unknown == ()


def test_settings_save_skips_keys_that_are_not_in_the_schema(tmp_path):
    # An unknown key read from someone else's file must not be written back as
    # if SolarScribe owned it.
    settings = default_settings()
    polluted = Settings(values=dict(settings.values), unknown=("x.y",))
    path = tmp_path / "config.ini"
    store.save_settings(polluted, path)
    assert "x.y" not in path.read_text(encoding="utf-8")


def test_profile_without_a_file_is_the_default_profile(tmp_path):
    profile = store.load_profile(tmp_path / "missing.json")
    assert profile.version == PROFILE_VERSION
    assert profile.telescope.focal_length_mm == 714.0
    assert profile.camera.pixel_size_um == 2.0
    assert profile.preset("default") is not None


def test_profile_round_trip_keeps_telescope_camera_and_presets(tmp_path):
    profile = store.load_profile(tmp_path / "missing.json")
    assert profile.version == 2
    path = tmp_path / "deep" / "profile.json"
    tuned = Profile(
        telescope=TelescopeData(focal_length_mm=900.0, aperture_mm=102.0,
                                      slit_length_mm=10.0),
        camera=CameraData(model="Touptek G3M678M", pixel_size_um=2.0,
                                binning=1),
        roi_presets=(RoiPreset(name="wide", capture=(0, 0, 3480, 300),
                                     band=(0, 40, 3480, 160)),),
    )
    store.save_profile(tuned, path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 2
    assert raw["telescope"]["focal_length_mm"] == 900.0
    assert raw["roi_presets"][0]["capture"] == [0, 0, 3480, 300]

    loaded = store.load_profile(path)
    assert loaded.telescope.focal_length_mm == 900.0
    assert loaded.telescope.slit_length_mm == 10.0
    assert loaded.camera.model == "Touptek G3M678M"
    assert loaded.preset("wide").capture == (0, 0, 3480, 300)


def test_profile_tolerates_a_hand_written_file(tmp_path):
    # Strings for numbers, a missing section, an unknown key and a preset as a
    # map keyed by name: all of it must load, with defaults where it is broken.
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps({
            "version": 2,
            "telescope": {"focal_length_mm": "850", "aperture_mm": "bad"},
            "camera": {"pixel_size_um": "2.4", "binning": 0},
            "roi_presets": {
                "home": {"capture": ["0", "0", "3480", "248"],
                         "band": [0, 40, 3480, 160]},
                "broken": {"capture": [0, 0, 0, 248]},
            },
            "future_key": "ignored",
        }),
        encoding="utf-8",
    )
    profile = store.load_profile(path)
    assert profile.telescope.focal_length_mm == 850.0
    assert profile.telescope.aperture_mm == 80.0          # default
    assert profile.camera.pixel_size_um == 2.4
    assert profile.camera.binning == 1                    # 0 is not a binning
    assert profile.preset("home").capture == (0, 0, 3480, 248)
    assert profile.preset("broken").capture == (0, 0, 3480, 248)  # preset default


def test_profile_migrates_a_nightscribe_v1_profile(tmp_path):
    # The prototype stores {version: 1, profiles: {name: {meta, config}}} with
    # CONSTANT-name keys. A user who brings that file must get their instrument
    # back, not the reference defaults (ADR-024).
    path = tmp_path / "v1.json"
    path.write_text(
        json.dumps({
            "version": 1,
            "active": "C9",
            "profiles": {
                "C9": {
                    "meta": {"camera": "Touptek", "aperture_mm": 102,
                             "focal_length_mm": 900},
                    "config": {"FOCAL_LENGTH": 910, "PIXEL_SIZE": 3,
                               "MOSAIC_SLIT_LENGTH_MM": 10,
                               "NUM_CYCLES": 2},
                },
                "other": {"config": {"FOCAL_LENGTH": 400}},
            },
        }),
        encoding="utf-8",
    )
    profile = store.load_profile(path)
    assert profile.version == 2
    assert profile.telescope.focal_length_mm == 910.0
    assert profile.telescope.aperture_mm == 102.0
    assert profile.telescope.slit_length_mm == 10.0
    assert profile.camera.model == "Touptek"
    assert profile.camera.pixel_size_um == 3.0


def test_profile_migrates_a_flat_v1_config(tmp_path):
    # A single flat profile file (the panel's "download profile") has no
    # wrapper at all.
    path = tmp_path / "flat.json"
    path.write_text(
        json.dumps({"FOCAL_LENGTH": 750, "PIXEL_SIZE": 2.9}),
        encoding="utf-8",
    )
    profile = store.load_profile(path)
    assert profile.telescope.focal_length_mm == 750.0
    assert profile.camera.pixel_size_um == 2.9


def test_profile_migrates_a_v1_map_without_its_wrapper(tmp_path):
    # A map of profiles with the version field next to them, no "profiles"
    # member: the metadata keys must not be mistaken for profile names.
    path = tmp_path / "map.json"
    path.write_text(
        json.dumps({
            "version": 1,
            "Sun": {"config": {"FOCAL_LENGTH": 800}},
        }),
        encoding="utf-8",
    )
    profile = store.load_profile(path)
    assert profile.telescope.focal_length_mm == 800.0


def test_profile_broken_json_returns_the_defaults(tmp_path):
    # A truncated file from a crash must not stop the app: defaults, and the
    # user can overwrite it from Settings.
    path = tmp_path / "profile.json"
    path.write_text("{not json", encoding="utf-8")
    profile = store.load_profile(path)
    assert profile.telescope.focal_length_mm == 714.0


def test_session_state_without_a_file_starts_pending(tmp_path):
    state = store.load_session_state(tmp_path / "missing.json")
    assert set(state.steps) == set(SESSION_STEPS)
    for step in state.steps.values():
        assert step.status is StepStatus.PENDING


def test_session_state_round_trip(tmp_path):
    state = SessionState(
        steps={
            "find_sun": StepState(status=StepStatus.DONE,
                                        updated_at="2026-11-06T10:00:00Z",
                                        metrics={"dec_error_arcsec": 12.5}),
            "polar": StepState(status=StepStatus.CURRENT),
            "roi": StepState(),
            "scan": StepState(),
        },
        session_dir="/tmp/session",
        created_at="2026-11-06T09:00:00Z",
        updated_at="2026-11-06T10:00:00Z",
    )
    path = tmp_path / "session" / SESSION_STATE_FILE
    store.save_session_state(state, path)
    loaded = store.load_session_state(path)
    assert loaded.steps["find_sun"].status is StepStatus.DONE
    assert loaded.steps["find_sun"].metrics["dec_error_arcsec"] == 12.5
    assert loaded.steps["polar"].status is StepStatus.CURRENT
    assert loaded.session_dir == "/tmp/session"


def test_session_state_tolerates_a_hand_written_file(tmp_path):
    # Unknown steps are ignored, missing steps are pending, an unknown status
    # is pending and a non-numeric metric is dropped: the rail always paints.
    path = tmp_path / "session_state.json"
    path.write_text(
        json.dumps({
            "steps": {
                "find_sun": {"status": "done", "metrics": {"tilt_deg": "0.4",
                                                           "note": "text"}},
                "invented": {"status": "done"},
            },
            "created_at": "2026-11-06T09:00:00Z",
        }),
        encoding="utf-8",
    )
    state = store.load_session_state(path)
    assert set(state.steps) == set(SESSION_STEPS)
    assert state.steps["find_sun"].status is StepStatus.DONE
    assert state.steps["find_sun"].metrics == {"tilt_deg": 0.4}
    assert state.steps["scan"].status is StepStatus.PENDING


def test_session_folder_is_created_and_named_with_its_date(tmp_path):
    when = datetime(2026, 11, 6, 19, 30)
    folder = store.session_folder(tmp_path, when)
    assert folder.is_dir()
    assert folder.name == "20261106_1930"
    # Two sessions inside the same minute must not share a folder: the second
    # one gets a suffix instead of overwriting the first (ADR-024).
    again = store.session_folder(tmp_path, when)
    assert again.name == "20261106_1930_2"
    assert again.is_dir() and again != folder


def test_scan_ser_path_follows_the_session_naming(tmp_path):
    when = datetime(2026, 11, 6, 19, 30)
    path = store.scan_ser_path(tmp_path, "sun", when, 3)
    assert path.name == "sun_20261106_1930_scan03.ser"
    assert path.parent == tmp_path
    # An empty base name falls back to sun instead of producing "_...".
    assert store.scan_ser_path(tmp_path, "  ", when, 1).name == \
        "sun_20261106_1930_scan01.ser"
    # Scan numbering is 1-based; 0 is a programming error, not a file name.
    with pytest.raises(ValueError):
        store.scan_ser_path(tmp_path, "sun", when, 0)


def test_session_companion_files_live_next_to_the_ser(tmp_path):
    # One CSV, one JSONL and one session_meta.json per SESSION folder, the same
    # names the post-processing already reads (ADR-018). Their columns never
    # change shape; only the path is decided here.
    assert store.scan_log_path(tmp_path) == tmp_path / "scan_log.csv"
    assert store.scan_stats_path(tmp_path) == tmp_path / "scan_stats.jsonl"
    assert store.session_meta_path(tmp_path) == tmp_path / "session_meta.json"
    assert store.session_state_path(tmp_path) == tmp_path / SESSION_STATE_FILE


def test_logging_keys_can_move_the_logs(tmp_path):
    # The inherited [logging] keys are a path, not a folder: empty means the
    # session folder. A relative path resolves against the session folder so the
    # app behaves the same whatever the working directory is when it starts.
    absolute = tmp_path / "elsewhere" / "scan.csv"
    assert store.scan_log_path(tmp_path, str(absolute)) == absolute
    assert store.scan_stats_path(tmp_path, "logs/stats.jsonl") == \
        tmp_path / "logs" / "stats.jsonl"
    assert store.session_meta_path(tmp_path, "") == tmp_path / "session_meta.json"


def test_paths_resolve_per_platform_directories():
    # platformdirs puts the small files under the user's config directory and
    # the sessions under the user's data directory; nothing is written next to
    # the executable, which is read-only in Program Files (ADR-004, ADR-024).
    config = paths.config_dir()
    data = paths.data_dir()
    assert isinstance(config, Path) and isinstance(data, Path)
    assert config.name == "SolarScribe"
    assert data.name == "SolarScribe"
    assert paths.settings_path() == config / "config.ini"
    assert paths.profile_path() == config / "profile.json"
    assert paths.default_session_base() == data / "sessions"
    assert paths.log_dir().is_absolute()
