# SolarScribe installation guide

**English** · [Español → INSTALACION.md](INSTALACION.md)

This guide covers the supported systems, the prerequisites and the two ways to
get SolarScribe: the packaged installers and a source install.

> **Status (2026-11-06)**: the packaged installers are **planned**, not
> published. The source install works and the main window starts with the
> simulator; real capture with a camera and a mount is not validated yet. The
> installers described in sections 2 and 3 are the agreed shape (ADR-004,
> ADR-017); treat their exact file names and dialogs as provisional.

---

## 1. Before you start

### 1.1 Supported systems

| System | Package | Status |
| --- | --- | --- |
| Windows 10/11 x64 | PyInstaller build wrapped in an Inno Setup installer | Planned (MVP) |
| Debian, Ubuntu and derivatives | `.deb` | Planned (MVP) |
| Fedora, RHEL and derivatives | `.rpm` | Planned (MVP) |
| Any system with Python 3.11 or 3.12 | Source install | Available today |

Both platforms are first-class from the MVP. Linux is not a second thought and
Windows is not an afterthought: a release is not cut until both build and start
(ADR-017).

### 1.2 Hardware

- **Camera**: one of the native backends, ZWO ASI, QHY, Player One or Touptek,
  plus the built-in simulator. The reference camera is a Touptek G3M678M, mono,
  16 bit, with a 3480×248 px reference ROI.
- **Mount**: OnStep in the reference setup. On Windows the path is ASCOM COM; on
  Linux it is INDI against a running `indiserver`.
- **Connection**: USB 3 for the camera. The reference strip produces about
  207 MB/s, which needs a USB 3 link and a disk that sustains at least 250 MB/s.
- **Disk**: budget several GB per scan. The application refuses to start a
  recording below a configurable free-space floor, one gigabyte by default,
  because a full disk in the middle of a scan loses the take.
- **No hardware?** The camera and mount simulators let you install, start and
  rehearse a session without a camera or a mount.

### 1.3 What the installer brings, and what it does not

The camera SDK binaries travel inside the package, because a capture application
that asks the user to hunt for DLLs is not usable out of the box. On Linux the
package also brings the `udev` rules and, for QHY, the firmware.

What it does **not** bring:

- The **ASCOM Platform** on Windows. It is the standard path to the mount and it
  is installed separately, with its .NET runtime.
- An **INDI server** on Linux. You start `indiserver` with the driver for your
  mount, as with any INDI client.
- Python, on the packaged installs. The source install is the only one that needs
  it.

If a piece is missing, SolarScribe says which one and keeps working with the
rest; it does not refuse to start.

---

## 2. Install on Windows (planned, MVP)

1. Download `SolarScribe-x.y.z-win64.exe` from **GitHub Releases**.
2. Run it. The installer is **not code-signed**, so Windows SmartScreen may show
   a warning. Check that the file comes from the project's Releases page, then use
   **More info → Run anyway**. Signing is a release decision (ADR-017), not a
   missing step in your machine.
3. Accept the licence (GPL-3) and choose the folder. The default is under
   `Program Files`.
4. The installer checks the prerequisites and reports what it finds. If the
   ASCOM Platform is absent, the mount will not be available until you install
   it; the camera and the simulator still work.
5. Finish and start SolarScribe from the Start menu.

**Mount prerequisite**: install the **ASCOM Platform** (which brings the .NET
runtime) before the first session. The Python COM bridge is one of the
application's dependencies; the ASCOM driver for your mount is not.

**Camera**: plug the camera into a USB 3 port. The SDK is already inside the
package; no separate SDK download is needed for the four native backends. If
Windows asks for a camera driver, install the vendor's signed driver, which the
SDK package normally includes. If the camera is still not found, see section 9.

---

## 3. Install on Linux (planned, MVP)

### 3.1 Debian, Ubuntu and derivatives

```bash
sudo apt install ./solarscribe_x.y.z_amd64.deb
```

`apt` resolves the runtime dependencies from the distribution. Installing with
`dpkg -i` also works, but then `sudo apt -f install` is needed to finish the
dependencies.

### 3.2 Fedora, RHEL and derivatives

```bash
sudo dnf install ./solarscribe-x.y.z.x86_64.rpm
```

### 3.3 Camera permissions and `udev`

The package installs the `udev` rules that give the logged-in user access to the
supported cameras. If the camera was plugged in before the install, unplug it and
plug it back in, or reload the rules:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

