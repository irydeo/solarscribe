# SolarScribe user guide

**English** · [Español → GUIA_USUARIO.md](GUIA_USUARIO.md)

A guide to SolarScribe: what it does, why each feature matters and how a session
is meant to run. It is written from the design and the contracts, so it can be
read before the code exists. Sections marked **Planned** describe agreed
behaviour, not something you can run today.

> **Status of this guide (2026-11-06)**: the real capture, centring and scan
> engines are wired into the interface and run against a solar-spectrum
> simulator; real camera and mount capture is not validated yet. The guide is
> written with the contracts, so the behaviour is specified before every corner
> of the hardware is proven.

---

## 1. What SolarScribe is

SolarScribe is the **capture** application for a solar spectroheliograph (SHG).
It opens the camera and the mount, measures on the live stream, runs the scan and
leaves the SER files and the logs ready for post-processing. **It does not
post-process**: recon, stacking and mosaics stay in JSol'Ex and the
`nightscribe-scan/tools` utilities.

A spectroheliograph works in a way that explains almost every feature in this
guide. Light entering a narrow slit is dispersed into a spectrum. The mount moves
the solar disk across that fixed slit, and each captured frame becomes one column
of the final image. The reconstruction is correct only if the sky moves exactly
one pixel width per frame; that is why the scan rate, the real frame rate and the
ROI matter so much.

SolarScribe is a sibling of NightScribe and keeps its patterns: Python 3.11+,
PySide6, a dark theme, a session by steps, bilingual ES/EN and GPL-3. It replaces
SharpCap in the SHG workflow, with one difference of substance: it is genuinely
cross-platform (Linux and Windows) and it only does SHG.

**Not in scope, by design**: post-processing, guiding, motorised autofocus and
dome control. A light **quick recon** exists to validate a take, but it is shown
on screen only and never replaces the real reduction chain.

---

## 2. Status and what works today

This is a young repository, and pretending otherwise would waste your time.

| Area | Status today |
| --- | --- |
| Package skeleton and layer layout | **Available** |
| Contract modules (`devices`, `capture`, `shg`, `config`) | **Available** |
| Configuration schema, profile and session state | **Available**: reading and writing with defaults, atomic writes and a v1 to v2 profile migration |
| Dependency-rule test (`tests/unit/test_layers.py`) | **Available** |
| GUI, camera panel and simulator | **Available**: the window starts, discovery finds the simulator, and the camera opens and streams |
| Real engines wired into the window | **Wired (simulator)**: centring, ROI, preparation, scan and the preview run against the simulator |
| Real camera and mount capture | **Planned (MVP)**: the drivers and engines exist, not validated on hardware yet |
| Installers for Windows and Linux | **Not available yet** |
| ES/EN catalogues and this guide | **Available**; every extractable string is translated, 0 unfinished |

What you can actually do from a clone:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit
.venv/bin/python -m solarscribe --version
.venv/bin/python -m solarscribe --diagnostics
```

`python -m solarscribe --version` prints the version of the installed package; a
development checkout shows something like `0.0.1.dev3+g...`, and a source tree
that was never installed falls back to `0.0.0`. `python -m solarscribe` opens the
main window; with no camera or mount it starts with the simulator.
`python -m solarscribe --diagnostics` prints a report of the paths, the optics,
the ROI presets and the device layer, and `python -m solarscribe --dry-run`
checks the geometry without opening the camera or moving the mount. Both are the
first things to attach to a bug report.

### Status words used in this guide

| Word | Meaning |
| --- | --- |
| **Available** | It works in the current source tree. |
| **Wired (simulator)** | The real engine is connected to the interface and runs against the simulator; the hardware path is still Planned (MVP). |
| **Planned (MVP)** | Agreed in the design and the contracts; it is part of the first usable release. |
| **Planned (phase 2)** | Agreed, but after the MVP (more camera backends, focus aid, device diagnostics). |
| **Planned (phase 3)** | Hardening and extra mount backends. |
| **Design only** | The decision exists; the shape may still change. |

---

## 3. Quick start

### 3.1 Reference equipment

The MVP is developed and validated on this setup, and the default figures in the
configuration come from it:

| Item | Reference |
| --- | --- |
| Camera | Touptek G3M678M, mono, 16 bit, no temperature control |
| Reference ROI | 3480×248 px |
| Mount | OnStep, through ASCOM COM on Windows and INDI on Linux |
| Optics | SHG-700 spectroheliograph, focal length about 714 mm, 2 µm pixels, 7 mm slit |
| Development | Linux; the mount is validated on Windows |

The 7 mm slit is not an arbitrary figure: at 714 mm focal it subtends
`7 / 714 rad = 33.7'`, just over the solar diameter of about 32', so one row of a
scan can cover the whole disk.

### 3.2 Install

See [the install guide](../install/INSTALL.md). Until the first release, the only
path is a source install; the installers on GitHub Releases are planned.

### 3.3 First run (available in the simulator)

1. The application checks the language (system language by default; Spanish and
   English are supported) and shows an inline welcome assistant on first start.
2. The assistant asks for the **observatory location**: latitude and longitude.
   They are needed to compute where the Sun is; a wrong location mis-points the
   telescope by degrees.
3. It asks for the **profile**: telescope focal length, aperture and slit length,
   plus the camera model and pixel size. The reference profile is 714 mm, 80 mm
   aperture, 7 mm slit, 2 µm pixels.
4. The camera and the mount are discovered in the background. Discovery can take
   a second or more because it talks to the SDKs, so it never runs on the GUI
   thread.
5. If a device is missing, the app says what is missing and carries on with the
   rest. A camera simulator and a mount simulator let you explore without
   hardware.

