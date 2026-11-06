# SolarScribe UI: usability task script and result

Owner: `ux`. Gate: G4 of `AGENTS.md`. Date: 2026-11-06.

This is the script the `qe` agent executes and the record of its last run. It is
written for a newcomer: no vocabulary from the design documents, no step that
needs a hidden control. The automated version is
`tests/unit/test_ui_usability.py`.

## Environment

- `QT_QPA_PLATFORM=offscreen`, Linux, PySide6 6.12, Python 3.12.
- The simulator is the first-class `devices.sim.SimCamera(pattern="solar")`,
  bound to the simulated mount, behind the real `CaptureEngineImpl`. The window
  and the tests/bench share this one simulator: no UI scene, no second frame
  generator. The reference strip is 3480 x 248 and the simulated sweep uses a
  fixed 1200 arcsec/s rate.
- No hardware, no network. The SER recording is disabled in the simulation, so
  the scan is a dry run and the result says so.

## How to run

```bash
# the whole task script, with timings
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
    tests/unit/test_ui_usability.py -q -s

# the window by hand
.venv/bin/python -m solarscribe gui

# the window with no simulator at all (empty states, no hardware)
.venv/bin/python -m solarscribe gui --no-demo

# the headless checks
.venv/bin/python -m solarscribe --dry-run
.venv/bin/python -m solarscribe --diagnostics
```

## Task script

### T0. Open the camera (budget 10 s)

1. Open the camera panel on the right (tabbed with Stream health).
2. Press "Find"; the simulator is always found, a native camera only when its SDK is installed.
3. Choose the simulator and press "Use this camera".
4. Read the live model, sensor, ROI and rate; the state line says "Simulator".

Pass when the state line says Simulator, the stream is running, and the model,
sensor, ROI and rate are all filled in.

### T1. First run: tell the app where you observe (budget 10 s)

1. Open the app for the first time.
2. The welcome banner is above the step rail. It says why the position matters:
   without it the GOTO cannot compute where the Sun is.
3. Type the latitude and the longitude.
4. Press "Save and start".

Pass when the banner closes, the values are stored, and no modal dialog appeared.

### T2. Free navigation: nothing blocks (budget 5 s)

1. From the first run, click "4. Scanning" on the rail.
2. Click "1. Find the Sun" again.

Pass when both clicks change the side panel immediately, no question is asked,
and "Find the Sun" still shows as pending. The rail guides; it does not gate.

### T3. Find the Sun (budget 30 s)

1. In the telescope panel on the right, press "Connect" if it is not connected.
2. Read the live RA and Dec, with their units.
3. Press the primary action "Point at the Sun and centre".
4. Watch the live reading: the coarse then fine centring, the Dec error and the
   centring limit.

Pass when the step shows Done, the real `SunCenteringImpl` has run, the Dec
error is in arcseconds and the "Centring limit" row shows the dead zone that
method leaves. On the simulator the value is labelled as simulated.

### T4. Polar alignment (budget 30 s)

1. Click "2. Polar alignment" on the rail.
2. Press "Start the measurement".
3. Wait for the first result. The step shows the azimuth and altitude errors in
   arcminutes.
4. Press "Take the confirmation measurement".

Pass when the step shows Done, both measurements agree, and the second button
was clearly disabled until the first measurement finished.

### T5. ROI (budget 25 s)

1. Click "3. ROI" on the rail.
2. Press "Measure tilt". Read the tilt in degrees and in pixels of drift.
3. Drag the spectral band on the video, or type its numbers.
4. Read the rate estimate, with its target.
5. Press "Apply this ROI".

Pass when the step shows Done, the warnings say "No problems found", and the
capture rectangle and the band are the ones on screen. The frame is already the
capture ROI, so the band is dragged and the capture rectangle is typed; the
step says why.

### T6. Scanning (budget 90 s)

1. Click "4. Scanning" on the rail.
2. Read the plan once Prepare has computed it: mode, rows, duration, rate and
   frames.
