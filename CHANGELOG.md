# Changelog

All notable changes to SolarScribe are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/) and this project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Contract layer v1** (ADR-012, ADR-023): `devices/abc.py` (camera, mount and
  device manager), `capture/abc.py` (engine, SER writer, ROI model),
  `shg/abc.py` (scan engine, ports, tilt meter) and `config/schema.py` (INI
  schema, profile and session state). The value types, the protocols, the units
  and the reason codes are fixed there.
- **Configuration and profile support**: the INI schema with every key's
  section, type, default, explanation and origin; the JSON v2 profile with
  telescope data, camera data and ROI presets; and the persistent state of the
  four session steps. `config/store.py` reads and writes them with a default for
  every missing key, an atomic write, a v1 to v2 profile migration and the
  session file naming; `config/paths.py` resolves the per-platform folders.
- **Dependency-rule test** `tests/unit/test_layers.py`: it parses the sources with
  `ast` and fails if a layer imports upwards, if Qt appears outside `ui`, if
  `ctypes` appears outside `devices`, or if a contract module loses a name from
  its surface.
- **ES/EN Qt Linguist catalogues** at `solarscribe/ui/i18n/` plus the
  extraction and compilation workflow (`pyside6-lupdate` / `pyside6-lrelease`),
  documented in `docs/README.md`.
- **User guide and installation guide**, in Spanish and English, with the status
  of every feature written down: available, wired (simulator), planned (MVP),
  planned (phase 2/3) or design only.
- **Bilingual CHANGELOG** (`CHANGELOG.md` / `CHANGELOG.es.md`).

### Changed

- **Image-first five-step interface** (ADR-026, ADR-028): the viewer takes most
  of the window, the rail is a single 28 px line with five steps (Find Sun, Polar,
  Focus, ROI, Scan), the side panel is capped and the camera, telescope and health
  panels fold. The spectrum magnifier, the coordinate GOTO, Sync, the live RA/Dec
  readout, the Focus aid dialog and the new/open session ceremony are removed;
  **Open data folder** replaces them.
- **Focus step** (ADR-026, ADR-028): the three focusers run as a step with the
  `shg.focus` metrics (line contrast and sharpness, edge sharpness and wobble,
  detail contrast, sharpness and count), a `FocusWatcher` running best and a
  reset, plus the `shg.tilt` slit-to-Dec tilt and the ROI height it needs. A soft
  spectrum and a tilted slit are measured instead of guessed.
- **Native spectral-line identification**: the `SpectrumPanel` runs
  `shg.spectrum` on the live band, detects absorption dips, matches a built-in
  catalog and names the lines with an F1 confidence. It uses the target line and
  the dispersion from Settings → Spectrum, labels telluric lines and never calls
  JSol'Ex. The names are a pattern match, not a wavelength calibration.
- **Named profiles** (ADR-027): a visible profile bar and a manager store several
  named profiles in one `profiles.json`, with one active profile loaded at
  startup. Switching reloads optics and ROI presets without moving the telescope
  or restarting the camera. The old `profile.json` is read as `default`, and a
  `nightscribe-profiles.json` v1 is migrated.
- **Device layer fixes**: four SDK defects, including the Touptek crash. (1) The
  Touptek device struct was 20 bytes where the SDK writes 136, a heap overflow and
  the "Find cameras" core dump. (2) The Touptek and QHY open calls returned 64-bit
  handles through the default `c_int` restype, truncating them and segfaulting the
  next call. (3) The Touptek `IMAGE` and `BITDEPTH` constants were
  `FRONT_OVERFLOW` and `DEMOSAIC_VIDEO`, so the driver waited forever. (4) The ASI
  camera-info `long` width and the Player One properties layout were wrong,
  shifting fields and risking another overflow. The native diagnostics mode prints
  the measured numbers.
- **INDIGO mount backend**: JSON over TCP to `indigo_server`, with the INDIGO
  property mapping and its rate classes. It does not invent an arbitrary
  arcsec/s rate; the scan calibration measures the rate the mount really gives.
- **i18n**: the new `ProfileManagerDialog` and `SpectrumPanel` contexts, the Focus
  step and the reworked layout strings are translated; the catalogues hold 896
  messages with 0 unfinished and 0 obsolete in ES and EN.
- **Real engines wired into the window**: the camera panel discovers and opens a
  camera, restores the ROI preset for its sensor and streams; a ROI is applied to
  the real capture engine; Sun centring runs coarse and fine with the dead zone
  stated; the scan engine computes the plan, prepares, repeats cycles and
  optionally recentres; the solar polar assistant samples, fits and asks for a
  confirmation.
- **Sky calendar figures**: the Sun tab adds the position angle of the north pole
  (P) and the heliographic centre (B0 and L0), computed locally with the
  ephemerides.
- **Quick recon wired**: the window calls `shg.recon.quick_recon` and paints its
  result as the scan advances, with the frame and row count in the caption and
  plain-language reason codes when it cannot build a preview.
- **Simulator decision**: the window uses the first-class
  `SimCamera(pattern="solar")` bound to the simulated mount. It deliberately has
  no tilted slit line, so the tilt reads about 0.0° in the simulator, and it fixes
  the spectral band rows at the reference band.
- **Version**: `solarscribe.__version__` reads the installed distribution
  metadata, so the window, the CLI and `session_meta.json` agree with the package
  version; a source tree that was never installed falls back to `0.0.0`.
- **Settings tooltips translated**: the 111 `why` texts moved to
  `solarscribe/ui/settings_text.py`, marked with
  `QT_TRANSLATE_NOOP("Settings", ...)` and looked up with
  `QCoreApplication.translate("Settings", ...)`.
- `design/ARCHITECTURE.md` is now **v1**: the contracts are written in code and
  the document keeps the inventory and the reasons behind each type.
- The ADR index lists ADR-028, and the set covers the design through that number,
  including the image-first layout (ADR-026), named profiles (ADR-027) and the
  five-step rail (ADR-028).

### Workstreams

The project runs as seven parallel workstreams with disjoint file ownership:
lead (contracts and design), video (camera, mount, capture), shg (science), ux
(interface), qe (tests and gates), packaging (installers and CI) and docs
(documentation and i18n). This entry records the first deliverables that cross
more than one of them: the contracts, the configuration and profile model, the
dependency test, the catalogues and the bilingual guides.

### Known limitations

- The GUI starts from source, and the `--diagnostics` and `--dry-run` modes
  work. Real capture and scanning with a camera and a mount are not validated on
  hardware yet. The Focus metrics and the spectral-line identification are
  exercised against the simulator and unit fixtures, not real spectra.
- No installer is built or published yet. Only the source install is available.
- The ES/EN catalogues cover every string `lupdate` can extract from the
  interface, with 0 unfinished and 0 obsolete entries. They are a snapshot:
  re-run `lupdate` after any `.ui` or `self.tr()` change.