The QHY firmware, when needed, travels with the package as well.

### 3.4 The mount: `indiserver`

Linux uses INDI. Start `indiserver` with the driver for your mount before opening
SolarScribe:

```bash
indiserver -v <your_mount_driver>
```

The exact driver name depends on the mount; it is the same driver you would use
with any other INDI client. If `indiserver` is not running, SolarScribe reports
that the mount backend is unavailable and keeps the camera and the rest of the
session working.

If you prefer a graphical INDI control panel, `kstars`/`ekos` or `indistarter`
can start the server for you; SolarScribe only needs the server.

---

## 4. Install from source (available today)

This is the only path that works before the first release, and the one used for
development.

### 4.1 Requirements

- Python 3.11 or newer; 3.12 is recommended.
- A C-free stack: the application uses pure Python with `ctypes`, so no compiler
  is needed.
- `git`.
- On Linux, the camera `udev` rules and the INDI server, as in section 3. When
  running from source, the rules are not installed by a package; use the script
  that ships with the project or the rules from the camera vendor.
- On Windows, the ASCOM Platform for the mount.

### 4.2 Steps

```bash
git clone https://github.com/irydeo/solarscribe.git
cd solarscribe
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit
.venv/bin/python -m solarscribe --version
```

On Windows the virtual environment lives in `.venv\Scripts` instead of `.venv/bin`:

```powershell
py -3.12 -m venv --system-site-packages .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest tests/unit
.venv\Scripts\python -m solarscribe --version
```

The unit tests need no hardware and no network. They are the fastest way to know
that the install is sane.

### 4.3 Current limitation

`python -m solarscribe --version` works and prints the version of the installed
package; a source tree that was never installed falls back to `0.0.0`.
`python -m solarscribe` opens the main window; with no camera or mount it starts
with the simulator. `python -m solarscribe --diagnostics` prints a report of the
installation and the device layer, and `python -m solarscribe --dry-run` checks
the geometry without opening the camera or moving the mount. Real camera and
mount capture is not validated yet; the simulator is the path that works today.

### 4.4 Translation tooling (developers)

The Qt Linguist tools come with PySide6 inside the virtual environment:

```bash
.venv/bin/pyside6-lupdate --help
.venv/bin/pyside6-lrelease --help
```

The workflow and the catalogue locations are documented in
[the documentation index](../README.md).

---

## 5. First start (planned, MVP)

1. **Language**: the application follows the system language and offers Spanish
   and English. The choice is stored in the settings.
2. **Welcome assistant**: asks for the observatory latitude and longitude, then
   for the telescope and camera data (focal length, aperture, slit length, pixel
   size). The reference values are 714 mm, 80 mm, 7 mm and 2 µm.
3. **Device discovery**: the camera and the mount are searched in the background.
   Discovery talks to the SDKs and can take a second or more; it never blocks the
   window.
4. **Degradation**: a missing camera SDK, ASCOM Platform or `indiserver` produces
   a plain-language message naming what is missing. The rest of the application
   stays usable.
5. **Dry run**: before the first real session, run in dry-run mode: the mount
   moves and the engine measures, but nothing is written to disk. It validates
   the location, the profile, the camera and the mount without risking a take.

The welcome assistant is inline, not a separate modal wizard, and it can be
skipped. Every value it asks for can be changed later in the settings.

---

## 6. Where SolarScribe stores its files

SolarScribe follows the platform conventions through `platformdirs` (ADR-004,
ADR-017, ADR-024). Nothing is written next to the executable: the installer drops
the program, the user's data goes to the user's directories.