3. Press "Prepare the scan". Wait for "Ready" with the Dec error and the rate.
4. Press "Start the scan".
5. Watch the captured strip, the slit line, the cycle counter and the percentage.
6. At the end, read the result and the quick recon, and open the session folder.

Pass when the step shows Done, the real `ScanEngineImpl` has run the configured
cycles, the result names the frames and the duration, the percentage reaches
100%, and `shg.quick_recon` has painted a preview that is labelled light and
non-authoritative. A failed preview explains `no_frames`, `band_empty` or
`low_contrast` in plain words. The RA rewind between cycles happens
automatically; the optional Dec recentre is the checkbox.

### T7. A mistake is explained, not blocked (budget 10 s, inside T5)

1. In the ROI step, set the capture height to 100 while the band is 160 tall.
2. Read the warning.

Pass when the warning starts with "Cannot scan", contains 100, 160 and 162, and
says whether to straighten the line or make the ROI taller. The Scanning step
still opens; only the scan action is disabled, with its tooltip explaining why.

### T8. Reopen a completed step (budget 10 s)

1. Click the "3. ROI" chip, which shows Done.
2. Press "Reopen this step".
3. Confirm the chip now says In progress and the previous tilt is still shown.

Pass when reopening keeps the saved numbers and opens the step again. The button
only appears on a completed step, so a pending step is not confused with a
reopened one.

## Per-feature task scripts

The whole-session script above is the gate. These shorter scripts cover each
feature on its own; the automated tests named after each one already check the
same pass criteria.

| Feature | Budget | Task | Pass when |
| --- | ---: | --- | --- |
| Camera panel | 10 s | Find the cameras, choose the simulator, press Use this camera. | The model, sensor, ROI and rate are live; the state line says Simulator; close empties the video and leaves the session alone. |
| Theme and first impression | 5 s | Open the app. Find the one action the first step asks for. | The amber primary button is the most prominent control, no widget is light grey, the title is SolarScribe and the sun icon is in the window. |
| Step rail | 5 s | Click the last chip, then the first. | The panel changes at once, no question is asked, and a pending step is still clickable. The chips spell Pending, In progress, Done or Skipped. |
| Live viewer and histogram | 15 s | Change the brightness preset, scroll to zoom, drag the image, toggle Grid and Slit cross, press Fit. | The picture and the two histogram markers change, the zoom readout follows, the drag pans only when zoomed, and Fit returns to 1x. |
| ROI editor | 20 s | Drag the band, type the capture rectangle, measure the tilt, read the scale and the rate, press Apply. | The band follows the pointer in frame pixels, the warnings carry their numbers, Apply sends only a valid ROI, and Start stays off until then. |
| Telescope panel | 20 s | Connect, press Go to the Sun, nudge N/S/E/W, toggle tracking, Sync, Park, Abort, Stop. | Every control calls the mount, the live RA/Dec changes with units, each failure is a sentence, and Stop is always reachable while connected. |
| Scan visualisation and quick recon | 30 s | Prepare, start, watch the strip and the percentage, pause, resume, stop. | The shaded strip and the slit line follow the percentage, the quick recon fills in, the result names frames and duration, and Open session folder works. |
| Welcome assistant | 10 s | Read the banner, type the position, press Save and start. | The banner closes, the values are stored, and the GOTO can now compute the Sun. |
| Settings | 10 s | Open Settings, filter "exposure", hover the field, change it, save. | The filter narrows the form, the tooltip is the schema's explanation, and the value survives a restart. |
| Logs | 5 s | Open Tools, Logs; choose Errors only; press Reload. | The path and the filtered lines are visible; a missing file says so and still shows where it will be. |
| Sky calendar, Sun tab | 5 s | Open Tools, Sky calendar. | Date, diameter, RA, Dec, north pole angle P and the heliographic centre B0/L0 are shown with units; the disk is drawn without a network. |
| CLI | 5 s | Run `--dry-run` and `--diagnostics`. | The dry run writes nothing, names the ROI and its findings, and exits 1 on an error; the diagnostic lists the paths, the backends and their reasons, and no Qt is imported. |

