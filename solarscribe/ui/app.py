############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui application entry module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# `python -m solarscribe gui` lands here (the __main__ module delegates to run).
#
# One doorway, three modes:
#   - the GUI (default), with the simulator when no device layer is present;
#   - --dry-run and --diagnostics, implemented in cli/ and dispatched here
#     because the package entry point funnels every argument through this
#     function. cli/ depends on ui, not the other way round, so the dispatch is
#     done with importlib and no module-level import: the layer rule of
#     ARCHITECTURE 1 stays intact and the AST test still sees the truth.
#
# The application object is created here and only here. apply_theme() is called
# before any widget is built, because a QSS applied after the first paint
# produces a visible flash of the light default theme.
#
# Language: the INI value, or the system when empty (ADR-016). A missing .qm is
# not an error: the English source strings are shown.

from __future__ import annotations

import importlib
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from solarscribe.config import paths, store
from solarscribe.config.schema import CONFIG_FILE

from .main_window import MainWindow
from .session import Session
from .theme import APP_NAME, apply_theme
from .ui_loader import install_translator

__all__ = ["run"]

# Modes that are not the GUI. Kept as simple strings so the parser does not need
# argparse: the UI owns no options beyond these, and an unknown one is reported.
CLI_MODES = ("--dry-run", "--diagnostics", "--self-test")


# @args: argv - command line arguments, with or without the leading "gui"
# @return: the process exit code
def run(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "gui":
        args = args[1:]

    if "--help" in args or "-h" in args:
        _print_help()
        return 0

    if "--dry-run" in args or "--diagnostics" in args:
        # Delegated to cli without importing it at module level: see the header.
        cli = importlib.import_module("solarscribe.cli")
        return cli.run(args)

    return _run_gui(args)


# @args: args - the GUI arguments (mode removed)
# @return: the process exit code
def _run_gui(args: list[str]) -> int:
    self_test = "--self-test" in args
    demo = "--no-demo" not in args
    language = _argument(args, "--lang", "")
    settings_file = _argument(args, "--settings", "")
    session_folder = _argument(args, "--session", "")

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0] if sys.argv else APP_NAME])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("SolarScribe")
    apply_theme(app)

    temporary = None
    if self_test:
        # A self test must not write into the user's real folders: it uses a
        # throwaway session and INI, opens the window and leaves.
        import tempfile
        temporary = tempfile.TemporaryDirectory(prefix="solarscribe-selftest-")
        root = Path(temporary.name)
        settings_file = settings_file or str(root / CONFIG_FILE)
        session_folder = session_folder or str(root / "session")

    settings_path = Path(settings_file) if settings_file else paths.settings_path()
    profile_path = paths.profile_path()
    log_folder = Path(temporary.name) / "log" if temporary else paths.log_dir()
    _configure_logging(log_folder)
    logger = logging.getLogger("solarscribe")
    logger.info("starting in %s mode", "simulator" if demo else "no-demo")

    settings = store.load_settings(settings_path)
    if not language:
        language = str(settings.get("general", "language") or "")
    install_translator(app, language)

    session = _make_session(settings, settings_path, profile_path,
                            session_folder, demo)
    window = MainWindow(session, show_welcome=None)
    window.show()
    window.start_capture()
    if self_test:
        # One event-loop turn is enough to lay out and paint offscreen; then the
        # window closes and the temporary folder disappears with it.
        QTimer.singleShot(250, window.close)
        QTimer.singleShot(300, app.quit)
        code = app.exec()
        logger.info("self test finished with code %s", code)
        temporary.cleanup()
        return code
    code = app.exec()
    logger.info("exited with code %s", code)
    return code


# @args: folder - where the rolling log lives (the temp folder in a self test)
# @return: none. Installs one handler, so importing the app twice does not
#          duplicate every line
def _configure_logging(folder: Path) -> None:
    logger = logging.getLogger("solarscribe")
    if getattr(logger, "_solarscribe_handler", None) is not None:
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(folder / "solarscribe.log",
                                      maxBytes=2_000_000, backupCount=3,
                                      encoding="utf-8")
    except OSError:
        # A read-only log folder must not stop the app; the rest still works.
        return
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger._solarscribe_handler = handler  # noqa: SLF001 - one handler marker


# @args: settings - the Settings; settings_path, profile_path - where they live
#        folder - a session folder or ""
#        demo - whether to build the simulator
# @return: the Session the window paints
def _make_session(settings, settings_path: Path, profile_path: Path,
                  folder: str, demo: bool) -> Session:
    profile = store.load_profile(profile_path)
    kwargs = dict(settings=settings, profile=profile, demo=demo,
                  autosave=True, settings_path=settings_path,
                  profile_path=profile_path)
    if folder:
        target = Path(folder)
        if store.session_state_path(target).is_file():
            return Session.load(target, **kwargs)
        return Session(folder=target, **kwargs)
    return Session(**kwargs)


# @args: args - the argument list; name - the option; default - the fallback
# @return: the value after the option, or the default
def _argument(args: list[str], name: str, default: str) -> str:
    if name in args:
        index = args.index(name)
        if index + 1 < len(args):
            return args[index + 1]
    # Also accept --name=value, the form a desktop file tends to use.
    for item in args:
        if item.startswith(name + "="):
            return item.split("=", 1)[1]
    return default


# @args: none
def _print_help() -> None:
    print("SolarScribe: capture for the solar spectroheliograph")
    print("")
    print("Usage:")
    print("  python -m solarscribe gui [--demo|--no-demo] [--session DIR]")
    print("  python -m solarscribe --dry-run [--session DIR]")
    print("  python -m solarscribe --diagnostics")
    print("  python -m solarscribe gui --self-test")
    print("")
    print("  --demo        run the simulator when no camera is present (default)")
    print("  --no-demo     start with no camera and no simulated frames")
    print("  --session     session folder to open or create")
    print("  --settings    INI file to read and write")
    print("  --lang es|en  force a language instead of the system one")