| Content | Windows | Linux |
| --- | --- | --- |
| Settings (`config.ini`) and profile (`profile.json`) | `%LOCALAPPDATA%\SolarScribe\` | `~/.config/SolarScribe/` |
| Session folders, SER files and logs | `%LOCALAPPDATA%\SolarScribe\sessions\` by default, configurable | `~/.local/share/SolarScribe/sessions/` by default, configurable |

The session base folder is configurable in the settings. Windows uses
`%LOCALAPPDATA%` rather than the roaming profile on purpose: a session folder of
several gigabytes has no place in a roaming profile.

The session folder is created per session and named with its date and time. The
files inside follow the `sun_YYYYMMDD_HHMM_scanNN` pattern.

**Important**: the session folder is **yours**. The application never deletes a
SER or a log. Uninstalling the program does not remove your captures, so copy
them out before removing the data folder by hand.

---

## 7. Verify the installation

| Check | How | What good looks like |
| --- | --- | --- |
| The program starts | Launch it from the menu or with `python -m solarscribe` | The main window opens with the simulator; `--self-test` does the same offscreen and exits |
| Version | `python -m solarscribe --version` | Prints the version, `0.0.0` from a plain source tree |
| Unit tests | `python -m pytest tests/unit` | All green, no hardware needed |
| Dry run | `python -m solarscribe --dry-run` | Prints the optics, the ROI and the geometry, and ends with "the dry run is valid" |
| Camera found | Device discovery in the application | The camera appears with its backend and serial |
| Mount found | Telescope panel, connect | RA/Dec and status update, buttons move the mount |
| Language | Settings, language selector | The interface switches between Spanish and English |
| Performance | Health panel during a dry run | FPS, drops, queue and disk rate close to the budget for the chosen ROI |
| Translation state | `pyside6-lupdate` and `pyside6-lrelease` on the catalogues | 0 unfinished strings in both languages |

Rows marked as planned cannot pass until the corresponding feature exists. The
unit tests and the version check do work today.

---

## 8. Updating and uninstalling

### Windows

- **Update**: run the newer installer over the installed version. The settings
  and the captures are kept.
- **Uninstall**: Settings → Apps → Installed apps → SolarScribe → Uninstall. The
  captures and the settings are not removed; delete them by hand if you want a
  clean machine.

### Linux

- **Update**: `sudo apt install ./solarscribe_x.y.z_amd64.deb` or
  `sudo dnf upgrade ./solarscribe-x.y.z.x86_64.rpm`, depending on the
  distribution.
- **Uninstall**: `sudo apt remove solarscribe` or `sudo dnf remove solarscribe`.
  The configuration and the captures stay in your home folder.

### Source

```bash
git pull
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit
```

The `.venv` is self-contained; removing the folder removes the development
install.

---

## 9. Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| The camera is not listed | Missing SDK, USB problem or `udev` rules not loaded | Check the USB 3 port and the cable; on Linux replug the camera or reload the rules; run the device diagnostics when it lands (phase 2) |
| The camera is listed but gives no frames | USB bandwidth or another program holding the camera | Close other capture software, try another port, lower the rate or the ROI |
| The mount is not available on Windows | ASCOM Platform or the mount driver is missing | Install the ASCOM Platform and the vendor's ASCOM driver; check that the driver bit width matches |
| The mount is not available on Linux | `indiserver` is not running or the driver is wrong | Start `indiserver` with the mount driver and confirm it is listening |
| The mount connects but does not move | The driver reports no rate support, or the mount is parked | Unpark, check the rate selector, try a small move with the telescope panel |
| The application starts but no window appears from source | `solarscribe.ui.app` does not exist yet | Expected at this stage; use the version and the unit tests to validate the install |
| SmartScreen blocks the Windows installer | The installer is not code-signed | Check the Releases page and use **More info → Run anyway** |
| A scan refuses to start for lack of disk | The free-space floor (1 GB by default) was hit | Free space or point the session folder at another disk |
| The interface stays in English on a Spanish system | The language setting is forced, or the `.qm` is missing | Set the language in the settings; developers rebuild the catalogues |
| A profile written by hand stops the start | A syntax error or an unknown version | The app should fall back to defaults; if it does not, that is a bug, report it with the file |

---

## 10. Prerequisites at a glance

| Requirement | Windows | Linux |
| --- | --- | --- |
| Operating system | Windows 10/11 x64 | Debian/Ubuntu or Fedora/RHEL, 64-bit |
| Python for the packaged install | Not needed | Not needed |
| Python for the source install | 3.11+ (3.12 recommended) | 3.11+ (3.12 recommended) |
| Camera SDKs | Bundled | Bundled |
| Camera permissions | USB driver from the SDK | `udev` rules from the package |
| Mount backend | ASCOM Platform and the vendor driver | `indiserver` and the mount driver |
| Disk | A few GB free per scan; 250 MB/s sustained | Same |
| Network | Not required | Not required |

---

## 11. References

- [User guide](../user-guide/USER_GUIDE.md).
- [Installation ADRs](../../design/adr/README.md): ADR-004 (cross-platform
  packaging), ADR-017 (packaging, CI, versioning and licences), ADR-019 (mount
  control).
- [CHANGELOG](../../CHANGELOG.md).
