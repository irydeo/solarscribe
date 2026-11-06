############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - config paths module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Where SolarScribe keeps its files on each platform (ADR-004, ADR-017,
# ADR-024). platformdirs applies the platform convention for us:
#   - Linux: $XDG_CONFIG_HOME/SolarScribe and $XDG_DATA_HOME/SolarScribe,
#     falling back to ~/.config and ~/.local/share; logs under the XDG state
#     directory.
#   - Windows: %LOCALAPPDATA%\SolarScribe for config and data, the roaming
#     profile is not used because a 4 GB session folder has no place in a
#     roaming folder.
#   - macOS: ~/Library/Application Support/SolarScribe.
#
# The rule this module exists for: nothing is ever written next to the
# executable. On Windows Program Files is read-only for a normal user, and on
# Linux /usr is read-only for everyone, so a config file there would either fail
# to save or demand root. The installer only drops the program; the user's data
# goes to the user's directories.
#
# These functions only resolve paths. They do not create directories: store.py
# creates the parent when it actually writes a file, so importing this module has
# no side effects and a test can ask where a file would live.

from __future__ import annotations

from pathlib import Path

import platformdirs

from solarscribe.config.schema import CONFIG_FILE, PROFILE_FILE

__all__ = [
    "APP_NAME",
    "config_dir",
    "data_dir",
    "default_session_base",
    "log_dir",
    "profile_path",
    "settings_path",
]

# The folder name inside the platform's config, data and log roots. It is the
# application id, so it must not change without a migration: every existing
# user's settings live under it. It is capitalised to match the name the app
# shows and the platform folders of the other SolarScribe tools.
APP_NAME = "SolarScribe"


# @return: the per-platform folder for the small files: the INI and the profile
def config_dir() -> Path:
    # appauthor=False keeps the Linux and macOS paths clean; on Windows it gives
    # %LOCALAPPDATA%\SolarScribe instead of %LOCALAPPDATA%\SolarScribe\SolarScribe.
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


# @return: the per-platform folder for the big files: the session folders
def data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


# @return: the per-platform folder of the application log, outside the session
#          folders: a log that outlives a session is what the Logs viewer reads
#          (DESIGN.md 11)
def log_dir() -> Path:
    return Path(platformdirs.user_log_dir(APP_NAME, appauthor=False))


# @return: where session folders live when the INI does not name a base folder.
#          Sessions are data, not configuration: a scan writes hundreds of MB
#          and must not land in a small config partition or in a backup folder
def default_session_base() -> Path:
    return data_dir() / "sessions"


# @return: the INI the app reads and writes when no other path is given
def settings_path() -> Path:
    return config_dir() / CONFIG_FILE


# @return: the JSON profile the app reads and writes
def profile_path() -> Path:
    return config_dir() / PROFILE_FILE
