# SolarScribe UI: usability task script and result

Owner: `ux`. Gate: G4 of `AGENTS.md`. Date: 2026-11-06 (ADR-026 rework).

This is the script the `qe` agent executes and the record of its last run. It is
written for a newcomer: no vocabulary from the design documents, no step that
needs a hidden control. The automated version is
`tests/unit/test_ui_usability.py`.

## Environment

- `QT_QPA_PLATFORM=offscreen`, Linux, PySide6 6.12, Python 3.12.
- Reference window 1280 x 820. The live viewer is 558 px tall (68% of the
  window) with the histogram open; the profile bar is 32 px, the step indicator
  28 px, the histogram strip 80 px, the side card 280 to 320 px, and the right
  band is capped at 210 px. The spectrum panel, when shown, is 220 px inside
  the video row.
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

1. In the right band, open the Camera tab (tabbed with Stream health).
2. Press "Find"; the simulator is always found, a native camera only when its SDK is installed.
3. Choose the simulator and press "Open".
4. Read the live model, sensor, ROI and rate; the state line says "Simulator".

Pass when the state line says Simulator, the stream is running, and the model,
sensor, ROI and rate are all filled in. The camera panel is closable; reopening
it from Tools, Panels must bring it back.

### T1. First run: tell the app where you observe (budget 10 s)

1. Open the app for the first time.
2. The welcome assistant opens as a compact first-run dialog, not as a permanent
   block above the window. It says why the position matters: without it the GOTO
   cannot compute where the Sun is.
3. Type the latitude and the longitude.
4. Press "Save and start".

Pass when the dialog closes, the values are stored, and the main window is not
left with a permanent position block. The position stays reachable in Settings.

### T2. Free navigation on the slim rail (budget 5 s)

1. From the first run, click "5. Scan" on the 28 px rail.
2. Click "1. Find Sun" again.

Pass when both clicks change the side card immediately, no question is asked,
and "Find the Sun" still shows as pending. The rail guides; it does not gate.
The status word ("Pending", "In progress", "Done", "Skipped") is on the same
line as the step name, not in a second 32 px row.

### T3. Find the Sun (budget 30 s)

1. In the telescope panel on the right, press "Connect" if it is not connected.
2. Press the primary action "Point at the Sun and centre".
3. Watch the live reading: the coarse then fine centring, the Dec error and
   the centring limit.

Pass when the step shows Done, the real `SunCenteringImpl` has run, the Dec
error is in arcseconds and the "Centring limit" row shows the dead zone that
method leaves. On the simulator the value is labelled as simulated. The
telescope panel shows no RA/Dec readout and no GOTO coordinate fields: the Sun
is the target, and the status bar says the tracking state.

### T4. Polar alignment (budget 30 s)

1. Click "2. Polar" on the rail.
2. Press "Start the measurement".
3. Wait for the first result. The step shows the azimuth and altitude errors in
   arcminutes.
4. Press "Take the confirmation measurement".

Pass when the step shows Done, both measurements agree, and the second button
was clearly disabled until the first measurement finished.

### T5. Focus: three focusers and the slit tilt (budget 30 s)

1. Click "3. Focus" on the rail.
2. Read the three groups. Each figure is live and carries the running best
   since the last reset: spectrograph line contrast and line sharpness;
   collimator edge sharpness and edge wobble; telescope detail contrast, detail
   sharpness and detail count. Every caption has a tooltip that says what the
   figure means and which way is better.
3. Press "Measure the slit tilt". Read the tilt in degrees and pixels of drift,
   and the ROI height it needs: band + drift + margin.
4. If the tilt is not near zero, rotate the slit and measure again. If the edge
   is irregular, the step says so instead of trusting the number.
5. Press "Reset the best values" before comparing a new focuser position.

Pass when the three groups update from the live frames, the tilt reaches the Dec
axis (within 0.5 deg with a straight edge) and the step shows Done, the tilt
carries its units, and the ROI height arithmetic names the band, the drift and
the margin. The Focus step does not gate the scan: a tilted slit is allowed, but
the ROI must then be taller.

### T6. ROI (budget 25 s)

1. Click "4. ROI" on the rail.
2. Read the tilt the Focus step already measured, or press "Measure tilt" for a
   quick check; the guided alignment lives in Focus.
