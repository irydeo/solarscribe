############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - SDK bundle preparation module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""Turn fetched SDK archives into a licence-checked bundle for the installers.

fetch_deps.py downloads vendor archives into installer/vendor/raw. This script
is the second, deliberate step: it reads sdk-manifest.json and copies only the
SDKs whose redistribution verdict is true. An SDK marked false stays out of the
release, and the app degrades gracefully at run time, exactly as ADR-017 says.

The PyInstaller spec, build_deb.py and the RPM spec all consume the same
installer/vendor/bundle/<platform> tree, so there is one place where the legal
decision is enforced instead of three.
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

HEADER = """\
SolarScribe SDK bundle
----------------------
Only SDKs whose redistribution verdict is true are copied below. An SDK whose
licence does not allow redistribution is intentionally absent: the application
says what is missing and keeps working with the other backends.
"""


def _sha256(path):
    # @args: path - file to hash
    # @return: lowercase hex digest
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _matches(rel, pattern):
    # @args: rel - path relative to the search root, pattern - manifest path
    # @return: True when the file is the requested artifact
    # fetch_deps.py writes the selected files flat under raw/<sdk>/<platform>,
    # so the basename fallback covers the normal case; the path fragment still
    # matches a developer tree that kept the vendor layout.
    rel = rel.replace("\\", "/").lower()
    pat = pattern.replace("\\", "/").lower()
    if "/" not in pat:
        return rel.rsplit("/", 1)[-1] == pat
    if "/" not in rel:
        # fetch_deps.py writes the selected files flat under
        # raw/<sdk>/<platform>; the manifest still names the vendor layout.
        return rel == pat.rsplit("/", 1)[-1]
    return rel == pat or rel.endswith("/" + pat)


def _find_artifacts(root, patterns):
    # @args: root - directory to search, patterns - manifest path fragments
    # @return: list of matching Paths (recursive, first match per basename)
    found = []
    seen = set()
    if not root.is_dir():
        return found
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(_matches(rel, pattern) for pattern in patterns):
            if path.name in seen:
                continue
            seen.add(path.name)
            found.append(path)
    return found


def prepare(manifest, platform, raw_dir, out_dir, allow_unreviewed, include):
    # @args: manifest - parsed sdk-manifest.json, platform - windows|linux,
    #        raw_dir - fetched tree, out_dir - bundle destination,
    #        allow_unreviewed - bundle false verdicts (developer only),
    #        include - optional set of SDK names
    # @return: dict written to MANIFEST.json
    out_dir.mkdir(parents=True, exist_ok=True)
    selected = {}
    skipped = []
    for name, info in manifest.get("sdks", {}).items():
        if include and name not in include:
            continue
        if not info.get("redistributable", False) and not allow_unreviewed:
            skipped.append((name, info.get("license", "no verdict")))
            continue
        # fetch_deps.py writes raw/<sdk>/<platform>; an older tree may have the
        # files directly under raw/<sdk>. Prefer the exact platform so a fetch
        # of both OSes in one checkout cannot mix a .dll into a Linux bundle.
        raw = raw_dir / name / platform
        if not raw.is_dir():
            raw = raw_dir / name
        if not raw.is_dir():
            skipped.append((name, "not fetched"))
            continue
        wanted = list(info.get("artifacts", {}).get(platform, []))
        files = _find_artifacts(raw, wanted)
        if not files:
            skipped.append((name, "artifacts not found in the fetched archive"))
            continue
        dest = out_dir / name
        dest.mkdir(parents=True, exist_ok=True)
        entries = []
        for src in files:
            target = dest / src.name
            shutil.copy2(src, target)
            entries.append({
                "file": f"{name}/{target.name}",
                "bytes": target.stat().st_size,
                "sha256": _sha256(target),
            })
        # The vendor's own licence text, when the archive carried one. Our
        # attribution file is in installer/licenses/; this is the notice the
        # licence itself asks to reproduce.
        notice = raw / "VENDOR-LICENSE.txt"
        if notice.is_file():
            shutil.copy2(notice, dest / "VENDOR-LICENSE.txt")
            entries.append({"file": f"{name}/VENDOR-LICENSE.txt",
                            "bytes": (dest / "VENDOR-LICENSE.txt").stat().st_size,
                            "sha256": _sha256(dest / "VENDOR-LICENSE.txt")})
        # QHY firmware is part of the same unsupported redistribution verdict;
        # it travels only when the SDK itself does.
        firmware = info.get("firmware", {}).get(platform)
        if firmware:
            fw_src = raw / firmware
            if not fw_src.is_dir():
                fw_src = raw / "firmware"
            # fetch_deps.py already normalises the vendor folder to
            # firmware/qhy; accept either shape so a hand-made raw tree works.
            if (fw_src / "qhy").is_dir():
                fw_src = fw_src / "qhy"
            if fw_src.is_dir():
                # The package always exposes the firmware at firmware/qhy, the
                # path the QHY udev rule and /lib/firmware/qhy use.
                fw_dest = out_dir / "firmware" / "qhy"
                if fw_dest.exists():
                    shutil.rmtree(fw_dest)
                shutil.copytree(fw_src, fw_dest)
                entries.append({"file": "firmware/qhy/", "bytes": 0,
                                "sha256": ""})
        selected[name] = {
            "vendor": info.get("vendor", ""),
            "license": info.get("license", ""),
            "license_file": info.get("license_file", ""),
            "files": entries,
        }

    result = {
        "schema": 1,
        "platform": platform,
        "license_gate": "allow-unreviewed" if allow_unreviewed else "manifest",
        "selected": selected,
        "skipped": [{"sdk": n, "reason": r} for n, r in skipped],
    }
    (out_dir / "MANIFEST.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (out_dir / "README.txt").write_text(HEADER, encoding="utf-8")
    return result


def main(argv=None):
    # @args: argv - command line arguments (defaults to sys.argv[1:])
    # @return: process exit code
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=["windows", "linux"])
    parser.add_argument("--manifest", default=str(
        Path(__file__).resolve().parent / "sdk-manifest.json"))
    parser.add_argument("--raw-dir", default=str(
        Path(__file__).resolve().parent / "vendor" / "raw"))
    parser.add_argument("--out", default="")
    parser.add_argument("--include", default="",
                        help="comma separated SDK names to include")
    parser.add_argument("--allow-unreviewed", action="store_true",
                        help="bundle SDKs whose verdict is false (development "
                             "builds only; the licence decision is yours)")
    parser.add_argument("--require-something", action="store_true",
                        help="fail when nothing was selected (release gate)")
    args = parser.parse_args(argv)

    here = Path(__file__).resolve().parent
    out = Path(args.out) if args.out else here / "vendor" / "bundle" / args.platform
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    include = {s.strip() for s in args.include.split(",") if s.strip()}
    result = prepare(manifest, args.platform, Path(args.raw_dir), out,
                     args.allow_unreviewed, include)

    print(f"SDK bundle for {args.platform}: {out}")
    for name, info in result["selected"].items():
        count = len(info["files"])
        print(f"  bundled {name}: {count} file(s), {info['license']}")
    for item in result["skipped"]:
        print(f"  skipped {item['sdk']}: {item['reason']}")
    if not result["selected"]:
        print("  no SDK bundled: this build ships without camera backends "
              "beyond the simulator and must degrade gracefully")
    if args.require_something and not result["selected"]:
        print("error: --require-something was given but nothing was selected",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