Automated coverage: `test_ui_theme.py`, `test_ui_steps.py`, `test_ui_viewer.py`,
`test_ui_roi_editor.py`, `test_ui_telescope_panel.py`, `test_ui_scan_view.py`,
`test_ui_dialogs.py`, `test_ui_polar.py`, `test_ui_main_window.py`,
`test_ui_camera.py` and `test_cli_modes.py`.

## Result of the last run

Measured on the simulator, in the order above:

| Task | Budget | Measured |
| --- | ---: | ---: |
| Camera discovery and open | 10 s | 0.06 s |
| Free navigation | 5 s | 0.00 s |
| Welcome | 10 s | 0.00 s |
| Find the Sun | 30 s | 10.05 s |
| Polar alignment | 30 s | 4.17 s |
| ROI | 25 s | 0.08 s |
| Scanning, 3 real cycles | 90 s | 20.96 s |
| Reopen step | 10 s | 0.00 s |
| **Total** | | **35.33 s** |

Verdict: **pass**. All four steps reach Done without a modal dialog, and the
state is on disk without pressing Save. The camera is opened through
`DeviceManagerImpl`; `CaptureEngineImpl` streams it; the Find step runs
`SunCenteringImpl`; the Scanning step runs `ScanEngineImpl` for three cycles and
rewinds the mount between them; `shg.quick_recon` paints the preview; the polar
task runs the real `PolarAlignmentSession` on simulated Dec samples and waits
for a confirmation inside 60 arcsec.

## Friction points found and fixed

1. **The GOTO fields chased the mount.** The panel refreshed the RA/Dec inputs
   from `position()` every 750 ms, so typing a coordinate was impossible and
   `Sync` always sent the current position. Fixed: the fields are inputs, the
   live readout above is the mount. This was found by the sync task, not by a
   reviewer.
2. **The ROI text promised a drag that does not exist.** The step said "draw it
   on the video" while only the spectral band can be dragged (the frame is
   already the capture ROI). Reworded: draw the band, type the capture
   rectangle, and the text says why.
3. **The status bar looked broken in the simulator.** The low simulated rate was
   amber with no explanation. It now says "(simulator)" and the health panel
   says that only the real camera can prove the rate.
4. **Zoom had no pan.** At 4x the image was centred and a corner was
   unreachable. Drag now pans when zoomed; "Fit" resets both.
5. **The log viewer hid the path when the file did not exist yet.** It now says
   "No log yet" and still shows the path that will be written.
6. **Start could run on a ROI the camera had not received yet.** The typed
   rectangles are not the applied ones, so Start is now disabled while the two
   differ, with a tooltip that says "Press Apply this ROI first". The step still
   opens; only the action is gated.
7. **The settings dialog showed raw INI names.** The fields now read "Capture
   width" and the exact key (`capture_width`) is in the tooltip, so a
   hand-edited file still maps to the field.
8. **The side panel could not scroll.** The step pages now live in a scroll
   area, so the ROI fields and the warnings are reachable on a 13 inch laptop.
9. **The Find step had no dead-zone field.** It now has "Centring limit" with an
   explanation of why the coarse histogram is flat near the centre; the real
   `SunCenteringImpl` fills it from `CenteringResult.dead_zone_arcsec` (0 for
   the symmetry method, slit/2 for the chord method).
10. **Apply on an invalid ROI changed the model while the status said it had
    not.** The editor now validates first and refuses to send an error to the
    session; the message and the state agree.
11. **Peeking at another step discarded the typed ROI.** The step switch no
    longer reloads the fields; only a real model change does.
12. **Choosing a preset pretended the camera had received it.** The preset is
    now loaded into the fields and the Start action stays off until Apply, which
    is what the ROI manager promises.
13. **The Tools dialogs could open twice.** Logs, Sky calendar, ROI manager and
    Focus aid now reuse their window and raise it.
14. **The window was demo-only.** It now builds a real `CaptureEngineImpl`,
    `SunCenteringImpl` and `ScanEngineImpl`; the camera panel discovers through
    `DeviceManagerImpl`, and the simulator is the first-class
    `SimCamera(pattern="solar")`, not a painter in the window.