3. Drag the spectral band on the video, or type its numbers.
4. Read the rate estimate, with its target.
5. Press "Apply this ROI".

Pass when the step shows Done, the warnings say "No problems found", and the
capture strip and the band are the ones on screen. The frame is already the
capture ROI, so the band is dragged and the capture strip is typed; the short
sentence on the card says why, and the long explanation is in its tooltip.

### T7. Histogram, open by default (budget 20 s)

1. Under the video, find the histogram already open, compact and bounded.
2. Read the 256 log-scaled bars; the header has the clipping sentence.
3. Read the two levels under the bars ("black 1200", "white 54000") and the
   saturation sentence in the header.
4. Click near the white handle; it moves to the click. Drag it; the picture
   follows and the brightness combo changes to "Manual".
5. Press the header; the strip folds and the video grows. Press it again to
   bring the histogram back.

Pass when the bars come from the spectral band only (their pixel count matches
the band, not the frame), the handles never cross, the clipped ends are shaded,
and the saturation sentence has a tooltip that explains why clipping matters.

### T8. Scanning with the foldable progress strip (budget 90 s)

1. Click "5. Scan" on the rail.
2. Read the plan once Prepare has computed it: mode, rows, duration, rate and
   frames.
3. Press "Prepare the scan". Wait for "Ready" with the Dec error and the rate.
4. Press "Start the scan". The scan strip opens by itself and its toggle is
   disabled: it cannot be folded away while the scan runs.
5. Watch the captured strip, the slit line, the cycle counter and the
   percentage in the strip header; the histogram stays visible.
6. At the end, read the result and the quick recon, and open the data folder.

Pass when the step shows Done, the real `ScanEngineImpl` has run the configured
cycles, the result names the frames and the duration, the percentage reaches
100%, and `shg.quick_recon` has painted a preview that is labelled light and
non-authoritative. A failed preview explains `no_frames`, `band_empty` or
`low_contrast` in plain words. The fixed 130 px box is gone: the strip is open
and locked while the scan runs, and can be folded again when it ends.

### T9. A mistake is explained, not blocked (budget 10 s, inside T6)

1. In the ROI step, set the capture height to 100 while the band is 160 tall.
2. Read the warning.

Pass when the warning starts with "Cannot scan", contains 100, 160 and 162, and
says whether to straighten the line or make the ROI taller. The Scanning step
still opens; only the scan action is disabled, with its tooltip explaining why.

### T10. Reopen a completed step (budget 10 s)

1. Click the "4. ROI" chip, which shows Done.
2. Press "Reopen this step".
3. Confirm the chip now says In progress and the previous tilt is still shown.

Pass when reopening keeps the saved numbers and opens the step again. The button
only appears on a completed step, so a pending step is not confused with a
reopened one.

### T11. No session ceremony (budget 5 s)

1. Open the File menu.
2. Confirm there is no "New session" and no "Open session…".
3. Confirm "Open data folder" and "Quit" are there.

Pass when the data folder is one click away and the user is not asked to create
or name a session before scanning. Tools, Panels must reopen a closed camera,
telescope or stream-health panel.

### T12. The image owns the window (budget 10 s)

1. Open the window at 1280 x 820 with no camera.
2. Look at how much height the video gets.
3. Collapse the telescope panel from Tools, Panels.
4. Maximise the window.

Pass when the viewer is more than half the window, the rail is at most 28 px,
the side card is at most 320 px, the right docks are capped at 210 px, the
histogram starts open, the scan strip starts folded, the profile bar shows the
active name, the collapsed telescope panel leaves no empty column, and
maximising gives the extra space to the image. There is no latitude/longitude
block in the permanent chrome.

### T13. Identify the spectral lines (budget 10 s)

1. Open Settings, Spectrum and set the dispersion in angstroms per pixel and
   the target line (H-alpha 6562.81 Å by default).
2. In the video toolbar, check "Identify lines".
3. The panel opens to the right of the video. Read the anchor and the confidence
   on top, then the list: name, wavelength in Å and row in the frame. Telluric
   lines are marked as such.
4. Uncheck "Identify lines": the panel closes and the video grows back.

Pass when a valid dispersion and a real spectrum name the lines sorted by row;
with the dispersion at 0 the panel says identification is off and points to
Settings; with no spectrum, no line or no match it says so; with a confidence
below the minimum it hides the names and says they are not trustworthy. The
panel never draws on the video.

