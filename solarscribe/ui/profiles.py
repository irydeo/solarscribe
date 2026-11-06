############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui profiles module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The adapter between the named-profile UI and config.store (ADR-027).
#
# ADR-027 gives the store an explicit, pure API: load_profiles/save_profiles
# read and write one profiles.json; profile_names, active_profile,
# set_active_profile, save_named_profile, rename_profile and delete_profile
# return a new ProfileStore and never touch the disk. This class is the only
# place that holds that in-memory store and decides when to call
# save_profiles, so the window, the profile bar and the manager dialog do not
# know the file format.
#
# The fallback is for a build without the named store: one "default" profile
# backed by the old single load_profile/save_profile. It never invents names and
# never pretends a save worked.

from __future__ import annotations

from pathlib import Path

from solarscribe.config import paths, store
from solarscribe.config.schema import Profile

__all__ = ["ProfileAdapter", "ProfileStoreError"]


class ProfileStoreError(Exception):
    # @args: reason - a stable code the UI turns into a sentence
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProfileAdapter:
    # @args: store_module - config.store or a fake with the same API; profiles_path
    #        - profiles.json; legacy_path - the old single profile.json;
    #        fallback_profile - the Profile already loaded by the session
    def __init__(self, store_module=None,
                 profiles_path: str | Path | None = None,
                 legacy_path: str | Path | None = None,
                 fallback_profile: Profile | None = None) -> None:
        self._store = store_module or store
        self._profiles_path = (Path(profiles_path) if profiles_path
                               else paths.profiles_path())
        self._legacy_path = Path(legacy_path) if legacy_path else None
        self._fallback_profile = fallback_profile
        self._state = None
        if self.available:
            self._state = self._store.load_profiles(
                self._profiles_path, legacy_path=self._legacy_path)

    # @args: none
    # @return: whether the store has the named-profile API of ADR-027
    @property
    def available(self) -> bool:
        return all(hasattr(self._store, name) for name in (
            "load_profiles", "save_profiles", "profile_names",
            "set_active_profile", "save_named_profile", "rename_profile",
            "delete_profile"))

    # @args: none
    # @return: the names in creation order, or ("default",) in the fallback
    def names(self) -> tuple[str, ...]:
        if not self.available or self._state is None:
            return ("default",)
        try:
            names = tuple(str(name) for name in
                          self._store.profile_names(self._state))
        except Exception:  # noqa: BLE001 - a broken store must not kill the UI
            return ("default",)
        return names

    # @args: none
    # @return: the active name, or "" when the store has no active profile.
    #          "" is honest: the UI shows "No active profile" instead of
    #          pretending another instrument is selected
    def active(self) -> str:
        if not self.available or self._state is None:
            return "default"
        return str(self._state.active or "")

    # @args: name - a profile name
    # @return: the profile, or None when the name does not exist
    def load(self, name: str) -> Profile | None:
        if self.available and self._state is not None:
            return self._state.profiles.get(name)
        if name != "default":
            raise ProfileStoreError("named_store_missing")
        if self._fallback_profile is not None:
            return self._fallback_profile
        if self._legacy_path is not None:
            return self._store.load_profile(self._legacy_path)
        return None

    # @args: name - the profile to create or replace; profile - its contents
    #        make_active - also select it, as Save as and New from current do
    def save(self, name: str, profile: Profile,
             make_active: bool = False) -> None:
        if self.available and self._state is not None:
            try:
                self._state = self._store.save_named_profile(
                    self._state, name, profile, make_active=make_active)
            except (KeyError, ValueError) as error:
                raise ProfileStoreError("invalid_name") from error
            self._store.save_profiles(self._state, self._profiles_path)
            return
        if name != "default":
            raise ProfileStoreError("named_store_missing")
        if self._legacy_path is None:
            raise ProfileStoreError("no_profile_path")
        self._store.save_profile(profile, self._legacy_path)

    # @args: name - the profile that startup should load next
    def set_active(self, name: str) -> None:
        if self.available and self._state is not None:
            try:
                self._state = self._store.set_active_profile(self._state, name)
            except KeyError as error:
                raise ProfileStoreError("not_found") from error
            self._store.save_profiles(self._state, self._profiles_path)
            return
        if name != "default":
            raise ProfileStoreError("named_store_missing")

    # @args: name - the profile to remove
    def delete(self, name: str) -> None:
        if not self.available or self._state is None:
            raise ProfileStoreError("named_store_missing")
        try:
            self._state = self._store.delete_profile(self._state, name)
        except KeyError as error:
            raise ProfileStoreError("not_found") from error
        self._store.save_profiles(self._state, self._profiles_path)

    # @args: old - the current name; new - the new name
    def rename(self, old: str, new: str) -> None:
        if not self.available or self._state is None:
            raise ProfileStoreError("named_store_missing")
        try:
            self._state = self._store.rename_profile(self._state, old, new)
        except KeyError as error:
            raise ProfileStoreError("not_found") from error
        except ValueError as error:
            raise ProfileStoreError("invalid_name") from error
        self._store.save_profiles(self._state, self._profiles_path)

    # @args: profile - the current profile, to persist without changing the name
    def save_active(self, profile: Profile) -> None:
        name = self.active()
        if name:
            self.save(name, profile, make_active=False)
