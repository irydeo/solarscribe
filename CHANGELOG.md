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

- **Real engines wired into the window**: the camera panel discovers and opens a
  camera, restores the ROI preset for its sensor and streams; a ROI is applied to
  the real capture engine; Sun centring runs coarse and fine with the dead zone
  stated; the scan engine computes the plan, prepares, repeats cycles and
  optionally recentres; the solar polar assistant samples, fits and asks for a
  confirmation. The GUI simulator now renders a solar spectrum coupled to the
  simulated mount, so the real loops converge against it.
- **Sky calendar figures**: the Sun tab adds the position angle of the north pole
  (P) and the heliographic centre (B0 and L0), computed locally with the
  ephemerides.
- **Quick recon wired**: the window calls `shg.recon.quick_recon` and paints its
  result as the scan advances, with the frame and row count in the caption and
  plain-language reason codes when it cannot build a preview. It is light,
  non-authoritative and never exported.
- **Simulator decision**: the window uses the first-class
  `SimCamera(pattern="solar")` bound to the simulated mount. It deliberately has
  no tilted slit line, so the tilt reads about 0.0° in the simulator, and it fixes
  the spectral band rows at the reference band. The tilt meter is exercised by the
  unit tests; a real frame is what proves it.
- **Version**: `solarscribe.__version__` reads the installed distribution
  metadata, so the window, the CLI and `session_meta.json` agree with the package
  version; a source tree that was never installed falls back to `0.0.0`.
- **Settings tooltips translated**: the 111 `why` texts moved to
  `solarscribe/ui/settings_text.py`, marked with
  `QT_TRANSLATE_NOOP("Settings", ...)` and looked up with
  `QCoreApplication.translate("Settings", ...)`. The ES/EN catalogues cover them,
  so a Spanish settings dialog no longer falls back to English.
- **i18n**: the new `CameraPanel` and `Session` contexts and the new MainWindow,
  sky-calendar and quick-recon strings are translated, 0 unfinished in ES and EN.
- `design/ARCHITECTURE.md` is now **v1**: the contracts are written in code and
  the document keeps the inventory and the reasons behind each type, which is the
  part that cannot be read from a signature.
- The ADR index lists ADR-024, and the ADR set covers the design through that
  number: tilt measurement (ADR-022), the contract modules (ADR-023) and the INI
  reconciliation with `nightscribe-scan` (ADR-024).

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
  hardware yet.
- No installer is built or published yet. Only the source install is available.
- The ES/EN catalogues cover every string `lupdate` can extract from the
  interface, with 0 unfinished entries. They are a snapshot: re-run `lupdate`
  after any `.ui` or `self.tr()` change.