15. **A camera connection did not restore its preset.** The named profile
    preset is converted with `preset_to_model` when the sensor connects; if it
    does not fit, the best fitting rectangle is used and the ROI step explains
    it.
16. **The scan repeated cycles without winding back.** Every cycle after the
    first now rewinds to the plan's starting RA; the optional checkbox also
    recentres Dec between cycles.
17. **Start could run before Prepare, with no plan.** Start now waits for the
    prepared plan, and the tooltip says "Press Prepare first".
18. **Closing the camera left its last frame on screen.** Close now empties the
    viewer, the magnifier and the histogram, so the status and the picture
    agree.
19. **The quick recon was a downsampled band slice.** It now runs
    `shg.quick_recon` over the scan frames, updates while the sweep advances and
    explains `no_frames`, `band_empty` and `low_contrast`.
20. **The window and the tests used two simulators.** The UI `SolarScene` and
    `SceneCamera` were removed; the window now binds the same first-class
    `SimCamera(pattern="solar")` the tests and bench use.

## Friction points still open

1. **The simulator is still a simulator.** It is the first-class
   `SimCamera(pattern="solar")` behind the real `CaptureEngineImpl`, but it is
   not a radiometric or optical model. Real hardware is the proof, and it has
   not been run here.
2. **The simulation does not write SER files.** The scan is a dry run because a
   3480 x 248 SER is about 1.7 MB per frame; the real camera path does use
   `RowRecorderAdapter` and `config.store.scan_ser_path`, but only the dry-run
   branch is exercised in CI. A real camera must verify the writer path.
3. **The polar assistant samples are synthetic.** The real
   `PolarAlignmentSession` fits them and applies the 60 arcsec confirmation, but
   the sampler that should read the Sun every few minutes is not wired; the page
   is a demo of the maths, not a 30 minute observation.
4. **The sky calendar has P, B0 and L0 but no Carrington rotation number.**
   `shg/ephemeris.py` does not expose the rotation number yet; the window shows
   what is computed and does not invent the rest.
5. **The ROI manager lists presets but cannot rename or delete them.** The
   profile is written by "Save preset" and by Apply in the ROI step.
6. **The focus aid uses the whole-frame mean and standard deviation.** shg's
   focus indicators (contrast on the slit) are still pending.
7. **The recommended step is a sentence, not a highlight on the rail.** The
   first pending chip is not visually singled out beyond its status word.
8. **No keyboard shortcuts for the rail.** The chips are standard tab-focusable
   buttons, but Alt+1 to Alt+4 would make the free navigation faster.
9. **Camera discovery probes native backends on a worker thread, but the
   simulator is the only camera available in CI.** A real Touptek, ASI, QHY or
   Player One has not been opened through the panel.
10. **The first-class solar pattern fixes the spectral band at the reference
    rows.** The default ROI band 40..200 matches it. Moving the band in the
    simulation shows a mismatch that real optics would not have, because the
    grating fixes where the spectrum lands.

## Simulator decision

The window uses `devices.sim.SimCamera(pattern="solar")` and binds it to the
simulated mount with `bind_mount()`, after `set_sun()` with the local ephemeris.
The camera panel's `SimCameraBackend` is created with the same pattern. The
window therefore shares one simulator with the tests and the bench.

The UI `SolarScene` and `SceneCamera` were removed. They rendered the chord,
limb darkening, spectral lines and the Dec shift, all of which the first-class
pattern also models. The only thing they added was a 0.28 degree tilted slit
line for the tilt meter to fit. The first-class band is flat, so the tilt meter
reads about 0.0 in the simulator. That is shown as 0.0, not hidden: the tilt
maths is tested by shg on its own fixtures, and the real spectrograph provides
the tilt. Keeping a second frame generator only to fake a tilt would have made
the window and the tests disagree, which is the problem this decision closes.

## What the test does not cover

- Real hardware, real 120 fps and the ADR-013 performance budget: that is the
  QE bench and the `video` agent.
- The real SER writer path during a scan; only the dry-run branch runs in CI.
- A machine without PySide6 or without a display, beyond the offscreen start.
