############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - config store module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Reading and writing the user's files (design/ARCHITECTURE.md 3.2 and 2.4,
# ADR-003, ADR-024).
#
# The split with config/schema.py is deliberate (ADR-023): schema.py holds the
# value types and the table, this module holds the algorithms. No layer above
# needs to know how an INI comment is stripped or how a v1 profile is migrated;
# it asks for a Settings, a ProfileStore, a Profile or a SessionState and gets a
# complete object with every default already applied.
#
# Named profiles (ADR-027): profiles.json holds every name and the active one;
# the single profile.json is still read and becomes the "default" profile.
#
# Three rules drive every choice here:
#
#   1. A hand-edited file never stops the app. A missing key, a garbled number,
#      an unknown section or a truncated JSON all fall back to the schema
#      default (ADR-003). The one thing never done is inventing a value.
#   2. One truth per behaviour. The inherited nightscribe-scan key is canonical;
#      a legacy SolarScribe name is read only when the canonical key is absent,
#      and save_settings writes the canonical name alone (ADR-024). The file a
#      user opens after a save has no contradictions in it.
#   3. Writes are atomic. Settings, profile and session state are written to a
#      temporary file in the same directory and then moved over the target, so a
#      crash mid-write leaves the previous good file instead of half a file.
#      Losing the ROI preset because the laptop slept at the wrong moment is
#      exactly the failure this prevents.
#
# Encoding: UTF-8 first, Latin-1 as a fallback, the same tolerance the prototype
# applies. Its HTML panel could write cp1252 on Windows, and one stray accent in
# a comment must not make a whole configuration unreadable.

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from solarscribe.config.schema import (
    LEGACY_KEYS,
    PROFILE_FILE,
    PROFILE_VERSION,
    PROFILES_VERSION,
    SCAN_LOG_FILE,
    SCAN_STATS_FILE,
    SCHEMA,
    SESSION_META_FILE,
    SESSION_STATE_FILE,
    SESSION_STEPS,
    CameraData,
    Profile,
    RoiPreset,
    SessionState,
    StepState,
    StepStatus,
    TelescopeData,
    keys_of,
    new_steps,
)

__all__ = [
    "SESSION_FOLDER_FORMAT",
    "ProfileStore",
    "Settings",
    "active_profile",
    "default_profile_store",
    "default_settings",
    "delete_profile",
    "load_profile",
    "load_profiles",
    "load_session_state",
    "load_settings",
    "profile_names",
    "rename_profile",
    "save_named_profile",
    "save_profile",
    "save_profiles",
    "save_session_state",
    "save_settings",
    "scan_log_path",
    "scan_ser_path",
    "scan_stats_path",
    "session_folder",
    "session_meta_path",
    "session_state_path",
    "set_active_profile",
]

# The session folder name: local date and minute, sortable as text, and readable
# by a human who opens the folder a month later. Seconds are not used on purpose
# (a session lasts tens of minutes); a collision in the same minute gets a
# numeric suffix instead.
SESSION_FOLDER_FORMAT = "%Y%m%d_%H%M"

# The fixed boolean vocabulary (ADR-003, ADR-024). The prototype accepted the
# same words, and pinning them here means a file written with "yes" on Linux
# still means true when it is opened on Windows. Anything outside the two sets
# keeps the schema default instead of guessing.
_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "no", "off"})

# Derived index of the table. It is built from SCHEMA, not kept by hand, so it
# cannot drift; it only avoids a linear scan per key while reading.
_INDEX = {(key.section, key.name): key for key in SCHEMA}


# @args: path - a file that may not exist
# @return: its text, or None when it is absent or unreadable. UTF-8 first,
#          Latin-1 as the fallback for the panel's old cp1252 files
def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


# @args: path - the target file; text - the complete content
# @return: nothing. Creates the parent directories and replaces the target in
#          one move, so a crash leaves the previous file intact
def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    finally:
        # A failed write must not leave the temporary file behind for the next
        # run to trip over.
        if tmp.exists():
            tmp.unlink()


