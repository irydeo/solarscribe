############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - PyInstaller spec (Windows and Linux onedir builds)
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Build with:  python -m PyInstaller installer/solarscribe.spec --clean --noconfirm
# Output:      dist/solarscribe/   (Linux binary; on Windows: solarscribe.exe)
#
# Bundles the Qt Designer .ui files, the compiled .qm translations, the
# installed package metadata (so the frozen app reports its real version),
# the user documentation, the per-SDK licence notices and, when
# prepare_vendor.py has approved them, the camera SDK binaries under sdk/.
#
# The SDK tree is the same one build_deb.py and the RPM spec consume; the
# licence gate lives in prepare_vendor.py and sdk-manifest.json, never here.

import glob
import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

block_cipher = None
ROOT = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))
IS_WIN = sys.platform.startswith("win")
PLATFORM = "windows" if IS_WIN else "linux"

datas = []
binaries = []

# The package's own data files. The interface is defined in ui/*.ui (ADR-009)
# and the translations are compiled .qm files (ADR-016); neither is a Python
# module, so PyInstaller cannot infer them from the import graph.
for pattern in ("solarscribe/ui/*.ui", "solarscribe/ui/i18n/*.qm",
                "solarscribe/ui/icons/*", "solarscribe/assets/*"):
    for path in glob.glob(os.path.join(ROOT, pattern)):
        sub = os.path.dirname(os.path.relpath(path, ROOT))
        datas.append((path, sub))

# Installed metadata: without it the frozen app falls back to __version__ =
# "0.0.0", which is exactly the value that must not reach session_meta.json.
try:
    datas += copy_metadata("solarscribe")
except Exception:
    pass  # a source tree with no installed metadata: the fallback stays

# Documentation and the build-time notices. The licenses/ folder ships even
# when no SDK does: it is how the observer learns what is missing and why.
for path in glob.glob(os.path.join(ROOT, "docs", "**", "*.md"), recursive=True):
    sub = os.path.dirname(os.path.relpath(path, ROOT))
    datas.append((path, sub))
for path in glob.glob(os.path.join(ROOT, "installer", "licenses", "*")):
    datas.append((path, os.path.join("licenses")))
_manifest = os.path.join(ROOT, "installer", "sdk-manifest.json")
if os.path.isfile(_manifest):
    datas.append((_manifest, os.path.join("licenses")))
_prereq = os.path.join(ROOT, "installer", "PREREQUISITES.txt")
if os.path.isfile(_prereq):
    datas.append((_prereq, "."))

# Approved SDK bundle. prepare_vendor.py writes this tree only when the
# manifest says redistribution is allowed (or a developer knowingly passed
# --allow-unreviewed). Copying a whole vendor folder keeps sibling DLLs/SOs
# together, which is what ctypes needs on both platforms.
_bundle = os.path.join(ROOT, "installer", "vendor", "bundle", PLATFORM)
if os.path.isdir(_bundle):
    for sdk_dir in sorted(glob.glob(os.path.join(_bundle, "*"))):
        if not os.path.isdir(sdk_dir) or os.path.basename(sdk_dir) == "firmware":
            continue
        sdk = os.path.basename(sdk_dir)
        for path in glob.glob(os.path.join(sdk_dir, "*")):
            if not os.path.isfile(path):
                continue
            base = os.path.basename(path).lower()
            if base.endswith((".dll", ".so", ".dylib")) or ".so." in base:
                binaries.append((path, os.path.join("sdk", sdk)))
            else:
                datas.append((path, os.path.join("sdk", sdk)))
    _bundle_manifest = os.path.join(_bundle, "MANIFEST.json")
    if os.path.isfile(_bundle_manifest):
        datas.append((_bundle_manifest, os.path.join("licenses")))
    _fw = os.path.join(_bundle, "firmware")
    if os.path.isdir(_fw):
        for path in glob.glob(os.path.join(_fw, "**", "*"), recursive=True):
            if os.path.isfile(path):
                sub = os.path.join("firmware",
                                   os.path.dirname(os.path.relpath(path, _fw)))
                datas.append((path, sub))

# Qt modules that are imported lazily or only through the .ui loader. Naming
# them keeps a future refactor from silently dropping the file dialog, the
# SVG icon or the Designer loader from the frozen build.
hiddenimports = [
    "platformdirs",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
    "PySide6.QtUiTools",
]
# Device backends are imported dynamically by the registry (an SDK missing at
# build time must not break the build), so the import graph cannot see them.
# Only names that actually exist today are added; the list grows by itself
# when a backend lands.
for module in (
    "solarscribe.devices.native",
    "solarscribe.devices.native.backend",
    "solarscribe.devices.native.zwo",
    "solarscribe.devices.native.qhy",
    "solarscribe.devices.native.playerone",
    "solarscribe.devices.native.touptek",
    "solarscribe.devices.mount",
    "solarscribe.devices.mount.backend",
    "solarscribe.devices.mount.ascom",
    "solarscribe.devices.mount.indi",
    "solarscribe.devices.mount.lx200",
    "solarscribe.devices.sim",
    "solarscribe.ui.app",
):
    try:
        if importlib.util.find_spec(module) is not None:
            hiddenimports.append(module)
    except (ImportError, ValueError):
        continue

_icon = os.path.join(ROOT, "installer", "icons", "solarscribe.ico")
if not os.path.isfile(_icon):
    _icon = None

a = Analysis(
    [os.path.join(ROOT, "installer", "launcher.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="solarscribe",
    icon=_icon,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # The CLI and the GUI share the binary: `solarscribe gui` opens the GUI,
    # `solarscribe --version` is the smoke test. A console build keeps the CLI
    # usable; the installer starts it with the "gui" argument.
    console=True,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="solarscribe",
)