### T14. The active profile (budget 10 s)

1. At startup, read the profile bar: `Profile [name]`, the selector, `Save as…`
   and `Manage…`, with the one-line explanation of what a profile stores.
2. Open the selector and choose another named profile (with the named profile
   store present). Read the status: the optics, camera data and ROI presets are
   loaded; the camera stays connected.
3. Press `Save as…`, type a name; the bar shows it active.
4. Press `Manage…`: the list marks the active profile and offers `Use this
   profile`, `Rename…` and `Delete`.
5. Close and reopen the app; the active profile is the one loaded and shown.

Pass when the active profile is visible at startup, switching loads its optics
and ROI presets, `Save as…` makes the new name active, `Manage…` renames and
deletes, and the camera and mount are never restarted by a profile change. Before
the named store lands the bar shows `Default` and the actions say the named
store is not available; that is the fallback, not a silent lie.

## Per-feature task scripts

The whole-session script above is the gate. These shorter scripts cover each
feature on its own; the automated tests named after each one already check the
same pass criteria.

| Feature | Budget | Task | Pass when |
| --- | ---: | --- | --- |
| Camera panel | 10 s | Find the cameras, choose the simulator, press Open. | The model, sensor, ROI and rate are live; the state line says Simulator; close empties the video and leaves the session alone. |
| Theme and first impression | 5 s | Open the app. Find the one action the first step asks for. | The amber primary button is the most prominent control, no widget is light grey, the title is SolarScribe and the sun icon is in the window. |
| Slim step rail | 5 s | Click the last chip, then the first. | The card changes at once, no question is asked, a pending step is still clickable, and the chip is one line of at most 28 px with the status word. |
| Live viewer | 15 s | Change the brightness preset, scroll to zoom, drag the image, toggle Grid and Slit cross, press Fit. | The picture and the histogram handles change, the zoom readout follows, the drag pans only when zoomed, and Fit returns to 1x. |
| Histogram strip | 20 s | Read the open strip, click the nearest handle, drag it, fold it and reopen it. | The bars are log-scaled and come from the spectral band, the clip zones are shaded, the white never crosses the black, the saturation sentence is present, and the video grows when folded. |
| ROI editor | 20 s | Drag the band, type the capture strip, measure the tilt, read the scale and the rate, press Apply. | The band follows the pointer in frame pixels, the warnings carry their numbers, Apply sends only a valid ROI, and Start stays off until then. |
| Focus step | 20 s | Open Focus, read the three groups with their best, press Measure the slit tilt, read the tilt and the ROI height, press Reset. | The metrics are live and carry their meaning in tooltips, the tilt has deg and px, the ROI height arithmetic names band, drift and margin, and the step is done only when the tilt is parallel to Dec with a straight edge. |
| Profile bar and manager | 10 s | Read the active name at startup, switch a profile, save a new one, open Manage and rename/delete. | The active profile is visible; switching loads optics and ROI presets without restarting the camera; the manager marks the active and refuses to delete the last profile. |
| Line identification panel | 10 s | Set the dispersion and target line, check Identify lines, read the anchor, confidence and list, uncheck. | The panel is to the right of the video, sorted by row, each row is name + wavelength Å, telluric lines are marked; low confidence hides the names; no dispersion or no spectrum says why; the toggle shows and hides it. |
| Telescope panel | 20 s | Connect, press Go to the Sun, nudge N/S/E/W, toggle tracking, Park, Stop. | Every remaining control calls the mount, each failure is a sentence, Stop is always reachable while connected, and the panel folds from Tools, Panels. |
| Scan visualisation and quick recon | 30 s | Prepare, start, watch the strip and the percentage, fold the strip, pause, resume, stop. | The shaded strip and the slit line follow the percentage, the header keeps it when folded, the quick recon fills in, and Open data folder works. |
| Welcome assistant | 10 s | Read the banner, type the position, press Save and start. | The banner closes, the values are stored, and the GOTO can now compute the Sun. |
| Settings | 10 s | Open Settings, filter "exposure", hover the field, change it, save. | The filter narrows the form, the tooltip is the schema's explanation, and the value survives a restart. |
| Logs | 5 s | Open Tools, Logs; choose Errors only; press Reload. | The path and the filtered lines are visible; a missing file says so and still shows where it will be. |
| Sky calendar, Sun tab | 5 s | Open Tools, Sky calendar. | Date, diameter, RA, Dec, north pole angle P and the heliographic centre B0/L0 are shown with units; the disk is drawn without a network. |
| CLI | 5 s | Run `--dry-run` and `--diagnostics`. | The dry run writes nothing, names the ROI and its findings, and exits 1 on an error; the diagnostic lists the paths, the backends and their reasons, and no Qt is imported. |