# @args: text - the INI text
# @return: {(section, key): raw text}. Sections and keys are lowercased because
#          the schema is lowercase and a hand-edited file is not; '#' and ';'
#          start a comment, and '=' or ':' separates key from value, as in the
#          prototype's parser
def _parse_ini(text: str) -> dict[tuple[str, str], str]:
    values: dict[tuple[str, str], str] = {}
    section = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            continue
        separator = "=" if "=" in line else (":" if ":" in line else None)
        if separator is None:
            continue
        name, value = line.split(separator, 1)
        values[(section, name.strip().lower())] = value.strip()
    return values


# @args: text - the raw value; kind - int, float, bool or str; default - what to
#        answer when the text cannot be read
# @return: the value with the type the schema declares
def _coerce(text: str, kind: type, default: object) -> object:
    if kind is bool:
        lowered = text.strip().lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        return default
    if kind is int:
        try:
            # int(float(...)) accepts "120.0", which a hand edit or a spreadsheet
            # export produces and which the prototype also accepted.
            return int(float(text))
        except (TypeError, ValueError):
            return default
    if kind is float:
        try:
            return float(text)
        except (TypeError, ValueError):
            return default
    return text


# @args: value - a value from the file; kind - the target type; default - the
#        fallback
# @return: the value formatted as the INI writes it. Booleans use true/false,
#          never 1/0, because the file is also read by people
def _format(value: object, kind: type, default: object) -> str:
    try:
        if kind is bool:
            return "true" if bool(value) else "false"
        if kind is int:
            return str(int(value))
        if kind is float:
            # 12 significant digits keep 15.04 and 0.03 intact without turning
            # 0.30000000000000004 into noise.
            return format(float(value), ".12g")
        return str(value)
    except (TypeError, ValueError):
        # A caller handed a value of the wrong type; write the schema default
        # rather than a file the next reader cannot parse.
        if kind is bool:
            return "true" if bool(default) else "false"
        if kind is int:
            return str(int(default))
        if kind is float:
            return format(float(default), ".12g")
        return str(default)


@dataclass(frozen=True)
class Settings:
    # A complete set of INI values: one entry per SCHEMA key, plus the names the
    # file had that the schema does not know.
    #
    # It lives here, next to the reader and the writer, because it is the shape
    # store.py returns and not a declaration the schema owns (ADR-023: the
    # contract of the table is in schema.py, the behaviour is here).
    #
    # `values` is keyed by (section, name) and is complete on purpose: a
    # consumer never has to know what a missing key means, because load_settings
    # already filled it with the default (ADR-003). `unknown` is the typo
    # report: the settings dialog can warn that a key will be ignored instead of
    # silently dropping it, which is how a hand-edited file teaches a wrong
    # spelling for years (ADR-024).
    values: dict[tuple[str, str], object]
    unknown: tuple[str, ...] = ()

    # @args: section, name - an INI key
    # @return: its value. KeyError for a key outside the schema, like
    #          schema.default_value(), so a typo cannot read as a default
    def get(self, section: str, name: str) -> object:
        return self.values[(section, name)]

    # @args: name - an INI section; include_legacy - also return the aliases
    # @return: that section as a plain name -> value map, in schema order, for
    #          the settings dialog and for logging. It hides the legacy aliases
    #          by default, exactly like keys_of(), so the dialog shows one
    #          control per behaviour
    def section(self, name: str, *, include_legacy: bool = False) -> dict[str, object]:
        return {key.name: self.values[(key.section, key.name)]
                for key in keys_of(name, include_legacy=include_legacy)}


# @return: a Settings with every key at its schema default, the same object
#          load_settings() produces for a missing file
def default_settings() -> Settings:
    return Settings(values={(key.section, key.name): key.default for key in SCHEMA})


