# ToupTek ToupCam SDK

- **Vendor**: ToupTek Photonics
- **Files on Windows**: `toupcam.dll`
- **Files on Linux**: `libtoupcam.so` and the rebrand libraries (`libnncam.so`, `libaltaircam.so`, `libogmacam.so`, `libomegonprocam.so`, `libbressercam.so`, `libmallincam.so`, `libmeadecam.so`, `libtscam.so`, `libmicam.so`)
- **Verdict**: **not bundled** by default
- **Reviewed**: 2026-11-06
- **Source**: <https://www.touptekphotonics.com/download/>
- **Archive used for the review**: `toupcamsdk.20261024.zip`

## Why it is not bundled

The SDK archive is proprietary and contains no `LICENSE` or `COPYING` file in
any directory. `toupcam.h` carries no copyright notice either. The vendor
distributes the SDK for development, but the archive grants no redistribution
right, and the default position for software with no written grant is all
rights reserved.

This is the uncomfortable one: the reference camera in DESIGN.md is a ToupTek
G3M678M, so a release without the SDK will not open that camera out of the box.
The application says which SDK is missing and keeps working with the simulator
and any other detected camera. A user who owns the camera can install the
vendor driver or SDK locally, and the dynamic loader will find it.

## What the observer sees

The ToupTek backend is absent from the backend list and the device
diagnostics name the missing SDK. The rest of the application starts and runs
(ADR-014).

## How to enable it after obtaining permission

1. Record the written permission in this file and in `../sdk-manifest.json`.
2. Set `redistributable` to `true`.
3. Run `installer/fetch-deps.sh --platform <os> --sdk toupcam --accept-licences`
   and `installer/prepare_vendor.py --platform <os>`.
4. Rebuild the installers.

A developer can bundle it before the permission is written down with
`prepare_vendor.py --allow-unreviewed`; that flag is deliberately not used by
CI.