Automated coverage: `test_ui_theme.py`, `test_ui_steps.py`, `test_ui_viewer.py`,
`test_ui_roi_editor.py`, `test_ui_telescope_panel.py`, `test_ui_scan_view.py`,
`test_ui_dialogs.py`, `test_ui_polar.py`, `test_ui_main_window.py`,
`test_ui_camera.py`, `test_ui_spectrum_panel.py`, `test_ui_profiles.py`,
`test_ui_usability.py` and `test_cli_modes.py`.

## Result of the last run

Measured on the simulator, in the order above:

| Task | Budget | Measured |
| --- | ---: | ---: |
| Camera discovery and open | 10 s | 0.04 s |
| Free navigation | 5 s | 0.00 s |
| Welcome | 10 s | 0.00 s |
| Find the Sun | 30 s | 8.60 s |
| Polar alignment | 30 s | 4.04 s |
| Focus, three focusers and slit tilt | 30 s | 0.04 s |
| ROI | 25 s | 0.14 s |
| Scanning, 3 real cycles | 90 s | 20.91 s |
| Reopen step | 10 s | 0.00 s |
| **Total** | | **33.78 s** |

The two new feature tasks also pass inside their budgets: the image-first layout
and the collapsible panels in under 10 s, and the foldable histogram with a
handle click in under 20 s. The automated test prints no separate timing for
them, but the assertion includes the budget.

The profile bar is covered by `test_ui_profiles.py`: the adapter reads and
writes the real `profiles.json` API of ADR-027 in a temporary folder, the
manager lists and uses a profile, and the window loads the active name at
startup. The fallback with no named store still shows the single `default`
profile and says so.

The line identification panel is covered by `test_ui_spectrum_panel.py`: the
synthetic H-alpha window names H-alpha, Fe I 6569.224 and Fe I 6575.037 at rows
500, 564 and 622, the low-confidence case hides the names, and the
no-dispersion and no-spectrum states say what to do. The test asserts the whole
task in under 5 s.

Verdict: **pass**. All five steps reach Done without a modal dialog, and the
state is on disk without pressing Save. The camera is opened through
`DeviceManagerImpl`; `CaptureEngineImpl` streams it; the Find step runs
`SunCenteringImpl`; the Scanning step runs `ScanEngineImpl` for three cycles and
rewinds the mount between them; `shg.quick_recon` paints the preview; the polar
task runs the real `PolarAlignmentSession` on simulated Dec samples and waits
for a confirmation inside 60 arcsec.

## Friction points found and fixed

1. **The GOTO fields chased the mount.** The panel refreshed the RA/Dec inputs
   from `position()` every 750 ms, so typing a coordinate was impossible and
   `Sync` always sent the current position. Fixed: the fields were inputs, the
   live readout above was the mount. ADR-026 later removed both, because a solar
   observer does not use them.
2. **The ROI text promised a drag that does not exist.** The step said "draw it
   on the video" while only the spectral band can be dragged (the frame is
   already the capture ROI). Reworded: draw the band, type the capture strip,
   and the text says why.
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
13. **The Tools dialogs could open twice.** Logs, Sky calendar and ROI manager
    now reuse their window and raise it.
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
    viewer and the histogram, so the status and the picture agree.
19. **The quick recon was a downsampled band slice.** It now runs
    `shg.quick_recon` over the scan frames, updates while the sweep advances and
    explains `no_frames`, `band_empty` and `low_contrast`.
20. **The window and the tests used two simulators.** The UI `SolarScene` and
    `SceneCamera` were removed; the window now binds the same first-class
    `SimCamera(pattern="solar")` the tests and bench use.