# @args: path - the INI file; a missing file is not an error
# @return: a Settings with every schema key present. Canonical inherited names
#          are authoritative; a legacy name is translated only when its
#          canonical key is absent from the file (ADR-024)
def load_settings(path: str | Path) -> Settings:
    text = _read_text(Path(path))
    data = _parse_ini(text) if text is not None else {}

    values: dict[tuple[str, str], object] = {}
    for key in SCHEMA:
        raw = data.get((key.section, key.name))
        values[(key.section, key.name)] = (
            key.default if raw is None else _coerce(raw, key.kind, key.default)
        )

    for legacy, canonical in LEGACY_KEYS:
        canonical_key = _INDEX[canonical]
        if legacy in data and canonical not in data:
            # An INI written before the reconciliation named the old key; its
            # value is the user's intent, so it feeds the canonical one.
            values[canonical] = _coerce(
                data[legacy], canonical_key.kind, canonical_key.default
            )
        # Both names answer the same value, so an old caller keeps reading the
        # truth even after the file migrated to the new spelling.
        values[legacy] = values[canonical]

    known = {(key.section, key.name) for key in SCHEMA}
    unknown = tuple(sorted(f"{section}.{name}" for (section, name) in data
                           if (section, name) not in known))
    return Settings(values=values, unknown=unknown)


# @args: settings - a complete Settings; path - where to write it
# @return: nothing. Writes one section per block, one comment per key and the
#          canonical names only, so the file is self-documenting and has no two
#          keys that mean the same thing
def save_settings(settings: Settings, path: str | Path) -> None:
    lines: list[str] = []
    current = None
    legacy = {name for name, _ in LEGACY_KEYS}
    for key in SCHEMA:
        if (key.section, key.name) in legacy:
            continue
        if key.section != current:
            if current is not None:
                lines.append("")
            current = key.section
            lines.append(f"[{current}]")
        value = settings.values.get((key.section, key.name), key.default)
        # The why travels with the key: the file teaches what the setting does
        # (AGENTS.md: no figure without an explanation).
        lines.append(f"# {key.why}")
        lines.append(f"{key.name} = {_format(value, key.kind, key.default)}")
    lines.append("")
    _write_atomic(Path(path), "\n".join(lines))


