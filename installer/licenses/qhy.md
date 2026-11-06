# QHYCCD Camera SDK and firmware

- **Vendor**: QHYCCD
- **Files on Windows**: `qhyccd.dll`
- **Files on Linux**: `libqhyccd.so`, `libqhyccd.so.2`, `libqhyccd.so.2.0.11`
- **Firmware on Linux**: `firmware/qhy/*.HEX`, `firmware/qhy/*.img`
- **Verdict**: **not bundled** by default
- **Reviewed**: 2026-11-06
- **Source**: <https://www.qhyccd.com/download>
- **Linux archive used for the review**: `qhyccdsdk-v2.0.11-Linux-Debian-Ubuntu-x86_64.tar.gz`

## Why it is not bundled

The archive contains `lib/`, `firmware/`, `include/`, `udev/`, samples and
documentation, but no `LICENSE`, `COPYING` or licence text of any kind. The
GitHub delivery repository (`qhyccd-lzr/QHYCCD_Linux_New`) has no licence file
either, and the vendor download page states no redistribution grant. Software
with no written grant is all rights reserved by default, so SolarScribe does
not put these binaries in a release.

The Windows SDK archive was not inspected: the Linux delivery already has no
grant, and one verdict covers both platforms until a review finds a written
licence for each. A future change must inspect both archives and record both.

The QHY udev firmware rule (`85-solarscribe-qhy.rules`) is installed only when
the firmware is present, so a package without QHY support does not leave udev
calling `fxload` on a missing file. The general USB permission rule is always
installed and does not need the vendor SDK.

## What the observer sees

The QHY backend is absent from the backend list and the device diagnostics say
that the QHY SDK is not installed. Every other backend, the simulator and the
whole SHG pipeline keep working (ADR-014).

## How to enable it after obtaining permission

1. Record the written permission in this file and in `../sdk-manifest.json`.
2. Set `redistributable` to `true`.
3. Run `installer/fetch-deps.sh --platform linux --sdk qhy --accept-licences`
   and `installer/prepare_vendor.py --platform linux`.
4. Rebuild the installers. The firmware and the QHY rule will travel with the
   package.

A developer can bundle it before the permission is written down with
`prepare_vendor.py --allow-unreviewed`; that flag is deliberately not used by
CI.