21. **The rail ate 333 px of the window.** The placeholder's maximum height was
    not carried by `replace_widget`, so the `StepRail` expanded instead of
    staying at 28 px; the real rail is now pinned to 28 px. The viewer went from
    345 px to 650 px before the profile bar and the open histogram; with both it
    is 558 px (68% of the window) and the docks no longer eat the width.
22. **The telescope panel could not shrink below 290 px.** The three N/S/E/W
    buttons asked for 80 px each. They are now 38 px wide (the letters are short
    and the tooltips explain them), Stop is 56 px and the panel fits in the
    210 px right band.
23. **The histogram read the whole frame.** The dark rows outside the spectral
    band dominated the count. It now receives `frame.cut_roi(band)` and its
    pixel count matches the band, not the frame.
24. **The spectrum magnifier duplicated the viewer zoom.** It was removed; the
    viewer zoom, the ROI overlay and the band histogram cover its job, and its
    90 px went back to the image.
25. **The scan result was a fixed 130 px box.** It is now a bounded strip with
    the captured disk and the quick recon; its header carries the percentage and
    the cycle, it opens by itself when a scan starts, and it is locked open for
    the duration of the run.
26. **The left card was a wall of prose.** Each step now shows a title, one
    short sentence, its live readings and one primary action; the long
    explanations moved to tooltips and the card fits in 280 to 320 px with
    tighter spacing and vertical scrolling.
27. **The telescope panel carried controls a solar observer never uses.**
    Coordinate GOTO, Sync, Abort slew and the live RA/Dec group were removed;
    Go to the Sun, N/S/E/W, Stop, tracking and park remain. The mount contract
    keeps the rest for the engines.
28. **The 64 px rail was an indicator pretending to be a page.** It is now one
    28 px line with the status word, and the image gets the difference.
29. **The File menu made the user manage a session.** New session and Open
    session are gone; the data folder is still one click away under Open data
    folder, and the flow is open camera, point, ROI, scan.
30. **A folded strip was not discoverable.** The header is always visible, with
    an arrow and a sentence in its tooltip; the scan header also keeps the live
    percentage, so folding it does not hide the progress.
31. **Focus was a Tools dialog that measured nothing live.** It is now the
    Focus step: the three `shg.focus` groups with their running best, the
    `shg.tilt` slit alignment and the ROI height arithmetic. The old
    `Tools → Focus aid…` entry is gone.
32. **The tilt lived in a corner of the ROI step.** The guided alignment moved
    to Focus; the ROI step keeps a quick measure because the strip height needs
    it and free navigation can jump straight there.
33. **The focus metrics could run at video rate.** They are throttled to 4 Hz
    and only while the Focus step is open, so the 288 block means never compete
    with the capture thread.
34. **A running best without a reset is meaningless.** The step has "Reset the
    best values"; the hold is the comparison the observer needs while touching
    a focuser.
35. **The line identification had no UI.** `shg.spectrum` could name the lines,
    but the observer had no way to see the names. The panel lists them to the
    right of the video, with the anchor and confidence on top, and the toolbar
    check shows or hides it.
36. **The identification could not run on the GUI thread or on the live frame.**
    The worker receives a copied 1D profile and drops an older request, so a
    slow match never blocks capture and never reads a recycled frame.
37. **A low confidence could still show wrong names.** The panel hides the table
    and says the naming is not trustworthy, instead of presenting a guess.
38. **The right band was still 210+ px and the spectrum side 260 px.** Both were
    capped: the docks at 210 px (hard maximum, so maximising cannot widen them),
    the spectrum panel at 220 to 260 px, and the camera content was compacted
    (Open/Close, short simulator state, 6 px margins).
39. **The welcome block with latitude and longitude was permanent chrome.** It
    was moved to a compact first-run dialog; the permanent top bar is now a
    32 px profile strip. The position stays in Settings and in the welcome
    assistant, as the user asked.
40. **The left card clipped the tilt/measure row at 250 px.** The side card is
    now 280 to 320 px with 4 px page spacing, 6 px group padding, and a ban on
    the horizontal scrollbar; every field fits at 1280 and maximised.
41. **The histogram started folded.** It now starts open, compact and bounded to
    80 px, so it is always visible without taking the image.
42. **The scan strip could be folded away mid-scan.** It opens by itself, and
    its toggle is disabled until the run ends; the histogram stays visible.
