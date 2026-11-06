# Bundled SDK licences and attribution

SolarScribe loads camera SDKs dynamically. Redistribution is a separate legal
question from use, and ADR-017 requires a written verdict per SDK before the
binary travels in an installer. This folder is that record: one file per SDK,
plus this table, plus the machine-readable `../sdk-manifest.json` that the
build reads.

| SDK | Runtime files | Licence | Verdict | Evidence |
| --- | --- | --- | --- | --- |
| ZWO ASI | `ASICamera2.dll`, `libASICamera2.so` | MIT | **bundled** | `license.txt` in both the Windows and the Linux SDK archives, Copyright (c) 2015 ZWO Company |
| Player One | `PlayerOneCamera.dll`, `libPlayerOneCamera.so` | Player One SDK licence (use and redistribute with notice) | **bundled** | `license.txt` in `PlayerOne_Camera_SDK_Linux_V3.10.1.tar.gz` |
| QHYCCD | `qhyccd.dll`, `libqhyccd.so`, QHY firmware | No licence file, no written grant found | **not bundled** | `qhyccdsdk-v2.0.11-Linux-Debian-Ubuntu-x86_64.tar.gz` has no LICENSE or COPYING; the GitHub delivery repository has none |
| ToupTek ToupCam | `toupcam.dll`, `libtoupcam.so`, rebrand libraries | No licence file, no written grant found | **not bundled** | `toupcamsdk.20261024.zip` has no LICENSE or COPYING in any directory |
| ASCOM Platform | not shipped | ASCOM Platform licence | prerequisite | separate installation, not redistributed |
| INDI (`indiserver`) | not shipped | LGPL-2.1-or-later / GPL-2.0-or-later | prerequisite | distribution package, not redistributed |
| .NET runtime | not shipped | MIT | prerequisite | required by the ASCOM Platform on Windows |

## How the gate works

1. `../fetch_deps.py` downloads the vendor archive into `../vendor/raw` after
   the developer confirms they have read this table.
2. `../prepare_vendor.py` reads `../sdk-manifest.json` and copies only the
   SDKs whose `redistributable` value is `true` into `../vendor/bundle/<os>`.
3. The PyInstaller spec, `../build_deb.py` and `../rpm/solarscribe.spec`
   consume that bundle. They never download or decide a licence themselves.

To change a verdict: obtain written permission or a licence file that grants
redistribution, record the evidence in this folder and in `sdk-manifest.json`,
and set `redistributable` to `true`. A developer build can opt in earlier with
`prepare_vendor.py --allow-unreviewed`, but a release must not.

## What the observer sees when an SDK is absent

The application reports the missing backend by name and keeps working with the
simulator and with the SDKs that are present (ADR-014). This is why the
packages install and start even when a vendor SDK is not bundled.
