############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - Vendor SDK fetcher module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

"""Download the camera vendor SDKs for a local build and record what arrived.

The SDK archives are not committed: they are large, they change, and their
redistribution terms are not ours to assume. This script fetches them from the
vendor's own download service into installer/vendor/raw, checks the SHA-256
when one is pinned, and leaves a SOURCE.json next to each file. The second
step, prepare_vendor.py, reads sdk-manifest.json and copies only the SDKs whose
licence allows redistribution into the installer bundle.

Why an explicit --accept-licences flag: fetching is a developer action, and the
developer must read the verdict table first. A CI job that wants the SDKs sets
SOLARSCRIBE_ACCEPT_SDK_LICENCES=1 and the pinned SHA-256 values, so the build
is reproducible and the licence decision is visible in the workflow.

Usage:
    python installer/fetch_deps.py --platform linux --accept-licences
    SOLARSCRIBE_ASI_SDK_URL=... python installer/fetch_deps.py --platform windows \
        --sdk asi --accept-licences
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The URLs are overridable on purpose. Vendor download services change their
# query strings and file names without notice, so pinning one URL in code is
# how a build rots silently. The defaults are the current public pages/files;
# CI should set the environment variables and a SHA-256 for a release.
DEFAULT_URLS = {
    "asi": {
        "windows": "https://dl.zwoastro.com/software?app=DeveloperCameraSdk&platform=windows86&region=Overseas",
        "linux": "https://dl.zwoastro.com/software?app=DeveloperCameraSdk&platform=windows86&region=Overseas",
    },
    "qhy": {
        "windows": "",
        "linux": "https://github.com/qhyccd-lzr/QHYCCD_Linux_New/raw/master/qhyccdsdk-v2.0.11-Linux-Debian-Ubuntu-x86_64.tar.gz",
    },
    "playerone": {
        "windows": "https://player-one-astronomy.com/download/softwares/PlayerOne_Camera_SDK_Windows_V3.10.1.zip",
        "linux": "https://player-one-astronomy.com/download/softwares/PlayerOne_Camera_SDK_Linux_V3.10.1.tar.gz",
    },
    "toupcam": {
        "windows": "https://www.touptekphotonics.com/downloads/beta/toupcamsdk.20261024.zip",
        "linux": "https://www.touptekphotonics.com/downloads/beta/toupcamsdk.20261024.zip",
    },
}

ENV_URL = {
    "asi": "SOLARSCRIBE_ASI_SDK_URL",
    "qhy": "SOLARSCRIBE_QHY_SDK_URL",
    "playerone": "SOLARSCRIBE_PLAYERONE_SDK_URL",
    "toupcam": "SOLARSCRIBE_TOUPCAM_SDK_URL",
}
ENV_SHA = {
    "asi": "SOLARSCRIBE_ASI_SDK_SHA256",
    "qhy": "SOLARSCRIBE_QHY_SDK_SHA256",
    "playerone": "SOLARSCRIBE_PLAYERONE_SDK_SHA256",
    "toupcam": "SOLARSCRIBE_TOUPCAM_SDK_SHA256",
}


def _sha256(path):
    # @args: path - file to hash
    # @return: lowercase hex digest
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url, dest):
    # @args: url - HTTP(S) source, dest - Path to write
    # @return: None
    # A browser user agent matters: some vendor CDNs answer 403 to urllib.
    req = urllib.request.Request(url, headers={"User-Agent": "SolarScribe-fetch-deps/1"})
    with urllib.request.urlopen(req, timeout=120) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)


def _archive_suffix(url):
    # @args: url - download URL, possibly with a query string
    # @return: the suffix to give the downloaded file ("" when unknown)
    path = url.split("?", 1)[0].lower()
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2",
                   ".txz", ".zip", ".tar"):
        if path.endswith(suffix):
            return suffix
    return ""


def _extract_one(archive, dest):
    # @args: archive - Path to a zip/tar archive, dest - extraction directory
    # @return: True when the file was recognised, False otherwise
    name = archive.name.lower()
    # A server that answers with Content-Disposition can still give the
    # downloaded file no useful name; sniff the first bytes as a fallback.
    try:
        with archive.open("rb") as fh:
            magic = fh.read(6)
    except OSError:
        magic = b""
    is_zip = name.endswith(".zip") or magic.startswith(b"PK")
    is_tar = name.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                            ".tar.xz", ".txz", ".tar")) or magic.startswith(
                                (b"\x1f\x8b", b"BZh", b"\xfd7zXZ"))
    if is_zip:
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
        return True
    if is_tar:
        with tarfile.open(archive) as t:
            # The vendor archives are flat enough; refuse absolute paths and
            # parent traversal rather than let a tarball write outside dest.
            members = []
            for m in t.getmembers():
                target = (dest / m.name).resolve()
                if dest.resolve() not in target.parents and target != dest.resolve():
                    raise RuntimeError(f"unsafe path in {archive}: {m.name}")
                members.append(m)
            t.extractall(dest, members=members)
        return True
    return False


def _deep_extract(root, depth=3):
    # @args: root - directory already extracted, depth - nested archive limit
    # @return: None
    # ZWO ships the Windows zip and the Linux tar inside one outer zip, so the
    # artifacts are one level deeper than a naive extractor expects.
    if depth <= 0:
        return
    for path in list(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in (".zip", ".gz", ".bz2", ".xz", ".tgz", ".tbz2", ".txz", ".tar"):
            target = path.parent / (path.name + ".extracted")
            target.mkdir(exist_ok=True)
            try:
                if _extract_one(path, target):
                    _deep_extract(target, depth - 1)
            except (zipfile.BadZipFile, tarfile.TarError):
                continue


def _matches(rel, pattern):
    # @args: rel - path relative to the extraction root, pattern - manifest path
    # @return: True when the file is the requested artifact
    # The manifest carries a path fragment such as "lib/x64/libASICamera2.so"
    # so an archive with several architectures cannot contribute the wrong one.
    # A bare file name is still accepted for SDKs whose layout is unknown.
    rel = rel.replace("\\", "/").lower()
    pat = pattern.replace("\\", "/").lower()
    if "/" not in pat:
        return rel.rsplit("/", 1)[-1] == pat
    return rel == pat or rel.endswith("/" + pat)


def _copy_artifacts(root, info, platform, out):
    # @args: root - extracted tree, info - manifest entry, platform - win/linux,
    #        out - raw/<sdk>/<platform> destination
    # @return: list of copied file names
    wanted = list(info.get("artifacts", {}).get(platform, []))
    out.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if any(_matches(rel, pattern) for pattern in wanted):
            target = out / path.name
            if target.exists():
                continue  # the same basename from another architecture
            shutil.copy2(path, target)
            copied.append(target.name)
    # Keep the vendor's own licence text next to the binaries: prepare_vendor
    # copies the notice into the package so the attribution travels with it.
    for path in root.rglob("*"):
        if path.is_file() and path.name.lower() in (
                "license.txt", "licence.txt", "license", "licence", "copying"):
            shutil.copy2(path, out / "VENDOR-LICENSE.txt")
            break
    firmware = info.get("firmware", {}).get(platform)
    if firmware:
        # The vendor calls the folder "firmware"; the package always installs
        # it at /lib/firmware/qhy, which is where the QHY udev rule looks.
        for candidate in root.rglob(Path(firmware).name):
            if candidate.is_dir():
                dest = out / "firmware" / "qhy"
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(candidate, dest)
                copied.append("firmware/qhy/")
                break
    return copied


def main(argv=None):
    # @args: argv - command line arguments (defaults to sys.argv[1:])
    # @return: process exit code
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=["windows", "linux"])
    parser.add_argument("--sdk", default="asi,qhy,playerone,toupcam",
                        help="comma separated subset of asi,qhy,playerone,toupcam")
    parser.add_argument("--dest", default=str(HERE / "vendor" / "raw"))
    parser.add_argument("--accept-licences", action="store_true",
                        help="confirm you have read the verdicts below")
    parser.add_argument("--force", action="store_true",
                        help="re-download even when the target exists")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-all", action="store_true",
                        help="fail when a selected SDK could not be fetched")
    args = parser.parse_args(argv)

    manifest = json.loads((HERE / "sdk-manifest.json").read_text(encoding="utf-8"))
    selected = [s.strip() for s in args.sdk.split(",") if s.strip()]
    unknown = [s for s in selected if s not in manifest["sdks"]]
    if unknown:
        print(f"unknown SDK(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    print("SDK redistribution verdicts (installer/sdk-manifest.json):")
    for name in selected:
        info = manifest["sdks"][name]
        verdict = "BUNDLE" if info["redistributable"] else "DO NOT BUNDLE"
        print(f"  {name:10s} {verdict:14s} {info['license']}")
        print(f"             {info['evidence']}")
    print()
    if not args.accept_licences and os.environ.get(
            "SOLARSCRIBE_ACCEPT_SDK_LICENCES") != "1":
        print("Refusing to download without --accept-licences "
              "(or SOLARSCRIBE_ACCEPT_SDK_LICENCES=1).", file=sys.stderr)
        return 2

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    failures = []
    for name in selected:
        info = manifest["sdks"][name]
        url = os.environ.get(ENV_URL[name]) or DEFAULT_URLS[name][args.platform]
        if not url:
            msg = (f"no {args.platform} URL for {name}; download it from "
                   f"{info['homepage']} and place the archive in {dest / name}")
            print(f"  {name}: {msg}")
            failures.append(name)
            continue
        out = dest / name / args.platform
        if out.is_dir() and any(out.iterdir()) and not args.force:
            print(f"  {name}: already present at {out} (use --force to replace)")
            continue
        if args.dry_run:
            print(f"  {name}: would download {url}")
            continue
        print(f"  {name}: downloading {url}")
        tmp = Path(tempfile.mkdtemp(prefix=f"solarscribe-{name}-", dir=dest))
        archive = tmp / ("archive" + _archive_suffix(url))
        try:
            _download(url, archive)
            digest = _sha256(archive)
            expected = os.environ.get(ENV_SHA[name], "").lower()
            if expected and digest != expected:
                raise RuntimeError(
                    f"sha256 mismatch for {name}: expected {expected}, got {digest}")
            extract = tmp / "extract"
            extract.mkdir()
            if not _extract_one(archive, extract):
                raise RuntimeError(f"unsupported archive type for {name}: {url}")
            _deep_extract(extract)
            if out.exists():
                shutil.rmtree(out)
            copied = _copy_artifacts(extract, info, args.platform, out)
            out.mkdir(parents=True, exist_ok=True)
            (out / "SOURCE.json").write_text(json.dumps({
                "sdk": name,
                "platform": args.platform,
                "url": url,
                "sha256": digest,
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "files": copied,
            }, indent=2) + "\n", encoding="utf-8")
            print(f"  {name}: {len(copied)} artifact(s) -> {out}")
            if not copied:
                failures.append(name)
        except Exception as exc:  # one vendor's server must not hide the rest
            print(f"  {name}: FAILED: {exc}", file=sys.stderr)
            failures.append(name)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("Next: python installer/prepare_vendor.py --platform "
          f"{args.platform}")
    if args.require_all and failures:
        print(f"error: could not fetch: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