# @args: value - a number or numeric string; default - the fallback
# @return: the value as a float. Booleans are rejected on purpose: True is not
#          a focal length, and accepting it would hide a hand-edit mistake
def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# @args: value - a number or numeric string; default - the fallback
# @return: the value as an int
def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# @args: value - anything; default - the fallback
# @return: value when it is a string, default otherwise
def _as_str(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


# @args: value - a list, tuple or dict-shaped ROI; default - the fallback
# @return: an (x, y, width, height) tuple of ints, or the default when the shape
#          or the numbers are impossible. A zero or negative width or height is
#          not a ROI (ADR-010)
def _as_roi(value: object, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return default
    try:
        roi = tuple(int(float(item)) for item in value)
    except (TypeError, ValueError):
        return default
    if roi[0] < 0 or roi[1] < 0 or roi[2] <= 0 or roi[3] <= 0:
        return default
    return roi


# @args: raw - the roi_presets member of a v2 file: a list of preset objects, or
#        a map name -> preset
# @return: the presets, or the single default preset when none is usable. A
#          preset with a broken rectangle keeps the default rectangle instead of
#          vanishing: the name is the user's, the numbers are ours to repair
def _as_presets(raw: object) -> tuple[RoiPreset, ...]:
    default = RoiPreset()
    items: list[tuple[object, object]] = []
    if isinstance(raw, list):
        items = [(None, item) for item in raw]
    elif isinstance(raw, dict):
        items = list(raw.items())

    presets: list[RoiPreset] = []
    seen: set[str] = set()
    for name_from_map, item in items:
        if not isinstance(item, dict):
            continue
        name = _as_str(item.get("name"), _as_str(name_from_map, default.name))
        if not name:
            name = default.name
        if name in seen:
            continue
        seen.add(name)
        presets.append(RoiPreset(
            name=name,
            capture=_as_roi(item.get("capture"), default.capture),
            band=_as_roi(item.get("band"), default.band),
        ))
    return tuple(presets) if presets else (default,)


# @args: data - a parsed v2 JSON object
# @return: the Profile. Unknown keys are ignored and every bad value falls back
#          to its default, so a hand-written file is as valid as a saved one
def _profile_from_v2(data: dict) -> Profile:
    telescope = data.get("telescope") if isinstance(data.get("telescope"), dict) else {}
    camera = data.get("camera") if isinstance(data.get("camera"), dict) else {}
    default_telescope = TelescopeData()
    default_camera = CameraData()
    return Profile(
        version=PROFILE_VERSION,
        telescope=TelescopeData(
            focal_length_mm=_as_float(
                telescope.get("focal_length_mm"), default_telescope.focal_length_mm
            ),
            aperture_mm=_as_float(
                telescope.get("aperture_mm"), default_telescope.aperture_mm
            ),
            slit_length_mm=_as_float(
                telescope.get("slit_length_mm"), default_telescope.slit_length_mm
            ),
        ),
        camera=CameraData(
            model=_as_str(camera.get("model"), default_camera.model),
            pixel_size_um=_as_float(
                camera.get("pixel_size_um"), default_camera.pixel_size_um
            ),
            binning=max(1, _as_int(camera.get("binning"), default_camera.binning)),
        ),
        roi_presets=_as_presets(data.get("roi_presets")),
    )


# @args: data - a parsed nightscribe-scan profile: {version: 1, profiles: {...}},
#        a map of profiles, or one flat config
# @return: the v2 Profile. The panel stored CONSTANT-named keys, so the three
#          that define the instrument are translated and the rest is left where
#          it belongs: the INI, not the profile (ADR-024)
def _profile_from_v1(data: dict) -> Profile:
    profiles = data.get("profiles")
    chosen: dict = {}
    metadata = ("version", "active", "profiles")
    entries = {name: item for name, item in data.items() if name not in metadata}
    single = "meta" in data or "config" in data
    if isinstance(profiles, dict) and profiles:
        active = data.get("active")
        candidate = profiles.get(active) if isinstance(active, str) else None
        if not isinstance(candidate, dict):
            candidate = profiles.get("default")
        if not isinstance(candidate, dict):
            candidate = next((item for item in profiles.values()
                              if isinstance(item, dict)), None)
        chosen = candidate if isinstance(candidate, dict) else {}
    elif not single and entries and all(isinstance(item, dict)
                                        for item in entries.values()):
        # A map of profiles with no wrapper: the active one is unknown, so take
        # "default" or the first. The version and active fields are metadata,
        # not profile names.
        candidate = entries.get("default")
        if not isinstance(candidate, dict):
            candidate = next((item for item in entries.values()
                              if isinstance(item, dict)), None)
        chosen = candidate if isinstance(candidate, dict) else {}
    else:
        chosen = data

    meta = chosen.get("meta") if isinstance(chosen.get("meta"), dict) else {}
    config = chosen.get("config") if isinstance(chosen.get("config"), dict) else chosen
    default_telescope = TelescopeData()
    default_camera = CameraData()

    # FOCAL_LENGTH and PIXEL_SIZE are the prototype's geometry; the meta block
    # may repeat the focal length, so it is the fallback.
    focal = _as_float(
        config.get("FOCAL_LENGTH"),
        _as_float(meta.get("focal_length_mm"), default_telescope.focal_length_mm),
    )
    aperture = _as_float(meta.get("aperture_mm"), default_telescope.aperture_mm)
    slit = _as_float(
        config.get("MOSAIC_SLIT_LENGTH_MM"), default_telescope.slit_length_mm
    )
    pixel = _as_float(config.get("PIXEL_SIZE"), default_camera.pixel_size_um)
    model = _as_str(meta.get("camera"), default_camera.model)
    return Profile(
        version=PROFILE_VERSION,
        telescope=TelescopeData(focal_length_mm=focal, aperture_mm=aperture,
                                slit_length_mm=slit),
        camera=CameraData(model=model, pixel_size_um=pixel,
                          binning=default_camera.binning),
        roi_presets=(RoiPreset(),),
    )


# @args: data - anything json.loads returned
# @return: the Profile. v2 is recognised by its version or by any of its three
#          sections; everything else is treated as a v1 file and migrated
def _profile_from_json(data: object) -> Profile:
    if not isinstance(data, dict):
        return Profile()
    version = data.get("version")
    is_v2 = (isinstance(version, int) and not isinstance(version, bool)
             and version >= PROFILE_VERSION)
    if is_v2 or any(name in data for name in ("telescope", "camera", "roi_presets")):
        return _profile_from_v2(data)
    return _profile_from_v1(data)


# @args: path - the profile file; a missing or broken file is not an error
# @return: the Profile, migrated to v2 when the file is v1. A truncated JSON
#          returns the defaults so the next save can overwrite it
def load_profile(path: str | Path) -> Profile:
    text = _read_text(Path(path))
    if text is None:
        return Profile()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return Profile()
    return _profile_from_json(data)


# @args: profile - one profile
# @return: the v2 JSON body of that profile (lists for the rectangles, because
#          JSON has no tuples). Shared by the single-file writer and the named
#          store so a profile exported from either is the same document
def _profile_to_json(profile: Profile) -> dict:
    return {
        "version": PROFILE_VERSION,
        "telescope": {
            "focal_length_mm": profile.telescope.focal_length_mm,
            "aperture_mm": profile.telescope.aperture_mm,
            "slit_length_mm": profile.telescope.slit_length_mm,
        },
        "camera": {
            "model": profile.camera.model,
            "pixel_size_um": profile.camera.pixel_size_um,
            "binning": profile.camera.binning,
        },
        "roi_presets": [
            {"name": preset.name,
             "capture": list(preset.capture),
             "band": list(preset.band)}
            for preset in profile.roi_presets
        ],
    }


# @args: profile - what to save; path - where
# @return: nothing. Writes the v2 shape of ARCHITECTURE 3.2. This is the single
#          profile file: the named store lives in profiles.json (ADR-027)
def save_profile(profile: Profile, path: str | Path) -> None:
    _write_atomic(
        Path(path), json.dumps(_profile_to_json(profile), indent=2, ensure_ascii=False) + "\n"
    )


@dataclass(frozen=True)
class ProfileStore:
    # Every named profile plus the active selection: the content of
    # profiles.json (ADR-027).
    #
    # One file, not one file per profile, because startup needs the list and the
    # active choice in one read, and rename or delete must be one atomic write.
    # It is also the shape nightscribe-scan used, so a user's named profiles
    # migrate as they are.
    #
    # `profiles` keeps insertion order: the UI lists names in the order the user
    # created them, not in an arbitrary order. `active` may name a profile that
    # is missing (a hand-written file): the string is preserved and
    # active_profile() returns None instead of silently choosing another
    # instrument.
    version: int = PROFILES_VERSION
    active: str = ""
    profiles: dict[str, Profile] = field(default_factory=dict)


# @return: the startup store: one profile called "default", active. A fresh
#          install must show a usable profile, not an empty list
def default_profile_store() -> ProfileStore:
    return ProfileStore(active="default", profiles={"default": Profile()})


# @args: name - a profile name typed by the user
# @return: the name without surrounding spaces. Raises ValueError when nothing
#          is left: an unnamed profile could not be selected or deleted
def _clean_profile_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("a profile name cannot be empty")
    return cleaned


# @args: data - anything json.loads returned for profiles.json
# @return: the ProfileStore, or None when the document is not a store at all.
#          It accepts the SolarScribe store, a single Profile document, a map of
#          names with no wrapper, and the nightscribe-scan v1 file; every block
#          goes through _profile_from_json, which migrates v1 bodies
def _store_from_json(data: object) -> ProfileStore | None:
    if not isinstance(data, dict):
        return None

    raw_profiles = data.get("profiles")
    if isinstance(raw_profiles, dict):
        profiles: dict[str, Profile] = {}
        for name, block in raw_profiles.items():
            if not isinstance(name, str):
                continue
            cleaned = name.strip()
            if not cleaned:
                continue
            # A broken body keeps the name with the default values: the name is
            # the user's, the values are ours to repair.
            profiles[cleaned] = _profile_from_json(block)
        return ProfileStore(active=_as_str(data.get("active"), "").strip(),
                            profiles=profiles)

    # A single profile document: the legacy profile.json or an exported profile.
    if any(marker in data for marker in
           ("telescope", "camera", "roi_presets", "meta", "config")):
        return ProfileStore(active="default",
                            profiles={"default": _profile_from_json(data)})

    # A map of profiles with no wrapper, minus the store metadata. This is the
    # shape the prototype's panel could download for one profile set.
    metadata = ("version", "active")
    entries = {name: block for name, block in data.items() if name not in metadata}
    if entries and all(isinstance(block, dict) for block in entries.values()):
        profiles = {}
        for name, block in entries.items():
            cleaned = str(name).strip()
            if cleaned:
                profiles[cleaned] = _profile_from_json(block)
        return ProfileStore(active=_as_str(data.get("active"), "").strip(),
                            profiles=profiles)

    # A flat v1 config passed as a store: one profile called "default".
    if data:
        return ProfileStore(active="default",
                            profiles={"default": _profile_from_json(data)})

    # An explicitly empty document is an empty store. A missing file is the one
    # that gets the startup default; deleting the last profile must stick.
    return ProfileStore(active="", profiles={})


# @args: path - profiles.json; legacy_path - the old single profile.json (None
#        looks for profile.json next to path)
# @return: the named store, loaded at startup. A missing file falls back to the
#          legacy profile as "default", and to the startup default when there is
#          none. A broken file tries the legacy profile first, then the default.
#          Loading never writes: the caller saves when the user changes
#          something (ADR-027)
def load_profiles(path: str | Path, *,
                  legacy_path: str | Path | None = None) -> ProfileStore:
    path = Path(path)
    if legacy_path is None:
        # The startup call is load_profiles(paths.profiles_path()): the old
        # profile.json lives in the same folder, so looking for it here keeps
        # the migration automatic instead of making every caller remember a
        # second path.
        sibling = path.with_name(PROFILE_FILE)
        if sibling != path and sibling.exists():
            legacy_path = sibling
    text = _read_text(path)
    if text is not None:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            data = None
        if data is not None:
            store = _store_from_json(data)
            if store is not None:
                return store

    if legacy_path is not None:
        legacy_text = _read_text(Path(legacy_path))
        if legacy_text is not None:
            try:
                legacy_data = json.loads(legacy_text)
            except (json.JSONDecodeError, ValueError):
                legacy_data = None
            return ProfileStore(active="default",
                                profiles={"default": _profile_from_json(legacy_data)})

    return default_profile_store()


# @args: store - every named profile and the active one; path - where to write
# @return: nothing. One atomic file with the version, the active name and one
#          complete v2 profile body per name, so a profile can be exported from
#          here into a single profile.json without a converter
def save_profiles(store: ProfileStore, path: str | Path) -> None:
    data = {
        "version": PROFILES_VERSION,
        "active": store.active,
        "profiles": {name: _profile_to_json(profile)
                     for name, profile in store.profiles.items()},
    }
    _write_atomic(Path(path), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# @args: store - the named profiles
# @return: the names in file order, which is the order the user created them
def profile_names(store: ProfileStore) -> tuple[str, ...]:
    return tuple(store.profiles)


# @args: store - the named profiles
# @return: the active Profile, or None when the active name is empty or does not
#          exist. None is honest: the caller must not pretend another profile is
#          the active one
def active_profile(store: ProfileStore) -> Profile | None:
    return store.profiles.get(store.active)


# @args: store - the named profiles; name - an existing profile
# @return: a new store with that profile active. Raises KeyError when the name
#          is not there, because a typo must not change the instrument silently
def set_active_profile(store: ProfileStore, name: str) -> ProfileStore:
    cleaned = name.strip()
    if cleaned not in store.profiles:
        raise KeyError(cleaned)
    return ProfileStore(version=store.version, active=cleaned,
                        profiles=dict(store.profiles))


# @args: store - the named profiles; name - the profile to add or replace;
#        profile - its data; make_active - also switch to it
# @return: a new store. The name is trimmed and cannot be empty. Saving a new
#          first profile makes it active, because a store with one profile and
#          no active one has nothing for the UI to show
def save_named_profile(store: ProfileStore, name: str, profile: Profile, *,
                       make_active: bool = False) -> ProfileStore:
    cleaned = _clean_profile_name(name)
    profiles = dict(store.profiles)
    profiles[cleaned] = profile
    active = cleaned if make_active or not store.active else store.active
    return ProfileStore(version=store.version, active=active, profiles=profiles)


# @args: store - the named profiles; old - the current name; new - the new one
# @return: a new store with the same profile under the new name. The active
#          selection follows the rename. Raises KeyError for a missing old name,
#          ValueError for an empty or already used new name
def rename_profile(store: ProfileStore, old: str, new: str) -> ProfileStore:
    old_name = _clean_profile_name(old)
    new_name = _clean_profile_name(new)
    if old_name not in store.profiles:
        raise KeyError(old_name)
    if old_name == new_name:
        return store
    if new_name in store.profiles:
        raise ValueError(f"a profile called {new_name!r} already exists")
    profiles = {}
    for name, profile in store.profiles.items():
        profiles[new_name if name == old_name else name] = profile
    active = new_name if store.active == old_name else store.active
    return ProfileStore(version=store.version, active=active, profiles=profiles)


# @args: store - the named profiles; name - the profile to remove
# @return: a new store without it. Deleting the active profile clears the
#          selection instead of silently activating another instrument; deleting
#          the last one leaves an empty store, which the loader respects
def delete_profile(store: ProfileStore, name: str) -> ProfileStore:
    cleaned = _clean_profile_name(name)
    if cleaned not in store.profiles:
        raise KeyError(cleaned)
    profiles = {key: value for key, value in store.profiles.items()
                if key != cleaned}
    active = "" if store.active == cleaned else store.active
    return ProfileStore(version=store.version, active=active, profiles=profiles)


# @args: raw - the metrics member of a saved step
# @return: the numeric metrics only, as floats. A label or a sentence stored by
#          mistake is dropped: StepState.metrics is numbers, the UI writes the
#          words (ADR-016, ADR-023)
def _as_metrics(raw: object) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    metrics: dict[str, float] = {}
    for name, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        try:
            metrics[str(name)] = float(value)
        except (TypeError, ValueError):
            continue
    return metrics


# @args: path - the session_state.json of a session
# @return: the SessionState, complete for the five steps. A missing file, a
#          missing step, an unknown step or an unknown status all resolve to
#          something the rail can paint (ADR-011)
def load_session_state(path: str | Path) -> SessionState:
    text = _read_text(Path(path))
    data: dict = {}
    if text is not None:
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            parsed = {}
        if isinstance(parsed, dict):
            data = parsed

    steps = new_steps()
    raw_steps = data.get("steps")
    if isinstance(raw_steps, dict):
        for name, raw in raw_steps.items():
            if name not in steps or not isinstance(raw, dict):
                continue
            try:
                status = StepStatus(raw.get("status"))
            except ValueError:
                status = StepStatus.PENDING
            steps[name] = StepState(
                status=status,
                updated_at=_as_str(raw.get("updated_at"), ""),
                metrics=_as_metrics(raw.get("metrics")),
            )
    return SessionState(
        steps=steps,
        session_dir=_as_str(data.get("session_dir"), ""),
        created_at=_as_str(data.get("created_at"), ""),
        updated_at=_as_str(data.get("updated_at"), ""),
    )


# @args: state - the five steps and the session dates; path - where to save
# @return: nothing. Writes the five steps in rail order and drops anything else,
#          so the file has one canonical shape
def save_session_state(state: SessionState, path: str | Path) -> None:
    steps = {}
    for name in SESSION_STEPS:
        step = state.steps.get(name, StepState())
        steps[name] = {
            "status": step.status.value,
            "updated_at": step.updated_at,
            "metrics": dict(step.metrics),
        }
    data = {
        "steps": steps,
        "session_dir": state.session_dir,
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }
    _write_atomic(Path(path), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# The two helpers below are the naming contract of DESIGN.md 10 and the only
# place a layer may learn how a session or a SER is called. They do not create
# the session folder except where the architecture says so.

# @args: base_dir - the INI session_dir, or paths.default_session_base();
#        when - the local time that names the session
# @return: the new session folder, created. A second session inside the same
#          minute gets _2, _3... instead of sharing a folder with the first
def session_folder(base_dir: str | Path, when: datetime) -> Path:
    base = Path(base_dir)
    stamp = when.strftime(SESSION_FOLDER_FORMAT)
    suffix = 1
    while True:
        # mkdir() itself decides the race: asking "does it exist?" and then
        # creating leaves a window where two starts pick the same folder. The
        # loop turns a collision into the next suffix instead of a crash.
        folder = base / stamp if suffix == 1 else base / f"{stamp}_{suffix}"
        try:
            folder.mkdir(parents=True)
            return folder
        except FileExistsError:
            suffix += 1


# @args: session_dir - the session folder; base_name - the INI base_name;
#        when - the scan's local time; scan - the 1-based scan number
# @return: sun_YYYYMMDD_HHMM_scanNN.ser. NN is zero padded so the files sort,
#          and scan 0 is rejected because the numbering starts at 1
def scan_ser_path(session_dir: str | Path, base_name: str, when: datetime,
                  scan: int) -> Path:
    if scan < 1:
        raise ValueError("scan numbering starts at 1")
    prefix = base_name.strip() or "sun"
    stamp = when.strftime(SESSION_FOLDER_FORMAT)
    return Path(session_dir) / f"{prefix}_{stamp}_scan{scan:02d}.ser"


# @args: session_dir - the session folder; configured - the inherited
#        [logging] value; default_name - the fixed file name of the log
# @return: where that log goes. Empty means the session folder. A relative path
#          resolves against the session folder, not the working directory: a
#          launcher can start the app anywhere, and the log must not depend on
#          that (the prototype used the working directory, which is exactly the
#          bug this rule removes)
def _log_path(session_dir: str | Path, configured: str, default_name: str) -> Path:
    if not configured.strip():
        return Path(session_dir) / default_name
    path = Path(configured.strip()).expanduser()
    return path if path.is_absolute() else Path(session_dir) / path


# @args: session_dir - the session folder; configured - logging.scan_log_path
# @return: the CSV of one row per scan (ADR-018)
def scan_log_path(session_dir: str | Path, configured: str = "") -> Path:
    return _log_path(session_dir, configured, SCAN_LOG_FILE)


# @args: session_dir - the session folder; configured - logging.scan_stats_path
# @return: the JSON lines of one sample per scan (ADR-018)
def scan_stats_path(session_dir: str | Path, configured: str = "") -> Path:
    return _log_path(session_dir, configured, SCAN_STATS_FILE)


# @args: session_dir - the session folder; configured - logging.session_meta_path
# @return: the effective configuration and plan of the session (ADR-018)
def session_meta_path(session_dir: str | Path, configured: str = "") -> Path:
    return _log_path(session_dir, configured, SESSION_META_FILE)


# @args: session_dir - the session folder
# @return: the step state of that session (ADR-023; not session_meta.json)
def session_state_path(session_dir: str | Path) -> Path:
    return Path(session_dir) / SESSION_STATE_FILE
