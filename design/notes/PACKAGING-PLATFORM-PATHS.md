# Packaging: platform paths and SDK layout

Internal note, 2026-11-06. Companion to ADR-004 and ADR-017. It records the
paths the installers create and the paths the application must look in, so
`config/paths.py`, the device loader and the three installers agree. The
`lead` owns `config/paths.py`; this note is the packaging side of that
decision and does not change the application code.

## 1. One source of truth

`config/paths.py` is the only module that decides where a per-user directory
lives. It uses `platformdirs` with `APP_NAME = "SolarScribe"` and
`appauthor=False`. Nothing else in the application hard-codes `%APPDATA%`,
`~/.config`, `/usr/share` or a path under the install folder.

The installers must not create or own the user directories. Uninstalling the
package removes the program, the udev rules and the bundled SDKs; it must not
remove the observer's settings, profiles or sessions.

## 2. Per-user directories

The values below are what the current `config/paths.py` returns. They are
resolved, not created: `store.py` creates the parent when it writes a file, so
importing the module has no side effects.

| Kind | Windows | Linux (XDG) | `config/paths.py` call |
| --- | --- | --- | --- |
| Config | `%LOCALAPPDATA%\SolarScribe` | `$XDG_CONFIG_HOME/SolarScribe`, default `~/.config/SolarScribe` | `config_dir()` |
| Data | `%LOCALAPPDATA%\SolarScribe` | `$XDG_DATA_HOME/SolarScribe`, default `~/.local/share/SolarScribe` | `data_dir()` |
| Logs | `%LOCALAPPDATA%\SolarScribe\Logs` | `$XDG_STATE_HOME/SolarScribe/log`, default `~/.local/state/SolarScribe/log` | `log_dir()` |
| Sessions (default) | `%LOCALAPPDATA%\SolarScribe\sessions` | `~/.local/share/SolarScribe/sessions` | `default_session_base()` |

Notes:

- On Windows both config and data use `%LOCALAPPDATA%`, not the roaming
  `%APPDATA%`. That is deliberate: a session folder is hundreds of MB and has
  no place in a roaming profile. The observer may still point the session base
  at a larger disk from the INI, because DESIGN.md section 10 makes it
  configurable.
- On Linux the XDG variables are honoured when set. A session started from a
  desktop menu and a session started from a terminal must resolve the same
  folder; `platformdirs` gives that for free, a hand-written `~/.config` does
  not.
- There is no `cache_dir()` yet. If one is added it belongs under
  `platformdirs.user_cache_dir(APP_NAME, appauthor=False)`, which is
  `%LOCALAPPDATA%\SolarScribe\Cache` on Windows and `~/.cache/SolarScribe` on
  Linux.
- No path in this table may appear inside the install folder. The Windows
  installer is per-user under `%LOCALAPPDATA%\Programs\SolarScribe`, and a
  future portable build must still read the same per-user directories.

## 3. Install trees

### Windows (Inno Setup, per-user)

```
%LOCALAPPDATA%\Programs\SolarScribe\
  solarscribe.exe
  sdk\              approved camera SDK DLLs, one folder per vendor
  licenses\         one attribution file per SDK plus the README
  docs\             user documentation
  ...               PyInstaller's Qt tree
```

The user needs no administrator rights. The installer runs the previous
uninstaller first, because Inno Setup appends to the old uninstall log and a
PyInstaller onedir tree changes shape between versions.

### Linux (.deb and .rpm, system Python)

```
/usr/bin/solarscribe
/usr/lib/python3/dist-packages/solarscribe/      (Debian)
/usr/lib/python3.X/site-packages/solarscribe/    (RPM)
/usr/lib/solarscribe/sdk/<vendor>/               approved camera SDKs
/lib/firmware/qhy/                               only when QHY is bundled
/usr/lib/udev/rules.d/99-solarscribe-cameras.rules
/usr/lib/udev/rules.d/85-solarscribe-qhy.rules   only with the firmware
/usr/share/applications/io.github.irydeo.solarscribe.desktop
/usr/share/metainfo/io.github.irydeo.solarscribe.metainfo.xml
/usr/share/icons/hicolor/<size>/apps/solarscribe.png
/usr/share/doc/solarscribe/                      copyright, changelog, guide
/usr/share/doc/solarscribe/sdk-licenses/         per-SDK attribution
```

The `.deb` uses `/usr/lib/python3/dist-packages` because that is where the
distribution's `python3` looks. The RPM uses `%{python3_sitelib}`. The code is
the same; only the prefix differs.

## 4. SDK search order

The device layer must load an SDK dynamically and never crash when it is
missing. The installed layout is stable even though the loader may change:

```
Windows: <install>\sdk\<vendor>\*.dll       plus a copy next to solarscribe.exe
Linux:   /usr/lib/solarscribe/sdk/<vendor>/*.so*
```

