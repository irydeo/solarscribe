# Installer

Packaging for Windows 10/11 x64 and Linux. Windows and Linux are functional
from the MVP (ADR-004, ADR-017); a release is not cut until both are green.

## Layout

```
installer/
  solarscribe.spec              PyInstaller onedir build (Windows and Linux)
  solarscribe.iss               Inno Setup installer (Windows, per-user)
  launcher.py                   absolute-import entry script for PyInstaller
  PREREQUISITES.txt             what the observer must install separately
  build_deb.py                  .deb builder (system Python)
  rpm/solarscribe.spec          .rpm spec (system Python)
  io.github.irydeo.solarscribe.desktop
  io.github.irydeo.solarscribe.metainfo.xml
  icons/                        provisional SVG plus generated PNG/ICO
  make-icons.sh / make_ico.py   regenerate the icon set
  sdk-manifest.json             redistribution verdict per SDK
  fetch_deps.py                 download the vendor archives
  fetch-deps.sh / .ps1          thin wrappers around fetch_deps.py
  prepare_vendor.py             enforce sdk-manifest.json, build the bundle
  licenses/                     one attribution file per SDK
  udev/                         USB access rule and optional QHY firmware rule
  install-udev-rules.sh         source/tarball install of the rules
  smoke_test.py                 source or frozen package smoke test
  vendor/                       fetched and approved trees (gitignored)
```

## Build on Linux

```bash
# 1. Python package and tests
python3 -m venv .venv
.venv/bin/pip install ".[dev]"
.venv/bin/python -m pytest tests/unit
.venv/bin/python installer/smoke_test.py --module --gui
.venv/bin/python -m solarscribe gui --self-test

# 2. PyInstaller (used for the smoke test and the portable tree)
.venv/bin/python -m PyInstaller installer/solarscribe.spec --clean --noconfirm
.venv/bin/python installer/smoke_test.py --frozen dist/solarscribe/solarscribe --gui
dist/solarscribe/solarscribe gui --self-test

# 3. .deb and .rpm (add --bundle / --define _with_sdk 1 after a licensed fetch)
.venv/bin/python installer/build_deb.py --version 0.1.0 --out dist
ver=0.1.0
mkdir -p ~/rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
tar czf ~/rpmbuild/SOURCES/solarscribe-$ver.tar.gz \
    --transform "s,^\.,solarscribe-$ver," .
rpmbuild -bb --define "_version $ver" installer/rpm/solarscribe.spec

# 4. udev rules for a source or tarball install
sudo installer/install-udev-rules.sh
```

The `.deb` and `.rpm` use the system Python and the distribution's PySide6,
numpy and platformdirs. Debian 13 and Ubuntu 25.10 are the supported floor for
the `.deb`; Fedora 42 and openSUSE Tumbleweed are the target for the `.rpm`.
Older releases install manually from the wheel.

## Build on Windows

```powershell
py -3.12 -m pip install ".[dev]"
py -3.12 -m pytest tests/unit
py -3.12 installer\smoke_test.py --module --gui
py -3.12 -m solarscribe gui --self-test
py -3.12 -m PyInstaller installer\solarscribe.spec --clean --noconfirm
py -3.12 installer\smoke_test.py --frozen dist\solarscribe\solarscribe.exe --gui
dist\solarscribe\solarscribe.exe gui --self-test

# Inno Setup 6 must be installed and ISCC.exe on PATH (CI uses choco).
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
    /DAppVersion=0.1.0 installer\solarscribe.iss
```