### 3.4 A session in one page (available in the simulator)

```
power camera + mount
        |
        v
welcome / settings: location, profile, language
        |
        v
camera panel: find a camera, open it, restore the ROI preset from the profile
        |
        v
1. Find the Sun: GOTO by ephemeris, coarse and fine centring on the slit
        |
        v
2. Polar alignment: drift samples of the Sun's Dec, azimuth and altitude hints
        |
        v
3. ROI: capture strip, spectral band, tilt, validation, estimated FPS and data rate
        |
        v
4. Scanning: preparation (fine centring + rate calibration), simple scan or mosaic,
   three cycles by default, live progress and drop counters
        |
        v
SER + scan_log.csv + scan_stats.jsonl + session_meta.json
        |
        v
quick recon on screen + session summary + open session folder
```

---

## 4. Session flow

### 4.1 The rail, not a wizard

The main view is a **session by steps**. A horizontal rail shows the state of
each step (pending, current, done, skipped). Navigation is free: the rail guides,
it does not lock. Every control stays visible; there is no separate expert mode.
The state is saved silently after every change, and a completed step can be
reopened.

This matters because a session is a sequence of setup decisions, and a form with
every control at once does not tell a newcomer where to start. It also matters
because an experienced observer must be able to jump straight to the ROI when the
Sun is already on the slit.

**Status**: Wired (simulator). The rail, the free navigation and the silent
auto-save run in the window; the steps drive the real engines with the simulator.

### 4.2 The four steps

| Step | What it does | Why it matters |
| --- | --- | --- |
| **Find the Sun** | GOTO to the Sun by local ephemeris, then coarse and fine centring on the slit | The scan needs the disk on the slit before anything else |
| **Polar alignment** | Samples the Sun's Dec over time and separates azimuth from altitude error | Daytime tracking error smears the disk and biases the scan rate |
| **ROI** | The user selects the capture strip and the spectral band; the tilt is measured and the ROI validated | The ROI sets the frame rate, the SER size and the data rate |
| **Scanning** | Fine centring, scan-rate autocalibration, then a simple scan or a mosaic | This is where the data is actually written |

Fine centring and rate calibration are **preparation inside the Scanning step**,
not a fifth step. The prototype taught that lesson: the two operations belong
together and both depend on the final exposure.

**Status**: Wired (simulator). The rail, the free navigation and the silent
auto-save run in the window; the steps drive the real engines with the simulator.

---

## 5. Features

Each feature says what it does, why it matters and how it is meant to be used.
Every figure in the interface must come with its meaning; the guide follows the
same rule.

Most features are now **Wired (simulator)**: the real engine runs in the window
against the simulator. Their hardware path is still **Planned (MVP)**, and
hardware validation remains the gate before calling any of it done.

### 5.1 Camera discovery and open

**Status**: Wired (simulator). The camera panel opens the simulator today; a real
camera follows the same path when its SDK is present.

- **What it does**: the camera panel searches for cameras through every backend,
  lists what it finds and opens the one you choose. The simulator is always found
  and is labelled as such, so it is never mistaken for hardware.
- **On open**: the app restores the ROI preset for that sensor from the profile,
  fits the rectangle to the sensor if the preset does not fit, and starts the
  stream. The panel shows the model, the sensor size, the rectangle the camera is
  actually delivering and the measured frame rate.
- **Why it matters**: the ROI is a hardware request; the frame rate and the SER
  size come from it. Opening a camera is what turns the interface from a preview
  into a capture session, and restoring the preset puts a known good strip one
  click away.
- **Discovery**: it talks to the SDKs and runs in a worker, so a slow backend
  never freezes the window. A missing SDK appears as a message with the backend
  name, and the device diagnostics list what the build can reach.
- **Close**: stops the stream and closes the camera without touching the session
  or the telescope.

The measured rate is the engine's, not the value requested from the SDK: a
driver can accept a request it cannot sustain, and the scan rate is computed from
what actually arrives.

### 5.2 Find the Sun, and centre it on the slit

**Status**: Wired (simulator).

- **What it does**: computes the Sun's RA/Dec locally from the date and the
  observatory location, points the mount there, then centres the disk on the slit
  in two stages.
- **Where it runs**: with a camera open (see §5.1) and the mount connected. The
  telescope panel's **Point at the Sun and centre** starts it; the coarse and
  fine stages report progress and the Dec error in arcseconds.
- **Coarse centring**: a Dec hill-climb that maximises the fraction of bright
  pixels in the live frame, a proxy for the illuminated extent of the spectrum.
  It is fast and needs no scan.
- **Fine centring**: left/right symmetry when the disk fits along the slit;
  otherwise the chord method, which needs a short sweep. The interface says which
  method ran.
- **Why it matters**: the illuminated extent is maximal at the centre but its
  derivative is zero there (the chord is `L = 2·√(R² − q²)`), so the histogram
  alone cannot resolve the centre. That is the **dead zone**, a geometric limit,
  not a tuning problem. The interface says so and chains the fine step.
- **Manual fallback**: the telescope panel is always available for N/S/E/W moves,
  GOTO by coordinates, sync, tracking and park.

The local ephemeris means the GOTO works with no network. A wrong observatory
location is the most common cause of a bad first GOTO: check latitude and
longitude before blaming the mount.

### 5.3 Solar polar alignment

**Status**: Wired (simulator). The assistant is a real session object
(`shg.polar`); in the simulator its samples are synthetic, so the figures prove
the wiring and the guidance, not the sky.