43. **The profile concept was invisible.** The top bar shows the active profile
    by name, a selector, Save as and Manage, with the one-line meaning; the
    active profile is loaded at startup and the manager explains/renames/deletes.

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
6. **The named-profile store is pending from the `lead`.** The UI talks to
   `ui/profiles.py`; without the API it shows one `Default` profile and says the
   named store is unavailable. The exact functions are listed in DESIGN 9.4.
7. **The rail has no keyboard shortcuts.** The chips are standard tab-focusable
   buttons, but Alt+1 to Alt+4 would make the free navigation faster.
8. **Camera discovery probes native backends on a worker thread, but the
   simulator is the only camera available in CI.** A real Touptek, ASI, QHY or
   Player One has not been opened through the panel.
9. **The first-class solar pattern fixes the spectral band at the reference
   rows.** The default ROI band 40..200 matches it. Moving the band in the
   simulation shows a mismatch that real optics would not have, because the
   grating fixes where the spectrum lands.
10. **The histogram handles are mouse-only.** They respond to a click and a
    drag, but there is no keyboard nudge (arrow keys) and no numeric black and
    white fields yet. The brightness presets and the manual combo are the only
    keyboard path.
11. **The saturation threshold is a UI choice.** The header warns above 0.1% of
    the band at the top 0.5% of the range. That is deliberately conservative for
    a solar spectrum; it is not calibrated per camera or per exposure.
12. **The folded state is not remembered.** The histogram and the scan strip
    start folded on every launch, even if the observer always opens them.
13. **The telescope panel no longer shows RA/Dec or offers Sync.** That is the
    ADR-026 decision, but an advanced mode for a non-solar target or a manual
    sync has no home yet.
14. **A maximised window has not been measured on real hardware.** The
    offscreen layout test confirms the viewer takes the extra height; the real
    window manager, a HiDPI screen and a 13 inch laptop are still untested.
15. **The focus metrics are not calibrated against a real SHG-700.** The
    numbers are the prototype's definitions and the simulator's synthetic band;
    a real instrument must establish the thresholds and the "good enough"
    values for each focuser.
16. **The tilt tolerance is a UI choice.** 0.5 deg and an edge residual of at
    most 1.5 px are the rules the app applies; the ROI height arithmetic is the
    objective part, and the scan is never gated by the tilt.
17. **The three focusers interact.** The step shows the figures but does not
    compute a single "in focus" score, because the prototype's routine is
    iterative and a single number would hide which focuser to touch.
18. **The best values live only in memory.** A restart or a step reopen starts
    a fresh comparison; the holds are not saved in the session state.
19. **The anchor is the strongest dip when the target line is not located.**
    That is the MVP assumption: if the grating is not tuned where the config
    says, the names slide. The panel shows the anchor and says it is a pattern
    match, not a calibration.
20. **The dispersion is an input, not a measurement.** The panel cannot compute
    it; the observer sets it in Settings, and the names are only as good as
    that figure.
21. **Telluric lines are marked but the Doppler shift is not removed.** A line
    can sit a few hundredths of an angstrom from its rest wavelength; the
    table's tooltip gives the residual for each name.
22. **The panel updates at 2 Hz.** A fast focuser or grating change can lag by
    up to half a second; the queue always keeps the newest profile.
23. **The panel is off by default and its state is not remembered.** The
    observer checks "Identify lines" each time; the off state keeps the image
    wide.
24. **Switching a profile does not restart the camera or move the telescope.**
    That is intentional; the observer applies a ROI preset if the strip changed.
    The status message says so.
25. **The profile optics and the Settings optics can both exist.** The profile is
    the instrument setup; the Settings `[optics]` keys are the older path. The
    `lead` should reconcile them when the named store lands.
26. **The profile bar is always visible.** It costs 32 px; the user asked for
    the profile to be obvious at startup, and the image gained far more by
    removing the old 150 px welcome block.
27. **The welcome dialog still asks for latitude and longitude.** That is the
    first-run assistant the user allowed; it is not in the permanent chrome and
    it can be dismissed.
28. **The camera model name can still be long.** At 210 px the simulator fits;
    a long real model elides in the combo/value with its tooltip. The compact
    camera panel is a trade-off for the image.

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
- A real window manager, a maximised window and a HiDPI screen.