Input: `dist\solarscribe\` (PyInstaller onedir). Output:
`dist\SolarScribeSetup-<version><suffix>.exe`.

## SDK binaries and the licence gate

The vendor SDKs are not committed. The gate is deliberately two steps:

```bash
python installer/fetch_deps.py --platform linux --accept-licences
python installer/prepare_vendor.py --platform linux
```

`fetch_deps.py` reads `sdk-manifest.json`, prints the redistribution verdict of
every selected SDK, and refuses to download without `--accept-licences` (or
`SOLARSCRIBE_ACCEPT_SDK_LICENCES=1`). It records the URL, the SHA-256 and the
file list in `vendor/raw/<sdk>/<os>/SOURCE.json`. Pin the archive with the
`SOLARSCRIBE_*_SDK_URL` and `SOLARSCRIBE_*_SDK_SHA256` environment variables in
CI; the default URLs are the vendors' current public files and can move.

`prepare_vendor.py` copies only the SDKs whose `redistributable` value is true
into `vendor/bundle/<os>`. The PyInstaller spec, `build_deb.py` and the RPM
spec consume that one tree, so the legal decision is enforced once.

Current verdicts (details in `licenses/README.md`):

| SDK | Verdict | Why |
| --- | --- | --- |
| ZWO ASI | bundled | MIT licence file in the SDK archive |
| Player One | bundled | vendor licence grants use and redistribution with notice |
| QHYCCD | not bundled | no licence file and no written grant |
| ToupTek | not bundled | no licence file and no written grant |

QHY firmware is part of the QHY verdict: the QHY udev loader rule is installed
only when the firmware is bundled. The general USB access rule is always
installed. A developer can override the verdict for a local build with
`prepare_vendor.py --allow-unreviewed`; CI never passes that flag.

When an SDK is absent the application reports it by name and keeps working
with the simulator and the SDKs that are present (ADR-014). That is why a
package with no SDKs still installs, starts and passes the smoke test.

## Platform prerequisites

- **Windows**: ASCOM Platform 7 (and the .NET runtime it needs) for the mount.
  It is detected from the registry; the installer explains it when absent.
  The Windows build includes `pywin32`, so the ASCOM COM bridge is present;
  the ASCOM Platform itself is still a separate installation. The camera SDKs
  that may be redistributed are inside the package.
- **Linux**: a running `indiserver` for the mount. The `.deb` recommends
  `indi-bin` and the RPM recommends `indi`; neither is required to install.
  `python3-serial` / `python3-pyserial` is recommended for the direct
  LX200/OnStep fallback. `fxload` is needed only for the QHY firmware loader.

## Platform paths

The application never writes settings or sessions into the install folder.
`config/paths.py` is the single source of truth, built on `platformdirs` with
`APP_NAME = "SolarScribe"` and `appauthor=False`:

| Kind | Windows | Linux |
| --- | --- | --- |
| Config | `%LOCALAPPDATA%\SolarScribe` | `~/.config/SolarScribe` (or `$XDG_CONFIG_HOME/SolarScribe`) |
| Data | `%LOCALAPPDATA%\SolarScribe` | `~/.local/share/SolarScribe` (or `$XDG_DATA_HOME/SolarScribe`) |
| Logs | `%LOCALAPPDATA%\SolarScribe\Logs` | `~/.local/state/SolarScribe/log` (or `$XDG_STATE_HOME/SolarScribe/log`) |
| Sessions (default) | `%LOCALAPPDATA%\SolarScribe\sessions` | `~/.local/share/SolarScribe/sessions` |

The install trees, the current name-based loader compatibility and the intended
`sdk_dir()` search order are recorded in
`design/notes/PACKAGING-PLATFORM-PATHS.md`.

## Versioning

`setuptools-scm` derives the version from the Git tag, so `v0.1.0` becomes
`0.1.0` and an untagged commit becomes a `.dev` version. The installers take
the version as a parameter; CI resolves it once with
`importlib.metadata.version("solarscribe")` from the installed package and
passes the same string to PyInstaller metadata, Inno Setup, the `.deb` and the
RPM.

Packaging records the version in the installed dist-info, the `.deb`
`METADATA`, the RPM dist-info, the installer file name and the application
metadata. `solarscribe.__version__` reads the same dist-info with
`importlib.metadata.version("solarscribe")`, so `solarscribe --version` and
`session_meta.json` report the same string as the installer. The `"0.0.0"`
fallback is used only by a bare source tree that has no dist-info; the CI
`meta` job fails when the installed version is that fallback.

Editable installs keep the version that was recorded when `pip install -e .`
ran. After a new tag, reinstall the editable package (or install a normal
wheel) so the metadata and `--version` move together.

Tag a release with `vMAJOR.MINOR.PATCH`. The CHANGELOG is bilingual
(`CHANGELOG.md` and `CHANGELOG.es.md`); docs owns it, and the release job puts
both files in the GitHub Release body.

## What is verified where

- **Linux, verified here**: the Python files compile, the shell scripts pass
  `shellcheck` and `sh -n`, the udev rules pass `udevadm verify`, the desktop
  entry and AppStream metadata validate, `pip install -e .` works, the
  PyInstaller Linux build and its smoke test run, and `build_deb.py` produces
  a `.deb` whose contents and control fields were inspected with `dpkg-deb`;
  the source, frozen and staged package all pass `gui --self-test` offscreen.
  The unit suite is run in CI; packaging does not add tests to it.
  The fetch and prepare steps were run against the real ZWO, Player One, QHY
  and ToupTek archives: the archive paths, the nested ZWO archives, the
  x86_64 selection and the QHY firmware tree were all exercised.
- **Windows, unverified here**: the Inno Setup script cannot be compiled on
  Linux. The CI job on `windows-latest` compiles it, installs it silently,
  starts the installed `solarscribe.exe --version` and uninstalls it. The
  PyInstaller Windows build and the ASCOM registry probe run only in that job.
- **QHY/ToupTek**: the code paths are written and the licence verdicts are
  recorded, but no hardware was available to run them. The SDKs are not in the
  default bundle.