Each vendor gets its own subfolder: `asi`, `qhy`, `playerone`, `toupcam`. The
approved set is the one `prepare_vendor.py` copied; a vendor folder that is not
there means that backend is absent, not broken.

### Current loader (name based)

`solarscribe/devices/native/loader.py` asks `ctypes` for the bare library name
(`libASICamera2.so`, `ASICamera2.dll`) and then falls back to
`ctypes.util.find_library`. It does not consult `config/paths.py` yet, so the
packaging makes the name resolve today:

- **Windows**: the Inno Setup script copies the approved DLLs from the
  PyInstaller bundle (`sdk\<vendor>` or `_internal\sdk\<vendor>`, depending on
  the PyInstaller version) next to `solarscribe.exe`. Windows searches the
  executable's folder for a bare DLL name, so
  `ctypes.WinDLL("ASICamera2.dll")` succeeds. The `sdk\<vendor>` tree stays for
  a future path-based loader.
- **Linux**: the `/usr/bin/solarscribe` wrapper prepends every
  `/usr/lib/solarscribe/sdk/<vendor>` to `LD_LIBRARY_PATH` before executing the
  system Python, so `ctypes.CDLL("libASICamera2.so")` resolves. The wrapper is
  the only place that sets it; the desktop entry and a terminal start both go
  through the wrapper.
- **PyInstaller on Linux** is used for the smoke test, not for a release
  package. If a portable Linux tree becomes a release artifact, it needs the
  same wrapper or a runtime hook; do not assume `LD_LIBRARY_PATH` is set.

### Intended `sdk_dir()` contract

When `config/paths.py` grows an `sdk_dir()` (or the loader learns to look in a
path), it should use this order, first hit wins:

1. `$SOLARSCRIBE_SDK_DIR`, if set. Escape hatch for a user with a vendor SDK
   elsewhere and for the functional tests.
2. Frozen build: `sys._MEIPASS/sdk`, then
   `os.path.dirname(sys.executable)/sdk`.
3. System install on Linux: `/usr/lib/solarscribe/sdk`.
4. Source checkout: `<repo>/installer/vendor/bundle/<platform>`; it exists only
   after `prepare_vendor.py` and is a developer convenience, not a release path.

The loader should then use the full path, not the bare name. On Windows 3.8 and
later, `ctypes.WinDLL` does not search `PATH` for a DLL's own dependencies, so
the full-path branch must call `os.add_dll_directory(sdk_dir/<vendor>)` and
keep the returned handle alive while the camera is open. On Linux,
`ctypes.CDLL(full_path)` is enough and `LD_LIBRARY_PATH` becomes a fallback
only. The distribution packages depend on `libusb-1.0-0`, which the SDKs link
against.

## 5. Udev and firmware

- `99-solarscribe-cameras.rules` is always installed. It grants the logged-in
  seat access with `TAG+="uaccess"` and raises `usbfs_memory_mb` for the
  high-frame-rate cameras (ZWO 1024, Player One 256). A 3480x248 16-bit ROI at
  120 fps is about 207 MB/s; the default 16 MB kernel buffer is not enough.
- `85-solarscribe-qhy.rules` loads the QHY firmware with `fxload`. It is
  installed only when the firmware is present, because the QHY SDK has no
  redistribution grant (see `installer/licenses/qhy.md`). A package without
  the firmware must not leave udev calling a missing file.
- The `.deb` and `.rpm` run `udevadm control --reload-rules` from their
  maintainer scripts. The source and tarball path is
  `installer/install-udev-rules.sh`.

## 6. Versioning

`setuptools-scm` is the single source. A `vMAJOR.MINOR.PATCH` tag produces the
exact version; an untagged commit produces a `.dev` version. The installed
metadata is read with `importlib.metadata.version("solarscribe")` and passed
unchanged to PyInstaller, Inno Setup, the `.deb` and the RPM. CI resolves the
version before building and fails when the installed metadata is the `0.0.0`
fallback.

`solarscribe.__version__` reads the same installed metadata with
`importlib.metadata.version("solarscribe")`, so `solarscribe --version` and
`session_meta.json` show the same string as the installer. The `"0.0.0"`
fallback is used only by a bare source tree with no dist-info.

An editable install keeps the version that was recorded when `pip install -e
.` ran. After a new tag, reinstall the editable package (or use a normal
wheel) so the metadata and the reported version move together.

## 7. What would change this note

- A portable Windows ZIP that wants the SDKs beside the executable: that is
  already step 2 of the search order, no decision changes.
- A Flatpak or AppImage: the sandbox changes udev and `/usr/lib`, so it needs
  a new ADR, not a tweak here.
- A second app name or a shared Irydeo config folder: change `config/paths.py`
  and this table together, and bump the packaging note.