- **What it does**: with the Sun on the slit and the mount tracking, samples the
  Sun's declination every few minutes, subtracts the Sun's own motion (up to
  about 0.4"/min from the ephemeris), fits the drift line and derives the
  **azimuth** and **altitude** error.
- **Guidance**: it tells you how much to turn each knob, with the direction, and
  asks for a **second confirmation measurement** before declaring the alignment
  good. The confirmation must bring both screws inside the tolerance; if the
  samples were too close in hour angle, it says so instead of forcing a number.
- **When to measure**: near the meridian for altitude, towards the East or West
  for azimuth. The Sun sweeps from East to West during the day, so spreading the
  samples is what separates the two errors.
- **Why it matters**: Polaris is not visible in daylight, but the SHG still needs
  good tracking. This is the honest substitute: the Sun itself is the reference.
- **Time**: the measurement is deliberately unhurried; 20–40 minutes is the
  useful range. A shorter run cannot separate azimuth from altitude with
  confidence.

**Limit**: the geometry of the Sun at a given hour limits how much of each error
can be separated. The assistant says when a measurement is weak instead of
showing a confident number that is not.

### 5.4 The ROI: the strip that makes the scan possible

**Status**: Wired (simulator). The rectangles are sent to the real capture engine
and the preset is restored from the profile when the camera opens; the simulator
answers the same contract.

The SHG does not use the whole sensor. A cropped strip, 3480×248 px in the
reference setup, cuts the data rate and reaches about 120 fps. The ROI therefore
decides whether the scan is possible, and SolarScribe treats it as a subsystem,
not a hidden setting.

Four regions are distinguished:

| Region | What it is | Where it lives |
| --- | --- | --- |
| Capture ROI | What the camera delivers; it sets FPS and SER size | Sensor pixels, chosen by the user |
| Analysis ROI | Sub-regions used for measuring (left/right halves, limb columns, focus cells, tilt fit) | Computed, never saved |
| Spectral band | The useful strip of the spectrum; it must fit inside the capture ROI | Frame pixels |
| Output ROI | What is written to the SER and read by post-processing | Same as the capture ROI |

Tools:

- **Live editor**: an overlay on the viewer with draggable handles, numeric
  fields and snapping to the illuminated band. There is **no automatic
  proposal**; the observer decides.
- **Presets** per camera and optic, stored in the profile and restored when the
  camera opens. If a preset does not fit the sensor, the app fits it and says so.
- **Applied, not only stored**: **Apply this ROI** sends the capture rectangle to
  the capture engine, which restarts the stream with it. The SER receives exactly
  that rectangle; the profile preset is written back so the next session starts
  from the same strip.
- **Validation** in plain language: order clipping, slit-to-spectrum alignment,
  ROI height against the measured tilt, estimated FPS and data rate, SDK limits
  (multiples, binning) and coherence when the binning changes.
- **Recording**: the effective ROI and the tilt go to `session_meta.json` and
  `scan_log.csv`, so a take can be reproduced.

**Why the height matters**: the ROI must hold the spectral band plus the drift
caused by tilt plus a margin. A strip that is too tight clips the order; the
validation says so before the scan instead of leaving the discovery to
post-processing.

**What the editor can and cannot show**: the frame on screen is already the
capture ROI, so the editor draws the spectral band over it. A capture rectangle
larger than the frame would be fiction; the camera panel is where the delivered
rectangle is changed.

### 5.5 Tilt measurement

**Status**: Wired (simulator), with one honest exception: the simulator has no
tilted slit line, so the tilt reads about 0.0°. The fit is exercised by the unit
tests; a real frame is what proves it.

- **What it does**: fits a straight line to the position of the slit edge (or an
  absorption line) across the width of the ROI. The slope is the tilt, shown in
  **degrees** and in **drift pixels** across the ROI.
- **Straightness**: the fit also reports how straight the edge is. A wavy edge
  means the tilt figure is not trustworthy, and the interface says that instead
  of showing a number.
- **What it is used for**: sizing the ROI height, guiding you to leave the line
  straight (ideally close to 0°) and recording the value for post-processing.
- **What it does not do**: capture does not deskew the frames. Correcting the
  tilt is the job of post-processing, which does it better and must not find
  already-modified raw data.
- **When it is recalculated**: if the optic, the ROI or the camera orientation
  changes.

### 5.6 Scan preparation: fine centring and rate calibration

**Status**: Wired (simulator). The real preparation runs in a worker, reports its
phase and leaves the plan the scan will use.

Before the first frame of a scan, the engine computes a **plan** and runs three
steps:

1. **Plan**: rows, sweep rate, frames and expected duration, shown before
   anything moves. A mosaic plan is validated for coverage.
2. **Fine Dec centring**: symmetry when the disk fits along the slit, chord
   otherwise. The interface says which method ran, because one needs a short
   sweep and the other does not.
3. **Scan-rate autocalibration**: crosses the disk, measures the crossing time
   against the ephemeris diameter and scales the mount rate so the sky moves
   exactly one pixel width per frame. This removes the dependence on the
   configured focal length and on the reported frame rate being exact.

The result is logged per scan as `actual_xy`, close to 1.000 when the sampling is
correct. A guard rejects a calibration that would leave the sky rate more than
2× off the target, so one bad measurement cannot ruin a session.

**Why it matters**: a stretched or compressed reconstruction is the most common
SHG failure, and it is invisible until the image is processed. Calibrating
before the scan is what makes the result trustworthy.

**Honesty in the simulator**: it uses a fixed sweep rate so a demo finishes in
seconds, and the plan summary says so. Only the real camera can prove the rate.

### 5.7 Simple scan and multi-row mosaic

**Status**: Wired (simulator). The real scan engine computes the plan, sweeps and
writes the accounting; the simulator runs the same path with recording disabled.

- **Simple scan**: one sweep across the disk, one SER.
- **Mosaic**: several rows in Dec, each with its own SER, because one slit height
  may not cover the whole disk. The row step comes from the slit geometry, with
  an overlap and a margin; the plan warns if the outer rows do not reach the
  limb.
- **Cycles**: three scans per session by default. Three is enough to reject one
  bad take without doubling the session time.
- **Cycles and recentring**: each cycle is a separate sweep. Before the next one
  the mount rewinds to the start RA, which is mandatory, and, if **Recentre
  between cycles** is on, the Sun is centred again first. The rewind is what
  stops the later cycles from sweeping empty sky.
- **Pause**: **Pause** stops the mount and holds the sweep; **Resume** continues
  from where it stopped, and the frames already written are kept. The design also
  pauses automatically when the Sun leaves the slit; that automatic guard is
  still planned (MVP).
- **Edges**: a short RA preload absorbs backlash before recording starts; an
  adaptive stop ends the sweep when the trailing limb leaves the slit; each
  mosaic row is sized to the chord at its declination, not to the full diameter.
- **Retry**: the design keeps a retry for a failed scan with the failed attempt
  preserved; the current engine stops on the first failure and reports its reason
  code. Retrying is planned (MVP).

**Status of the four edge details**: wired (simulator), like the rest of the
scan.

**In the simulator**: the SER recording is disabled on purpose, so a run is a
dry run. The window says so when the scan finishes; no file pretends to be a
capture.

### 5.8 Exposure, binning and bit depth

**Status**: Wired (simulator). The capture engine applies the settings to the
camera; a rejected value comes back as a message, not a silent change.

- **Auto-exposure**: aims the mean at a target fraction of the full range, a
  quarter by default. A quarter fills the histogram and still leaves headroom for
  the bright chromospheric features, which must not clip.
- **Manual override**: exposure in microseconds, gain and offset as the SDK's own
  indices. Gains differ between brands, so they travel with the camera model in
  the profile.
- **Binning**: 1×1 by default. The SHG needs the full spatial resolution along
  the slit; changing binning revalidates the ROI.
- **Bit depth**: 16 bits per pixel. That is the contract with post-processing, not
  a preference.
- **Rejected settings**: if the camera refuses the exposure, the gain or the
  binning, the session says which one and keeps the previous value. The technical
  detail goes to the log.

### 5.9 Live scan visualisation, quick recon and summary

**Status**: Wired (simulator). The visualisation follows the real scan progress
and the summary comes from the scan result.

- **During the scan**: the viewer shows the strip already captured, the slit line
  and the percentage completed, over a **schematic disk** that works offline. If
  there is a connection, the day's real Sun image (SDO) can replace the
  schematic disk. The percentage refers to the planned sweep, so 100% means the
  plan finished, not that the image is processed.
- **As the scan advances**: a **quick recon**, computed by the SHG layer with
  `shg.quick_recon`. It collapses each frame's spectral band into one profile and
  stacks the profiles in time into a disk; the window paints the result on screen
  as the sweep runs. The caption says how many frames and rows went into it.
- **What the quick recon is not**: calibrated, aligned, flat-fielded or
  photometric. It is not exported, it does not read the SER back and it does not
  replace post-processing.
- **When it cannot be built**: the window says why in plain language, with a
  stable reason behind it: too little contrast to show a disk, no frames yet, a
  spectral band with no pixels, or frames that cannot produce a preview. The
  reason names the step to check.
- **Summary**: captured frames, dropped frames, duration and session path, with a
  button to open the session folder.

**Honesty**: the quick recon is not authoritative. If it looks good, the data is
probably usable; if it looks bad, the reason is usually in the logs, and the
summary points there. The caption "light preview, not for measurement" is part of
the widget on purpose.

### 5.10 Health panel and performance counters

**Status**: Wired (simulator). The counters come from the real capture engine;
with the simulator they prove the wiring, not the sustained rate.

A scan at 120 fps on the reference strip moves about 207 MB/s, so the health of
the stream is not a detail. The panel shows, in plain language:

| Figure | What it means | Budget |
| --- | --- | --- |
| Real FPS | Frames per second actually received | ≥ 120 at the reference ROI |
| Dropped by the SDK | Frames the camera driver says it lost | ≤ 0.1% per scan |
| Dropped by the queue | Frames lost because the disk could not keep up | Part of the same 0.1% |
| Sequence gaps | Holes in the frame numbering seen by the host | 0 in nominal conditions |
| Queue high-water mark | How close the recording queue came to its 512 MB ceiling | Stable, not pinned at the ceiling |
| Disk rate | Megabytes per second written while recording | ≥ 250 MB/s sustained |
| Viewer latency | Delay between capture and display | ≤ 150 ms |

Each figure is a fact with a comparison. A drop count without its budget is noise
to the observer, so the panel never shows one alone. Viewer latency is part of the
budget but is measured by the performance bench, not by a live counter in the
panel.

**In the simulator** the figure proves the pipeline is connected; only a real
camera can prove 120 fps and the 207 MB/s. The panel says which of the two it is
looking at.

### 5.11 Sky calendar, Sun tab

**Status**: Available. The figures are computed locally from the observatory
position; the optional SDO image needs a network.

Under **Tools → Sky calendar… → Sun** the solar utilities live together:

- The apparent solar diameter and angular size for the date. They feed the scan
  geometry, so a value computed for today is better than a fixed one.
- The **position angle of the solar north pole P**, in degrees. It says how far
  the north pole is tilted east or west in the sky, and post-processing uses it
  to orient the reconstructed image.
- The **heliographic latitude B0 and Carrington longitude L0** of the centre of
  the disk. They say which part of the Sun the slit crosses.
- The **Carrington rotation** number, so images of the same region can be
  compared across rotations.
- Active regions (NOAA).
- An optional real Sun image (SDO) for the calendar and the scan visualisation.

**Without a network** the tab still works: the ephemeris and the P, B0 and L0
figures are local, and the visualisation falls back to the schematic disk. If the
ephemeris module is missing, the figures are hidden instead of guessed.

### 5.12 Profiles, settings and language

**Status**: Wired (simulator). The profile is read and written by the
configuration store; the settings dialog edits the same schema.

- **One profile**, not a list of competing ones: telescope data (focal length,
  aperture, slit length), camera data (model, pixel size, binning) and ROI
  presets per camera and optic.
- **ROI presets** are restored when a camera opens and written back when you
  apply a ROI, so the next session starts from the same strip. A preset that does
  not fit the sensor is fitted and reported.
- **INI settings** inherited from `nightscribe-scan`, plus the new ROI, tilt,
  mount, capture-limit and session keys. Every key has a default and an
  explanation, so a hand-edited file never stops the app from starting.
- **Hand editable**: the file is plain text. A value that cannot be parsed falls
  back to its default, and the settings dialog explains what each key controls.
- **Language**: the system language by default, with Spanish and English
  available. Changing it asks for a restart so the application reloads its
  catalogues.

**Known limitation**: the explanations in the settings dialog are the `why` texts
of the configuration schema. They are English-only in this build; the labels and
the rest of the interface are translated. The labels themselves do not change the
facts the tooltip explains.

### 5.13 Dry run and simulators

**Status**: Available. `--dry-run` checks the geometry without opening the camera
or moving the mount; the GUI simulator runs the real engines against a synthetic
sky.

- **Dry run**: the mount moves and the engine measures, but nothing is recorded.
  It is the safe way to rehearse a session, and it is useful without a camera or
  a clear sky.
- **Solar-spectrum simulator**: the window uses the first-class
  `SimCamera(pattern="solar")`, bound to the simulated mount, so the rendered disk
  moves with Dec and RA and the real centring and scan loops converge. It has
  **no tilted slit line**, so the tilt reads about 0.0° in the simulator; the tilt
  meter is exercised by the unit tests. The spectral band rows are fixed at the
  reference band, so the preview shows what that band would produce.
- **Camera simulator**: the same `SimCamera` through the `Camera` contract, so the
  capture engine, the counters and the viewer take the real path.
- **Mount simulator**: a mount that reports position and accepts rates, so the
  whole session flow can be exercised without hardware.

**Honest limits**: the simulator is not a radiometric instrument. It uses a fixed
sweep rate so a demo finishes in seconds, and SER recording is disabled on
purpose, so a simulated run is a dry run. Only real hardware can prove the rate,
the noise and the disk throughput.

The simulators are also what makes the automated tests possible, which is why
they are part of the product design and not an afterthought.

### 5.14 Focus aid

**Status**: the dialog is present in the interface; the full routine and its
tests are planned (phase 2).

The focus indicators follow the SHG-700 routine:

1. **Spectrograph**: maximise the contrast and gradient of the absorption lines.
   H-alpha is the main line.
2. **Collimator**: maximise the sharpness of the slit edge and minimise its
   flatness.
3. **Telescope**: maximise the contrast, gradient and number of surface
   structures.

The indicators are computed along both axes, so camera orientation does not
matter. The design schedules the full routine for phase 2; the dialog in the
current interface shows the mean level and the contrast of the live frame, which
are the two indicators that matter most.

### 5.15 Device diagnostics and extra mount backends

**Status**: the `--diagnostics` mode is available in this build; the extra mount
backends are planned (phase 3).

- A **device diagnostics** mode reports which SDKs and backends were found, what
  each camera reports and what the mount accepts. It runs with
  `python -m solarscribe --diagnostics` and prints the paths, the optics, the ROI
  presets and the state of the device layer.
- Extra mount backends: a direct serial fallback (LX200, OnStep) and INDIGO.

The extra backends are not needed to scan with the reference hardware, which is
why they come after the MVP.

---

## 6. Acceptance criteria

A take is considered good when these checks pass. They are the same criteria the
prototype uses, plus the ones SolarScribe adds for the ROI and the performance
budget.

| Check | Criterion | Why |
| --- | --- | --- |
| `actual_xy` in `scan_log.csv` | 0.97–1.03 | The X sampling is 1:1; outside this range the reconstruction is stretched or compressed |
| Measured vs used FPS | Less than 2% | The scan rate is computed from the frame rate |
| `frames_short_pct` | Close to 0 | Missing frames are holes in the reconstruction |
| Dropped frames per scan | ≤ 0.1% | The budget of ADR-013 |
| Sequence gaps | 0 in nominal conditions | A gap is a frame the host never saw |
| `CONSISTENCY` warnings | None | A change of scale between scans makes the rows disagree |
| Dec spread per mosaic row | Less than 10" | The rows must tile without a step |
| Tilt recorded | Present in `session_meta.json` | Post-processing needs it to correct the geometry |
| ROI height | Band + tilt drift + margin | A tight ROI clips the order |
| Session logs | Same columns as `nightscribe-scan`, none removed | The existing post-processing keeps working |
| Hand-written profile | The app starts with every default | A profile is data, not a program |
| Translations | 0 unfinished strings in ES and EN | The interface is bilingual from day one |

**Status**: the geometry can be checked in the simulator; the rate, the dropped
frames and the disk figures need real hardware. The table is the target for a
real take, not a claim that every figure has been measured.

---

## 7. Parity with `nightscribe-scan`

SolarScribe must cover every function of the prototype, except the two that are
out of scope by design: the SharpCap capture engine, which SolarScribe replaces
with its own, and the post-processing tools.

| # | `nightscribe-scan` function | SolarScribe |
| --- | --- | --- |
| 1 | Scan-rate self-calibration by limb crossing time | Wired (simulator) |
| 2 | Solar diameter from a local ephemeris, UTC of each scan | Wired (simulator) |
| 3 | Live slit-axis scale and mosaic step | Wired (simulator) |
| 4 | Scan watchdog: abortable wait, stall detection, disk guard, frame accounting, one retry | Wired (simulator); retry planned (MVP) |
| 5 | Consistency checks between scans | Wired (simulator) |
| 6 | `scan_log.csv`, `scan_stats.jsonl`, `session_meta.json` | Wired (simulator) |
| 7 | Control panel with profiles and configuration | Available in the simulator, as the PySide6 session UI |
| 8 | Focus aid | Dialog present; full routine planned (phase 2) |
| 9 | Simple scan and multi-row mosaic with chord-based Dec centring | Wired (simulator) |
| 10 | Auto-exposure loop | Wired (simulator) |
| 11 | Dec centring: left/right loop and chord | Wired (simulator) |
| 12 | Mosaic geometry: slit length, magnification, overlap, margin, scans per row, backlash | Wired (simulator) |
| 13 | RA preload, adaptive trailing-limb stop, padding | Wired (simulator) |
| 14 | RA rate correction by `1/cos(Dec)` | Wired (simulator) |
| 15 | Limb detection by standard deviation | Wired (simulator) |
| 16 | Slit extent and left/right mean measurements | Wired (simulator) |
| 17 | Profiles and persisted settings | Wired (simulator) |
| 18 | Capture ROI | Wired (simulator), as the live ROI editor |
| 19 | Tilt measurement | Wired (simulator), new in SolarScribe |
| 20 | Solar polar alignment | Wired (simulator), new in SolarScribe |
| 21 | Find the Sun: ephemeris GOTO and coarse histogram centring | Wired (simulator) |
| 22 | Capture engine and SER writer | Wired (simulator) |
| N/A | `tools/align_stack_recon.py`, `tools/mosaic_from_recon.py` | Out of scope: external post-processing |

Some rows deserve a note:

- **Row 7**: the prototype's HTML panel is replaced by the native session UI, but
  the functions are the same: profiles, settings, start and stop.
- **Row 18**: in the prototype the ROI is set in SharpCap. In SolarScribe it is a
  first-class step with validation and a measured tilt.
- **Rows 19 and 20** are additions, not parity items. They exist because the
  design closes two gaps the prototype left open.
- **The post-processing tools** are not ported. SolarScribe feeds them, with the
  same columns and the same SER format.

---

## 8. When something goes wrong

Every feature in SolarScribe exists to detect or fix a specific failure. This is
the map.

| Symptom | Typical cause | What SolarScribe does | What you do |
| --- | --- | --- | --- |
| Elliptical reconstruction (X/Y ≠ 1) | Scan rate or slit scale | Autocalibrates X, measures `S_Y`, records `actual_xy` | Check `actual_xy`; if it is near 1, the problem is the slit axis |
| Mosaic rows do not line up | Dec step with the wrong scale | Measures the slit scale and records the real Dec of each row | Use the measured offsets in the mosaic tool |
| One row at a different scale | FPS or scale changed between scans | Emits a `CONSISTENCY` warning | Find what changed in capture, or let the mosaic tool rescale as a last resort |
| Empty SER or no data | Disk full, driver hang | Disk guard, stall watchdog, preserved SER and a reason code | Free space, check the USB link, raise `stall_timeout_s` only if the hardware is slow |
| Missing frames | USB bandwidth or frame limit | Compares written frames with duration × fps and warns `FRAMES SHORT` | Lower the rate, shorten the exposure or check the cable |
| Soft stack | Dec drift between frames | Dec re-centring and the drift in the log | Check `dec_start`; improve polar alignment |
| Brightness seam in a mosaic | Exposure changed between rows | Fixes the exposure once per session | Use the normalise option in the mosaic tool |
| Tracking drift over time | Polar alignment | Drift summary at the end of the session | Adjust azimuth or altitude as hinted |
| The Sun leaves the slit mid-scan | Tracking error or a bump | Pauses, warns and waits | Recentre with the telescope panel, then continue |
| The app starts without a camera or a mount | Missing SDK or platform backend | Says what is missing and keeps running | Install the SDK or the platform backend; use the simulator to explore |

**Status**: the behaviours are planned; the wording in the interface will be
written with the code and translated with the rest of the strings.

---

## 9. Files and logs

**Status**: Wired (simulator). The scan engine writes the three logs and the SER
in a real capture; the simulator records no SER, so its session folder holds the
state, the logs and the summary but no SER files. The formats are inherited from
`nightscribe-scan`; the new columns are added, never replacing the old ones.

### 9.1 The session folder

One folder per session, named with its date and time, inside a configurable base
folder. Files are named:

```
sun_AAAAMMDD_HHMM_scanNN.ser    one file per scan or per mosaic row
scan_log.csv                    one row per scan, rewritten after each scan
scan_stats.jsonl                one JSON sample per scan
session_meta.json               the effective configuration and geometry
session_state.json              the app's own memory of the four steps
```

The spelling above is the one fixed in the configuration contract. The exact
folder location is resolved per platform (see the install guide).

### 9.2 What is in the SER

A standard SER file: width, height, bit depth, colour ID and per-frame
timestamps, with 16 bits per pixel in the MVP. The capture ROI is not a standard
SER field, so it is recorded in `session_meta.json`, next to the file.

### 9.3 The three logs

- **`scan_log.csv`**: one row per scan, rewritten after each scan. It is the file
  you read first when a take looks wrong.
- **`scan_stats.jsonl`**: the same metrics per scan as JSON, one sample per scan,
  shaped for scripts and plots.
- **`session_meta.json`**: the effective configuration, the calibration, the slit
  geometry, the mosaic plan, the ROI, the tilt, the app version and the drop
  counters.

Fields worth knowing, because they answer the usual questions:

| Field | What it tells you |
| --- | --- |
| `actual_xy` | Whether the X sampling is 1:1; about 1.000 is correct |
| `frames_short_pct` | The fraction of frames missing against duration × fps |
| `problem` | The reason code of a failed scan; empty when the scan was fine |
| `dec_offset_measured_arcsec` | The real Dec of a mosaic row |
| `slit_extent_px` | The illuminated extent along the slit, the Y scale |
| `calibration_factor` | The correction the rate calibration applied |

### 9.4 Two files that are easy to confuse

- **`session_state.json`** is the application's memory: which step is done, what
  numbers were measured, where the session is. It is saved silently and can be
  discarded without losing data.
- **`session_meta.json`** is the contract with post-processing: the effective
  geometry and the version, with stable columns. It is not app state.

Keeping them apart is deliberate. A step can be reopened without touching the
record of the take, and post-processing never depends on how the interface
remembers things.

---

## 10. Deep dive: how it works and why

This section collects the geometry and the reasoning, so the behaviour can be
understood and diagnosed without opening the design documents.

### 10.1 Scan geometry and the X sampling

An SHG reconstructs one image column per captured frame. For the reconstruction
to be 1:1, the sky must move exactly one pixel width per frame:

```
scan_speed ("/s)    = pixel_scale ("/px) × fps (frames/s)
scan_multiplier (×) = scan_speed / sidereal_rate
```

`pixel_scale = 206265 × (pixel_size_um / 1000) / focal_length_mm`.

For the reference setup: 2 µm pixels at 714 mm give about 0.578"/px; at 120 fps
that is about 69.3"/s, or 4.61× the sidereal rate. The solar diameter of about
1934.8" then spans about 3349 px, which matches the reference strip.

Two traps:

- The focal length must be the **effective** focal length at the sensor, measured
  on a native reconstruction. A processing scale copied from a post-processing
  tool is not the physical focal length and will scale the whole image in X.
- The mount moves in RA coordinates, so the true sky rate is `rate × cos(Dec)`.
  The correction divides by `cos(Dec)`, which keeps the X scale the same at any
  declination.

### 10.2 Ephemeris and rate self-calibration

The apparent solar diameter changes by about 3% over the year. SolarScribe
computes it from the date with a low-precision local ephemeris, accurate to about
0.01%, and records the UTC of every scan so the exact value can be recomputed
later. If the configuration forces a value, the log says so; if the ephemeris
fails, a fallback is used and recorded.

At session start, once the exposure is final, the engine measures the real frame
rate and then **self-calibrates the scan rate**: it crosses the disk, measures
the crossing time against the ephemeris diameter and scales the mount rate so the
sky moves exactly one pixel width per frame. This removes the dependence on the
focal length and the reported FPS being exact.

The calibration measures the sky rate while moving at a known multiple of the
scientific rate, and scales by the rate per unit, not by the raw ratio. The
prototype got this wrong once and the scan came out several times too slow. A
guard rejects a correction that would leave the sky rate more than 2× off target.

The same local ephemeris returns the rotation figures the sky calendar shows:
**P**, the position angle of the solar north pole (positive towards the east),
**B0**, the heliographic latitude of the centre of the disk, and **L0**, its
Carrington longitude. P orients the reconstructed image; B0 and L0 say which part
of the Sun the slit crosses. They follow Meeus's low-precision solar coordinates
and are checked against the published example (P = 26.27°, B0 = +5.99°,
L0 = 238.63° at JD 2448908.5). They never need a network.

### 10.3 The slit axis and reconstruction anisotropy

In the reconstruction, X is the scan and Y is the slit. The two axes do not share
a plate scale: the slit re-imaging magnification is not necessarily 1, so the
disk can come out noticeably wider than tall. In the reference setup the ratio is
about 1.28, with Y compressed.

With the disk centred, SolarScribe measures the illuminated extent along the slit
and derives `S_Y = solar_diameter / extent_px`. The correction is to **stretch
Y**, not to change the mount rate. Confusing the two is what makes a mosaic step
wrong even when every individual scan looks fine.

### 10.4 Dec centring, the dead zone and the chord

Two methods share the work:

- **Left/right loop**: split the frame into two halves and compare their mean
  brightness, `offset = (L − R) / (L + R)`. It is valid only when the disk fits
  along the slit. When the disk overfills the frame, both halves are full of
  disk, the metric loses its zero crossing and the loop can push the Sun out of
  the slit.
- **Chord method**: the RA interval between the leading and trailing limb is the
  chord of the disk at the slit's declination. With `R` the solar radius, `S` the
  effective slit length and `q` the signed Dec offset of the slit centre:

```
e = max(0, |q| − S/2)          nearest slit edge to the disk centre
L = 2 × √(R² − e²)             the measured chord
|q| = e + S/2                  outside the dead zone
```

While the slit spans the disk centre (`|q| ≤ S/2`), the chord is the full
diameter and does not change with the offset. This is the **dead zone**. It is
geometry, not tuning. The routine walks in Dec until the nearest edge is far
enough from the centre, then probes to learn which side the slit was on. When the
disk fits the slit, the chord routine delegates to the cheaper left/right loop.

The coarse histogram centring makes the setup fast but cannot remove the dead
zone. The interface says that, and the fine step finishes the job.

### 10.5 Mosaic geometry

```
slit_px = slit_mm × magnification × 1000 / pixel_size_um
strip   = min(roi_width, slit_px) × pixel_scale / magnification
step    = strip × (1 − overlap)
margin  = max(configured_margin, uncertainty)
rows    = 1                                              if strip ≥ diameter
rows    = ceil((diameter + 2 × margin − strip) / step) + 1 otherwise
```

`magnification` is the slit re-imaging magnification, measured live when
possible. Rows are placed symmetrically around the centred declination. When one
row already holds the whole disk, the number of rows is forced to 1. The plan is
validated for coverage and warns if the outer rows do not reach the limb. A
margin row that finds no disk is skipped; if it happens after data was captured,
it is treated as the trailing edge and the mosaic ends.

### 10.6 Tilt and the height of the ROI

A line fitted to the slit edge gives a slope. The drift across the ROI width `W`
is:

```
drift_px = W × tan(tilt)
height   = band_height + |drift_px| + margins
```

The formula explains why a tilted line forces a taller strip. Capture measures
the tilt, uses it to validate the height, guides you to straighten the slit and
records it. It does not deskew. The post-processing has the raw data and the
figure it needs to correct the geometry without a second interpolation.

### 10.7 Why polar alignment is measured on the Sun

At night, polar alignment uses Polaris. In daylight there is no Polaris, but the
Sun is a precise Dec reference on the slit. The assistant samples its
declination, subtracts the Sun's own motion from the ephemeris and fits the
residual drift. Azimuth and altitude errors produce different drift patterns
depending on the Sun's hour angle, which is why the assistant recommends
measuring near the meridian for altitude and towards the East or West for
azimuth, and why it spreads the samples over 20–40 minutes.

A second measurement is required before the result is accepted. It is slower than
a single reading, and it is the only way to tell a real correction from noise.

### 10.8 Threads, drops and the performance budget

The capture thread does one thing: get a frame from the SDK and hand it to cheap
inline consumers. The recording queue is bounded on purpose. A slow disk costs
frames that are counted, never a stalled capture thread. The viewer is a one-frame
mailbox: a slow GUI drops video frames instead of accumulating them.

Drops are counted in three places: inside the SDK, at the queue overflow and as
gaps in the frame sequence seen by the host. All three appear in the health panel
and in the logs, because a single number would hide where the loss happened.

The provisional budget for the reference ROI is 120 fps, about 207 MB/s, at most
0.1% dropped frames per scan, 150 ms viewer latency, a 512 MB bounded queue, at
least 250 MB/s of sustained disk and a capture start within 5 s. It is measured
in phase 0 and corrected with real numbers; the interface compares every figure
against it.

**The quick recon is cheap on purpose.** Each frame's band is averaged along the
dispersion axis, which leaves one intensity per slit position; those profiles are
stacked in time, and at scan position `x` the lit slit length is the chord
`2·√(R² − x²)`. The result is downsampled and normalised to 0 to 1. The spectral
information is gone, there is no alignment, no flat field, no `1/cos(Dec)`
correction and no photometry, and nothing is exported. That is why it can run
while the session continues and why it must not be mistaken for the result.

### 10.9 Network and privacy

The ephemerides are computed locally. The network is used only, optionally, for
the day's real Sun image (SDO) in the calendar and the visualisation. Without a
connection, the schematic disk is shown and everything else works. There is no
telemetry: nothing is sent anywhere.

### 10.10 Language and translation

Spanish and English are supported from day one. Every visible string goes through
the Qt translation mechanism, the catalogues are rebuilt when strings change, and
both languages must stay at zero unfinished strings. The language follows the
system by default and can be changed in the settings.

The figures in the interface are translated as sentences, never as bare codes:
the engine reports a stable reason code and the interface turns it into a
sentence with its numbers.

---

## 11. Limits and honesty

These are the limits you should know before trusting a take:

- **The rate is a hardware property.** The 120 fps budget is a target for the
  reference strip, not a promise for every camera, cable or disk.
- **The histogram has a dead zone.** Coarse centring is fast but cannot resolve
  the centre; the fine step is required.
- **Polar alignment takes time.** A short measurement cannot separate azimuth
  from altitude, and the assistant says so instead of inventing precision.
- **Tilt is measured, not corrected.** The raw frames stay raw; post-processing
  applies the correction.
- **The quick recon is not the result.** It answers "did the take work?", not
  "what does the Sun look like?".
- **There is no post-processing in SolarScribe.** Recon, stacking and mosaics
  remain external.
- **The MVP does not cover every camera brand.** The four native backends and the
  simulator are the plan; the generic camera backends come later.
- **The engines are proven against the simulator, not the sky.** Anything marked
  Wired (simulator) is connected but has not been validated on real hardware, and
  it may still change with an ADR. Anything marked Planned is not wired yet.

---

## 12. References

- [Install guide](../install/INSTALL.md).
- [CHANGELOG](../../CHANGELOG.md).
- [Design](../../design/DESIGN.md) and
  [layer contracts](../../design/ARCHITECTURE.md).
- [ADR index](../../design/adr/README.md). The decisions most visible here:
  ADR-006 (centring), ADR-007 (polar alignment), ADR-010 (ROI), ADR-011 (session
  steps), ADR-013 (performance), ADR-018 (post-processing contract), ADR-019
  (mount), ADR-020 (result), ADR-021 (network), ADR-022 (tilt).
- `nightscribe-scan` user guide and tools, the prototype this application
  replaces in capture.
