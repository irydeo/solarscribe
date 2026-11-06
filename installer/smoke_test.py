############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - Package smoke test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""Smoke test a source install or a frozen build.

It answers the two questions a release gate actually asks:

1. Does the package import, report a version and carry its Qt .ui/.qm data?
2. Does the GUI start (offscreen) and stay alive, rather than crash on the
   first missing plugin or translation?

Run it after `pip install .` (CI) or against dist/solarscribe/solarscribe
(--frozen). The GUI step is opt-in with --gui because this repository may be
between the skeleton and the first ui/app.py; a missing GUI module is reported
loudly and is not mistaken for a crash. A release build must pass --gui.
"""

import argparse
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path


def _run(cmd, timeout=60):
    # @args: cmd - argument list, timeout - seconds
    # @return: (returncode, stdout+stderr)
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, env=env)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _check_data():
    # @return: list of failure strings
    failures = []
    try:
        from importlib.resources import files
        ui = files("solarscribe.ui")
        uis = list(ui.glob("*.ui"))
        qms = list(ui.glob("i18n/*.qm"))
        for item in uis + qms:
            if item.stat().st_size == 0:
                failures.append(f"empty package data: {item}")
    except Exception as exc:
        failures.append(f"package data not readable: {exc}")
    return failures


def _gui_starts(cmd):
    # @args: cmd - the base command that opens the GUI
    # @return: list of failure strings
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    proc = subprocess.Popen(cmd + ["gui"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env)
    # A GUI that survives ten seconds has built its windows and entered the
    # event loop. It is asked to exit afterwards, so the CI job is not left
    # with a child process holding the runner open.
    deadline = time.time() + 10.0
    while time.time() < deadline and proc.poll() is None:
        time.sleep(0.2)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        return []
    out = (proc.stdout.read() if proc.stdout else "").strip()
    return [f"GUI exited with {proc.returncode}: {out}"]


def main(argv=None):
    # @args: argv - command line arguments (defaults to sys.argv[1:])
    # @return: process exit code
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", default="",
                        help="path to the PyInstaller binary (overrides --module)")
    parser.add_argument("--module", action="store_true",
                        help="test `python -m solarscribe` (default)")
    parser.add_argument("--gui", action="store_true",
                        help="also start the GUI offscreen")
    parser.add_argument("--require-gui", action="store_true",
                        help="fail when solarscribe.ui.app is not present")
    args = parser.parse_args(argv)

    failures = []
    if args.frozen:
        exe = Path(args.frozen)
        if not exe.is_file():
            print(f"FAIL: frozen binary not found: {exe}")
            return 1
        code, out = _run([str(exe), "--version"])
        print(f"frozen --version: rc={code} {out!r}")
        if code != 0 or not out:
            failures.append(f"frozen --version failed: {out}")
        if args.gui:
            failures += _gui_starts([str(exe)])
    else:
        code, out = _run([sys.executable, "-m", "solarscribe", "--version"])
        print(f"module --version: rc={code} {out!r}")
        if code != 0 or not out:
            failures.append(f"python -m solarscribe --version failed: {out}")
        try:
            import solarscribe
            print(f"import solarscribe: {solarscribe.__version__}")
        except Exception as exc:
            failures.append(f"import solarscribe failed: {exc}")
        failures += _check_data()
        if args.gui:
            if importlib.util.find_spec("solarscribe.ui.app") is None:
                msg = ("GUI module solarscribe.ui.app is not present yet: "
                       "the package starts but this build cannot open a window")
                if args.require_gui:
                    print(f"FAIL: {msg}")
                    failures.append(msg)
                else:
                    print(f"SKIP: {msg}")
            else:
                failures += _gui_starts([sys.executable, "-m", "solarscribe"])

    if failures:
        for item in failures:
            print(f"FAIL: {item}")
        return 1
    print("smoke test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
