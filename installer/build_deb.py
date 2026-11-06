############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - Debian package builder module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""Build the SolarScribe .deb (Debian and Ubuntu).

The package uses the SYSTEM Python, exactly like NightScribe's builder: it
depends on the distribution's python3, PySide6, numpy and platformdirs, so the
download is a few MB instead of a second Qt and a second interpreter. The price
is the supported floor: Debian 13 and Ubuntu 25.10, the releases that package
PySide6. Older LTS releases are documented as a manual install, not silently
broken.

The SDK binaries come from installer/vendor/bundle/linux, which
prepare_vendor.py fills with the licence-approved set only. When that folder is
absent the package still installs and starts: the app reports the missing
backend and carries on (ADR-014, ADR-017).

Usage:
    python installer/build_deb.py --version 0.1.0 --out dist
    python installer/build_deb.py --version 0.1.0 --bundle installer/vendor/bundle/linux
"""

import argparse
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESKTOP_ID = "io.github.irydeo.solarscribe"
ICON_SIZES = (16, 32, 48, 64, 128, 256)

# The Qt modules the app imports are split into binary packages on Debian.
DEPENDS = [
    "python3 (>= 3.11)",
    "python3-numpy",
    "python3-platformdirs",
    "python3-pyside6.qtcore",
    "python3-pyside6.qtgui",
    "python3-pyside6.qtwidgets",
    "python3-pyside6.qtuitools",
    "python3-pyside6.qtsvg",
]
# The mount backend is external on purpose (ADR-019): the app degrades to the
# simulator without a running indiserver. fxload is what the QHY firmware rule
# calls; it is harmless when there is no QHY camera.
RECOMMENDS = ["indi-bin", "fxload"]


def _write(path, text, mode=None):
    # @args: path - Path, text - contents, mode - chmod or None
    # @return: None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)


def _dist_info(version):
    # @return: the METADATA text of solarscribe-<version>.dist-info
    return "\n".join([
        "Metadata-Version: 2.1",
        "Name: solarscribe",
        f"Version: {version}",
        "Summary: Capture application for a solar spectroheliograph (SHG)",
        "License: GPL-3.0-only",
        "Home-page: https://github.com/irydeo/solarscribe",
        "",
    ])


def _copyright(manifest, bundled_names):
    # @args: manifest - parsed sdk-manifest.json, bundled_names - SDK dirs
    #        actually present in the package
    # @return: the Debian copyright text
    lines = [
        "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/",
        "Upstream-Name: SolarScribe",
        "Source: https://github.com/irydeo/solarscribe",
        "",
        "Files: *",
        "Copyright: 2026 Francisco Jose Calvo Fernandez (Irydeo Observatory, MPC Z41)",
        "License: GPL-3.0-only",
        " This program is free software: you can redistribute it and/or modify it",
        " under the terms of the GNU General Public License as published by the Free",
        " Software Foundation, version 3.",
        " .",
        ' On Debian systems, the complete text of the GNU General Public License',
        ' version 3 can be found in "/usr/share/common-licenses/GPL-3".',
        "",
    ]
    not_bundled = []
    for name, info in manifest.get("sdks", {}).items():
        if name not in bundled_names:
            not_bundled.append(name)
            continue
        lines += [
            f"Files: usr/lib/solarscribe/sdk/{name}/*",
            f"Copyright: {info.get('vendor', name)}",
            f"License: {info.get('license', 'see the vendor terms')}",
            f" Redistribution verdict: bundled ({info.get('reviewed', '')}).",
            f" Evidence: {info.get('evidence', '')}",
            "",
        ]
        if info.get("firmware"):
            lines += [
                "Files: lib/firmware/qhy/*",
                f"Copyright: {info.get('vendor', name)}",
                f"License: {info.get('license', 'see the vendor terms')}",
                " These files travel with the SDK and are covered by the same",
                " redistribution verdict.",
                "",
            ]
    if not_bundled:
        lines += [
            "Files: *",
            "Comment:",
            " The following camera SDKs are NOT distributed with this package: "
            + ", ".join(not_bundled) + ".",
            " Two of them have no redistribution grant; the others were simply not",
            " fetched for this build. The application reports them as missing and",
            " keeps working (ADR-014).",
            "",
        ]
    return "\n".join(lines)


def _control(version, arch, installed_size_kb):
    # @args: version - package version, arch - Debian architecture,
    #        installed_size_kb - staged size in KiB
    # @return: the DEBIAN/control text
    return "\n".join([
        "Package: solarscribe",
        f"Version: {version}",
        "Section: science",
        "Priority: optional",
        f"Architecture: {arch}",
        "Maintainer: Francisco Jose Calvo Fernandez "
        "<irydeo@users.noreply.github.com>",
        "Homepage: https://github.com/irydeo/solarscribe",
        "Description: Capture application for a solar spectroheliograph (SHG)",
        " SolarScribe opens the camera and the mount, measures live and runs the",
        " SHG scan, and leaves the SER files and logs ready for post-processing.",
        " The mount is ASCOM COM on Windows and INDI on Linux; the camera is a",
        " vendor SDK loaded dynamically. A missing SDK or mount server is reported",
        " and the application keeps working with what is present.",
        f"Depends: {', '.join(DEPENDS)}",
        f"Recommends: {', '.join(RECOMMENDS)}",
        f"Installed-Size: {installed_size_kb}",
        "",
    ])


def _wrapper():
    # @return: the /usr/bin/solarscribe launcher
    # The current native loader asks ctypes for the bare library name, so the
    # private SDK folder must be on the dynamic loader path. The loop adds
    # each vendor dir without touching the rest of the environment; a future
    # config/paths.py:sdk_dir() can drop this, but the package has to work with
    # the loader that shipped.
    return "\n".join([
        "#!/bin/sh",
        "# SolarScribe launcher: the .deb uses the system Python and the",
        "# distribution's PySide6 (see DEBIAN/control).",
        "SDK_ROOT=/usr/lib/solarscribe/sdk",
        "if [ -d \"$SDK_ROOT\" ]; then",
        "    for d in \"$SDK_ROOT\"/*; do",
        "        [ -d \"$d\" ] || continue",
        "        LD_LIBRARY_PATH=\"$d${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\"",
        "    done",
        "    export LD_LIBRARY_PATH",
        "fi",
        "exec python3 -m solarscribe \"$@\"",
        "",
    ])


def _maintainer_scripts(stage):
    # @args: stage - the staged package root
    # @return: None
    # udev reads /usr/lib/udev/rules.d at boot and on reload. The postinst
    # trigger is what makes a freshly installed package see the camera without
    # a reboot; both scripts are no-ops on a system without udevadm.
    for name in ("postinst", "postrm"):
        body = ["#!/bin/sh", "set -e"]
        if name == "postinst":
            # The mount backend is external (ADR-019). Say it at install time
            # instead of letting the first session discover it.
            body += [
                "if ! command -v indiserver >/dev/null 2>&1; then",
                "    echo \"SolarScribe: indiserver is not installed; the mount \" \\",
                "         \"backend will report it as missing. Install indi-bin \" \\",
                "         \"to use INDI.\" >&2",
                "fi",
            ]
        body += [
            "if command -v udevadm >/dev/null 2>&1; then",
            "    udevadm control --reload-rules || true",
            "    udevadm trigger --subsystem-match=usb || true",
            "fi",
            "exit 0",
            "",
        ]
        _write(stage / "DEBIAN" / name, "\n".join(body), mode=0o755)


def _stage(version, bundle, arch, manifest):
    # @args: version, bundle - approved SDK tree or None, arch, manifest
    # @return: the staged tree Path
    stage = Path(tempfile.mkdtemp(prefix="solarscribe-deb-"))
    sitelib = stage / "usr" / "lib" / "python3" / "dist-packages"
    shutil.copytree(ROOT / "solarscribe", sitelib / "solarscribe",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.ts"))
    _write(sitelib / f"solarscribe-{version}.dist-info" / "METADATA",
           _dist_info(version))
    _write(stage / "usr" / "share" / "solarscribe" / "version",
           version + "\n")
    _write(stage / "usr" / "bin" / "solarscribe", _wrapper(), mode=0o755)

    shutil.copy2(ROOT / "installer" / f"{DESKTOP_ID}.desktop",
                 _mk(stage / "usr" / "share" / "applications" / f"{DESKTOP_ID}.desktop"))
    shutil.copy2(ROOT / "installer" / f"{DESKTOP_ID}.metainfo.xml",
                 _mk(stage / "usr" / "share" / "metainfo" / f"{DESKTOP_ID}.metainfo.xml"))
    for size in ICON_SIZES:
        src = ROOT / "installer" / "icons" / f"solarscribe-{size}.png"
        if src.is_file():
            dst = (stage / "usr" / "share" / "icons" / "hicolor"
                   / f"{size}x{size}" / "apps" / "solarscribe.png")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # Documentation and the per-SDK notices. The notices ship even when the
    # SDK does not: they explain what the observer has to install.
    doc = stage / "usr" / "share" / "doc" / "solarscribe"
    doc.mkdir(parents=True, exist_ok=True)
    with gzip.open(doc / "changelog.gz", "wt", encoding="utf-8") as fh:
        fh.write(
            f"solarscribe ({version}) unstable; urgency=medium\n\n"
            f"  * Package build {version}.\n\n"
            f" -- Francisco Jose Calvo Fernandez "
            f"<irydeo@users.noreply.github.com>  "
            f"{time.strftime('%a, %d %b %Y %H:%M:%S %z')}\n")
    for src in sorted((ROOT / "docs").rglob("*.md")):
        rel = src.relative_to(ROOT / "docs")
        shutil.copy2(src, _mk(doc / "guide" / rel))
    shutil.copytree(ROOT / "installer" / "licenses",
                    doc / "sdk-licenses")
    shutil.copy2(ROOT / "installer" / "sdk-manifest.json",
                 doc / "sdk-licenses" / "sdk-manifest.json")
    shutil.copy2(ROOT / "installer" / "PREREQUISITES.txt",
                 doc / "PREREQUISITES.txt")
    shutil.copy2(ROOT / "LICENSE", doc / "LICENSE")

    # udev rules are small and always useful; the QHY firmware rule only goes
    # in when the firmware itself does, otherwise udev would call fxload on a
    # file that is not there.
    rules = stage / "usr" / "lib" / "udev" / "rules.d"
    shutil.copy2(ROOT / "installer" / "udev" / "99-solarscribe-cameras.rules",
                 _mk(rules / "99-solarscribe-cameras.rules"))

    bundled = set()
    if bundle and Path(bundle).is_dir():
        # The bundle manifest records the exact files and hashes that were
        # approved; ship it with the notices for an auditable package.
        bm = Path(bundle) / "MANIFEST.json"
        if bm.is_file():
            shutil.copy2(bm, doc / "sdk-licenses" / "bundle-MANIFEST.json")
        sdk_dst = stage / "usr" / "lib" / "solarscribe" / "sdk"
        for sdk_dir in sorted(Path(bundle).iterdir()):
            if sdk_dir.is_dir() and sdk_dir.name != "firmware":
                shutil.copytree(sdk_dir, sdk_dst / sdk_dir.name)
                bundled.add(sdk_dir.name)
        fw = Path(bundle) / "firmware" / "qhy"
        if fw.is_dir():
            shutil.copytree(fw, stage / "lib" / "firmware" / "qhy")
            shutil.copy2(ROOT / "installer" / "udev" / "85-solarscribe-qhy.rules",
                         _mk(rules / "85-solarscribe-qhy.rules"))
            bundled.add("qhy")

    # The copyright names only the SDKs this package actually carries; the
    # manifest's verdict is a permission, not a promise that the files were
    # fetched for this build.
    _write(doc / "copyright", _copyright(manifest, bundled))

    _maintainer_scripts(stage)
    size_kb = sum(f.stat().st_size for f in stage.rglob("*") if f.is_file()) // 1024
    _write(stage / "DEBIAN" / "control",
           _control(version, arch, size_kb))
    return stage


def _mk(path):
    # @args: path - Path
    # @return: the path, with its parent created
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build(version, out_dir, arch="amd64", bundle=None):
    # @args: version - package version, out_dir - where the .deb lands,
    #        arch - Debian architecture, bundle - approved SDK tree or None
    # @return: the .deb Path
    manifest = json.loads(
        (ROOT / "installer" / "sdk-manifest.json").read_text(encoding="utf-8"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stage = _stage(version, bundle, arch, manifest)
    try:
        deb = out_dir / f"solarscribe_{version}_{arch}.deb"
        subprocess.run(["dpkg-deb", "--build", "--root-owner-group",
                        str(stage), str(deb)], check=True)
        return deb
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main(argv=None):
    # @args: argv - command line arguments (defaults to sys.argv[1:])
    # @return: process exit code
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--arch", default="amd64")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument("--bundle", default="",
                        help="approved SDK tree (installer/vendor/bundle/linux)")
    args = parser.parse_args(argv)
    if shutil.which("dpkg-deb") is None:
        print("dpkg-deb is required (install dpkg-dev)", file=sys.stderr)
        return 2
    deb = build(args.version, args.out, arch=args.arch,
                bundle=args.bundle or None)
    print(f"built {deb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
