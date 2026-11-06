############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - config schema module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Schema of the configuration and the data model of the profile
# (design/ARCHITECTURE.md 3.2 and 2.4, ADR-003, ADR-012, ADR-024).
#
# config is a support leaf: it imports devices (for the ROI alias only) and
# nothing else from the application, so every layer above can read a setting or
# a profile without dragging an engine or a driver with it. There is no Qt here
# and no engine import.
#
# Two kinds of type, as everywhere in the contract modules (ADR-023):
#   - value types: the schema table, Settings, the profile dataclasses and the
#     session state. Concrete, because everybody must agree on their fields.
#   - behaviour: none here. Reading and writing the INI, the profile and the
#     session state are algorithms and live in config/store.py:
#       load_settings(path) / save_settings(settings, path)
#       load_profile(path) / save_profile(profile, path)
#       load_session_state(path) / save_session_state(state, path)
#     store.py parses the INI booleans with a fixed vocabulary ("true", "yes",
#     "1", "on" and their negatives) so a hand-edited file behaves the same on
#     Windows and on Linux.
#   - session paths: store.py also owns the session folder and the file naming
#     (DESIGN.md 10), so no layer invents its own:
#       session_folder(base_dir, when) -> the session folder, created
#       scan_ser_path(session_dir, base_name, when, scan) -> sun_..._scanNN.ser
#       scan_log_path / scan_stats_path / session_meta_path -> the ADR-018 logs
#       session_state_path(session_dir) -> the session_state.json of that folder
#     Naming files is persistence, not UI business logic: the RowRecorder adapter
#     the UI writes asks store.py for the path of each mosaic row.
#
# Inheritance (ADR-003): the sections marked origin="scan" are nightscribe-scan's
# own, with its exact spelling, section and default, so the user's existing
# nightscribe-scan.cfg keeps working untouched. ADR-024 reconciled the table
# against the prototype's CONFIG_SCHEMA and its cfg reference. New keys are
# added, never renamed; the few SolarScribe names that duplicated an inherited
# behaviour survive only as legacy aliases (LEGACY_KEYS below), and the
# inherited key always wins.
#
# Paths: this module fixes file NAMES, never directories. Where the files live
# is the application's business (platformdirs, config/paths.py), so the
# packaging agent owns the per-platform location (ADR-004, ADR-017).

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from solarscribe.devices.abc import ROI

__all__ = [
    "CONFIG_FILE",
    "CameraData",
    "Key",
    "LEGACY_KEYS",
    "PROFILE_FILE",
    "PROFILE_VERSION",
    "Profile",
    "SCAN_LOG_FILE",
    "SCAN_STATS_FILE",
    "SCHEMA",
    "SESSION_META_FILE",
    "SESSION_STATE_FILE",
    "SESSION_STEPS",
    "SessionState",
    "StepState",
    "StepStatus",
    "TelescopeData",
    "RoiPreset",
    "default_value",
    "keys_of",
    "new_steps",
]

# File names, resolved by the app inside its per-platform config directory.
CONFIG_FILE = "config.ini"
PROFILE_FILE = "profile.json"

# The three logs of the post-processing contract (ADR-018). They live inside the
# SESSION folder; the SER is per scan, these are per session, exactly as the
# prototype writes them, so the existing tools keep reading them.
SCAN_LOG_FILE = "scan_log.csv"
SCAN_STATS_FILE = "scan_stats.jsonl"
SESSION_META_FILE = "session_meta.json"

# The step state lives in the SESSION folder, one per session, and is not
# session_meta.json: that one is the contract with the post-processing
# (ADR-018) and its columns never change shape.
SESSION_STATE_FILE = "session_state.json"

# Profile format. v2 is the JSON shape of ARCHITECTURE 3.2; a file with another
# version is migrated by store.py, never read as if it matched.
PROFILE_VERSION = 2


@dataclass(frozen=True)
class Key:
    # One INI key. The table is data, not code, so a test can assert that every
    # key has a default and a reason, and the settings dialog can be built from
    # it instead of being written by hand.
    section: str
    name: str
    kind: type            # int, float, bool or str: how the INI text is parsed
    default: object       # what an absent or unreadable key means (ADR-003:
                          # every key has a default, so a hand-edited file never
                          # stops the app from starting)
    why: str              # what it controls and why it matters. Shown as the
                          # tooltip of the settings dialog: no figure without an
                          # explanation (AGENTS.md)
    origin: str           # "scan": inherited from nightscribe-scan (ADR-003)
                          # "new": added by SolarScribe


SCHEMA: tuple[Key, ...] = (
    # --- general -------------------------------------------------------------
    Key("general", "language", str, "",
        "Empty means the system language; write 'es' or 'en' to force one "
        "(ADR-016).", "new"),

    # --- observatory ---------------------------------------------------------
    # The Sun's RA/Dec for the automatic GOTO is computed locally from these
    # (ADR-021: no network for ephemerides). Zeroes mean "not set yet": the
    # welcome assistant asks for them, because a wrong place mis-points the
    # telescope by degrees. The prototype took the site from SharpCap, so
    # these keys are ours (ADR-024).
    Key("observatory", "latitude_deg", float, 0.0,
        "Observatory latitude in degrees, north positive. Needed to compute "
        "where the Sun is (ADR-021).", "new"),
    Key("observatory", "longitude_deg", float, 0.0,
        "Observatory longitude in degrees, east positive.", "new"),
    Key("observatory", "elevation_m", float, 0.0,
        "Observatory elevation in metres. Small effect on the ephemeris, but "
        "free to store.", "new"),

    # --- optics (inherited: the scan rate and the arcsec-per-pixel scale) ----
    # At 714 mm focal and 2 um pixels one pixel is 0.578", so a 1920" Sun fills
    # about 3320 pixels along the scan axis. These three figures are the whole
    # geometric model of the prototype, which is why they are inherited.
    Key("optics", "focal_length", float, 714.0,
        "Effective focal length at the sensor, in mm. It sets the arcsec per "
        "pixel along the scan axis and therefore the scan rate. Measure it on "
        "the native recon, not on a resampled stack.", "scan"),
    Key("optics", "pixel_size", float, 2.0,
        "Camera pixel size in micrometres. With the focal length it turns "
        "pixels into arcseconds.", "scan"),
    Key("optics", "sidereal", float, 15.04,
        "Arcseconds per second per sidereal multiplier unit (the ASCOM "
        "standard is 15.04). The mount rate is expressed in these units.", "scan"),
    Key("optics", "use_ephemeris", bool, True,
        "Compute the solar diameter from the date: the ephemeris is local and "
        "about 0.01% accurate (ADR-021), which beats any fixed figure.", "scan"),
    Key("optics", "ephemeris_diameter_override", float, 0.0,
        "Force the solar diameter in arcseconds; 0 means use the ephemeris. A "
        "wrong figure skews the reconstructed disk, so only set it to test.",
        "scan"),
    Key("optics", "solar_diameter", float, 1920.0,
        "Fallback solar diameter in arcseconds when no ephemeris is available. "
        "1920\" is the mean apparent diameter, about 32'.", "scan"),

    # --- camera --------------------------------------------------------------
    # The prototype got exposure and gain from SharpCap; SolarScribe owns them,
    # so these keys are ours (ADR-024).
    Key("camera", "camera_id", str, "",
        "Empty: the first camera found. Otherwise the id reported by discovery, "
        "'<backend>:<serial or index>'.", "new"),
    Key("camera", "exposure_us", float, 1000.0,
        "Exposure in microseconds, the native unit of every SDK we drive. At "
        "120 fps the exposure cannot exceed 8300 us, which is why the ROI step "
        "shows the rate limit.", "new"),
    Key("camera", "gain", float, 0.0,
        "Gain as the SDK's own index, not dB. Each brand scales it differently, "
        "so the value travels with the camera model in the profile.", "new"),
    Key("camera", "offset", float, 0.0,
        "Offset (black level pedestal) as the SDK's index. Keeps the sky above "
        "zero so the reconstruction has no clipped blacks.", "new"),
    Key("camera", "binning", int, 1,
        "Binning factor. 1x1 by default: the SHG needs the full spatial "
        "resolution along the slit (DESIGN.md 6).", "new"),
    Key("camera", "bit_depth", int, 16,
        "Bits per pixel written to the SER. 16 is the contract with the "
        "post-processing (ADR-018).", "new"),
    Key("camera", "readout", float, 0.0,
        "Readout / USB traffic control in SDK units (ZWO: USB traffic %, "
        "Touptek: speed index). 0 leaves the SDK default.", "new"),
    Key("camera", "auto_exposure", bool, True,
        "Legacy SolarScribe name for scan.enable_auto_exp; kept so an old INI "
        "still reads, the inherited key wins (ADR-024).", "new"),

    # --- roi (ADR-010, ADR-022) ----------------------------------------------
    # The capture ROI is in SENSOR pixels and binned; the band is in FRAME
    # pixels. These keys are the last values the observer used, restored when
    # the camera connects; the authoritative record of a take is
    # session_meta.json.
    Key("roi", "preset", str, "default",
        "Name of the profile preset to restore when the camera connects.", "new"),
    Key("roi", "capture_x", int, 0,
        "Left edge of the capture ROI on the sensor, in binned pixels.", "new"),
    Key("roi", "capture_y", int, 0,
        "Top edge of the capture ROI on the sensor, in binned pixels.", "new"),
    Key("roi", "capture_width", int, 3480,
        "Width of the capture ROI. It sets the frame rate and the SER size: "
        "3480x248 is the reference strip that reaches 120 fps (ADR-013).", "new"),
    Key("roi", "capture_height", int, 248,
        "Height of the capture ROI. It must hold the spectral band plus the "
        "tilt drift plus a margin (ADR-022).", "new"),
    Key("roi", "band_x", int, 0,
        "Left edge of the spectral band inside the frame, in frame pixels.", "new"),
    Key("roi", "band_y", int, 40,
        "Top edge of the spectral band inside the frame, in frame pixels.", "new"),
    Key("roi", "band_width", int, 3480,
        "Width of the spectral band, the useful strip of the dispersed "
        "spectrum.", "new"),
    Key("roi", "band_height", int, 160,
        "Height of the spectral band. If it does not fit in the capture ROI the "
        "order is clipped and the ROI step says so.", "new"),
    Key("roi", "tilt_deg", float, 0.0,
        "Last measured tilt of the spectral line, in degrees. A hint for the "
        "next session; session_meta.json holds the authoritative value.", "new"),
    Key("roi", "tilt_px", float, 0.0,
        "Last measured tilt drift across the ROI width, in pixels.", "new"),
    Key("roi", "tilt_max_deg", float, 1.0,
        "Tilt above which the ROI step warns: a tilted line skews the "
        "reconstruction and forces a taller ROI (ADR-022).", "new"),

    # --- mount (ADR-019) -----------------------------------------------------
    Key("mount", "backend", str, "",
        "Empty: the platform default, ASCOM COM on Windows and INDI on Linux "
        "(ADR-019).", "new"),
    Key("mount", "mount_id", str, "",
        "Empty: the first mount found. Otherwise the id reported by discovery.",
        "new"),
    Key("mount", "tracking", bool, True,
        "Track while the session runs. The scan is a rate movement on top of the "
        "sidereal tracking, so tracking off means a smeared disk.", "new"),
    Key("mount", "move_rate_arcsec_s", float, 0.0,
        "Default rate of the N/S/E/W buttons, in arcsec/s. 0 uses the backend's "
        "own default; the panel's selector overrides it.", "new"),

    # --- scan ----------------------------------------------------------------
    # The inherited block is the prototype's single-scan and mosaic behaviour.
    # enable_capture is also the dry run: false writes no SER (DESIGN.md 14).
    Key("scan", "enable_capture", bool, True,
        "Write SER files. False is the dry run: the mount moves and the engine "
        "measures, but nothing reaches the disk.", "scan"),
    Key("scan", "enable_auto_exp", bool, True,
        "Run the auto-exposure loop before and during the scan. The Sun's "
        "brightness changes with seeing and with the filter.", "scan"),
    Key("scan", "num_cycles", int, 3,
        "Scans per session. Inherited spelling; the default is 3 because DESIGN "
        "asks for three cycles, enough to reject a bad one without doubling the "
        "time (ADR-024).", "scan"),
    Key("scan", "padded_duration", float, 3.0,
        "Seconds of sky recorded on each side of the disk, used only when "
        "padded_arcsec is 0. Keeps background in the reconstruction.", "scan"),
    Key("scan", "padded_arcsec", float, 100.0,
        "Fixed arcsec of sky padding per side; 0 falls back to "
        "padded_duration. A fixed angular padding does not depend on the frame "
        "rate, so repeated scans are more repeatable.", "scan"),
    Key("scan", "scan_preload_seconds", float, 0.3,
        "Forward pre-load in seconds before recording starts: it takes up the "
        "RA backlash left by the reverse backup, so the first recorded frames "
        "are already at rate. 0 disables it.", "scan"),
    Key("scan", "trailing_limb_stop", bool, True,
        "Stop recording shortly after the trailing limb leaves the slit "
        "(stddev drop) instead of always writing the full trailing padding.",
        "scan"),
    Key("scan", "trailing_margin_arcsec", float, 50.0,
        "Sky kept after the trailing limb, in arcseconds. Too little and the "
        "reconstruction has no background on that edge.", "scan"),
    Key("scan", "trailing_stddev_fraction", float, 0.15,
        "Trailing threshold as a fraction of the peak stddev. It is what "
        "decides that the Sun has left the slit.", "scan"),
    Key("scan", "return_multiplier", float, 32.0,
        "Sidereal multiplier for the fast slew back to the start. 32x is about "
        "481 arcsec/s, fast enough to make repositioning negligible without "
        "exceeding most mount limits.", "scan"),
    Key("scan", "cycles", int, 3,
        "Legacy SolarScribe name for scan.num_cycles; kept so an old INI still "
        "reads, the inherited key wins (ADR-024).", "new"),
    Key("scan", "padding_s", float, 3.0,
        "Legacy SolarScribe name for scan.padded_duration; kept so an old INI "
        "still reads, the inherited key wins (ADR-024).", "new"),
    Key("scan", "preload_s", float, 0.3,
        "Legacy SolarScribe name for scan.scan_preload_seconds; kept so an old "
        "INI still reads, the inherited key wins (ADR-024).", "new"),
    Key("scan", "adaptive_stop", bool, True,
        "Legacy SolarScribe name for scan.trailing_limb_stop; kept so an old "
        "INI still reads, the inherited key wins (ADR-024).", "new"),
    # Our own scan knobs, which the prototype did not expose.
    Key("scan", "dec_center", str, "auto",
        "'auto', 'symmetry' or 'chord': which fine Dec centring to use when "
        "enable_dec_centering is on (ADR-006). 'auto' picks by the disk fit.",
        "new"),
    Key("scan", "rate_arcsec_s", float, 0.0,
        "Sweep rate in arcsec/s. 0 means the engine calibrates it, which is "
        "what the prototype taught us to trust; a non-zero value forces the "
        "rate and skips calibration.", "new"),
    Key("scan", "rows", int, 1,
        "Rows of a mosaic the observer asks for. One row is a simple scan; with "
        "enable_mosaic on, the planner uses it as a minimum and recomputes from "
        "the slit geometry.", "new"),
    Key("scan", "row_step_arcsec", float, 0.0,
        "Dec step between mosaic rows, in arcseconds. 0 steps one effective "
        "slit height minus the overlap, so the rows tile without a gap.", "new"),

    # --- fps (inherited: the rate is the project's critical number) ----------
    Key("fps", "capture_fps", float, 0.0,
        "Force the capture frame rate; 0 measures it after auto-exposure. The "
        "rate is read after the exposure is final because auto-exposure changes "
        "it: reading it at start made the prototype scan 27% too fast.", "scan"),
    Key("fps", "fps_samples", int, 5,
        "Readings of the camera's reported rate to median. The median rejects "
        "the one-off low reading that a slow frame produces.", "scan"),
    Key("fps", "fps_sample_interval", float, 0.2,
        "Seconds between those readings. At 0.2 s five samples span a second, "
        "long enough to see a stall and short enough not to delay the scan.",
        "scan"),
    Key("fps", "fps_probe_seconds", float, 0.0,
        "Additionally measure the real rate from a real capture of this many "
        "seconds (it writes a small SER labelled fpsprobe); 0 uses the reported "
        "rate.", "scan"),
    Key("fps", "capture_start_timeout", float, 5.0,
        "Seconds to wait for the capture to actually start before giving up. "
        "Starting the scan before the file records loses the leading limb.",
        "scan"),
    Key("fps", "capture_start_settle", float, 0.1,
        "Seconds to settle after the first frame before the mount moves, so the "
        "first recorded frame is not a stationary duplicate.", "scan"),
    Key("fps", "capture_stall_seconds", float, 3.0,
        "Abort the scan if no frames are written for this long; 0 disables the "
        "check. A stalled writer means a lost take, not a slow one (ADR-014).",
        "scan"),
    Key("fps", "frames_short_tol", float, 0.1,
        "Warn when the frames written fall more than this fraction below the "
        "expected rate times duration. A short scan means dropped frames.",
        "scan"),
    Key("fps", "capture_min_free_gb", float, 1.0,
        "Free disk below which a scan does not start, in GB. A full disk "
        "mid-scan loses the take (ADR-014).", "scan"),

    # --- limb (inherited: stddev-based limb detection) -----------------------
    Key("limb", "limb_search_speed", float, 4.0,
        "Sidereal multiplier for the limb search. Fast enough to find the Sun "
        "in a frame or two, slow enough not to overshoot the slit.", "scan"),
    Key("limb", "limb_sample_interval", float, 0.05,
        "Seconds between limb samples. 50 ms resolves the limb crossing well "
        "below the scan rate.", "scan"),
    Key("limb", "limb_max_search", float, 120.0,
        "Seconds before giving up the limb search. Two minutes is long enough "
        "for a manual nudge and short enough to surface a wrong GOTO.", "scan"),
    Key("limb", "limb_stddev_min", float, 500.0,
        "Minimum stddev to call it on-disk. On a MONO16 sensor the dark noise "
        "stddev is about 20 to 100 and the disk is usually above 10000.", "scan"),
    Key("limb", "on_disk_stddev", float, 2000.0,
        "Stddev that clearly means on-disk. Above it the engine decides it does "
        "not need to back off before searching.", "scan"),
    Key("limb", "limb_dark_mult", float, 5.0,
        "The detection threshold is the observed dark stddev times this. It "
        "adapts to the sensor instead of trusting an absolute figure.", "scan"),

    # --- dec (inherited: left/right centring, ADR-006) -----------------------
    Key("dec", "enable_dec_centering", bool, True,
        "Use the left/right Dec centring loop. Turn it off when the disk does "
        "not fit along the slit: the metric loses its zero crossing and the "
        "loop can push the Sun out of the slit.", "scan"),
    Key("dec", "dec_interval", int, 2,
        "Re-centre Dec every N cycles. Recentring is cheap but not free, and "
        "drift between adjacent cycles is small.", "scan"),
    Key("dec", "dec_center_tolerance", float, 0.03,
        "Centred when |L-R|/(L+R) is below this. 3% is inside the noise of the "
        "left/right measurement on a real disk.", "scan"),
    Key("dec", "dec_max_corrections", int, 8,
        "Maximum Dec nudges per centring. Without a cap a bad metric oscillates "
        "forever.", "scan"),
    Key("dec", "dec_nudge_speed", float, 3.0,
        "Sidereal multiplier of a Dec nudge. 3x is about 45 arcsec/s, fine "
        "enough for a small correction.", "scan"),
    Key("dec", "dec_settle_time", float, 0.3,
        "Seconds to settle after a nudge before measuring again. The mount "
        "reports the target before it has arrived.", "scan"),
    Key("dec", "dec_drift_tol_arcsec", float, 10.0,
        "Re-centre Dec between scans of a row when it drifts more than this. "
        "Ten arcseconds is well below the slit height.", "scan"),

    # --- mosaic (inherited: multi-row planning) ------------------------------
    Key("mosaic", "enable_mosaic", bool, False,
        "True runs a multi-row mosaic; false runs a single scan. The switch "
        "also decides which Dec centring path the scan uses.", "scan"),
    Key("mosaic", "mosaic_slit_length_mm", float, 7.0,
        "Physical slit length in mm. It is the hard limit on the spatial axis, "
        "not the sensor: 7 mm at 714 mm focal subtends 33.7', just over the "
        "solar diameter, so one row can cover the whole disk.", "scan"),
    Key("mosaic", "mosaic_slit_image_scale", float, 1.0,
        "Sensor pixels per millimetre of slit, the spectrograph re-imaging "
        "magnification. Set it to slit_pixels * pixel_size / (slit_mm * 1000) "
        "when the slit does not image 1:1, or the row step is off by that "
        "ratio.", "scan"),
    Key("mosaic", "mosaic_overlap", float, 0.15,
        "Fractional overlap between adjacent rows. 15% hides a small pointing "
        "error without wasting rows.", "scan"),
    Key("mosaic", "mosaic_margin_arcsec", float, 100.0,
        "Extra sky above and below the disk, in arcseconds, so the poles are "
        "not at the row edge.", "scan"),
    Key("mosaic", "mosaic_scans_per_row", int, 5,
        "Scans per row, each one a separate SER. More scans let the "
        "post-processing reject the bad ones.", "scan"),
    Key("mosaic", "mosaic_auto_center_dec", bool, True,
        "Centre Dec automatically by chords. The chord method works even when "
        "the disk overfills the slit, which is where the left/right metric "
        "fails.", "scan"),
    Key("mosaic", "mosaic_center_max_iter", int, 3,
        "Chord centring measurement and correction rounds. Three converge on a "
        "real disk; more mostly chase noise.", "scan"),
    Key("mosaic", "mosaic_center_residual_arcsec", float, 300.0,
        "Residual assumed after the chord centring, in arcseconds. It is added "
        "to the plan margin so a small error does not clip a pole.", "scan"),
    Key("mosaic", "mosaic_dec_speed", float, 3.0,
        "Sidereal multiplier for the Dec move between rows.", "scan"),
    Key("mosaic", "mosaic_dec_backlash", float, 30.0,
        "Backlash taken up before each final approach, in arcseconds. Without "
        "it the row lands short by the gear slack.", "scan"),
    Key("mosaic", "mosaic_dec_settle", float, 0.5,
        "Seconds to settle after a Dec move before the row starts.", "scan"),
    Key("mosaic", "mosaic_chord_speed", float, 16.0,
        "Sidereal multiplier for the chord and calibration traverses. Fast "
        "traverses keep the centring short.", "scan"),

    # --- exposure (inherited: percentile auto-exposure) ----------------------
    Key("exposure", "exp_percentile", float, 0.995,
        "Histogram percentile the loop targets. 0.995 ignores a few hot pixels "
        "that would otherwise drive the exposure down.", "scan"),
    Key("exposure", "exp_target_level", float, 0.88,
        "Target level of that percentile as a fraction of full scale. 0.88 "
        "leaves headroom for the continuum peak, which must not clip.", "scan"),
    Key("exposure", "exp_tolerance", float, 0.04,
        "Convergence window as a fraction of full scale. Inside it the loop "
        "stops instead of hunting.", "scan"),
    Key("exposure", "exp_max_attempts", int, 6,
        "Maximum auto-exposure iterations. After six the light is not changing "
        "and more attempts only delay the scan.", "scan"),

    # --- calibration (inherited: scan-rate and consistency) ------------------
    Key("calibration", "calibrate_scan_rate", bool, True,
        "Self-calibrate the scan rate at session start from the measured "
        "limb-crossing time and the solar diameter. It removes the dependence "
        "on trusting the focal length and the reported frame rate.", "scan"),
    Key("calibration", "calibration_samples", int, 1,
        "Calibration traverses to average. One is usually enough; more trades "
        "time for a steadier rate.", "scan"),
    Key("calibration", "consistency_tol_xy", float, 0.03,
        "Warn when the X/Y scale drifts more than this fraction between scans. "
        "A drift means the rate or the pixel scale changed.", "scan"),
    Key("calibration", "consistency_tol_extent", float, 0.03,
        "Warn when the slit extent drifts more than this fraction between "
        "scans. It catches a focus or pointing change.", "scan"),
    Key("calibration", "scan_retries", int, 1,
        "Retries of a scan that failed (stall, short, limb lost). The failed "
        "attempt stays in the log with a problem tag.", "scan"),
    Key("calibration", "cos_dec_correction", bool, True,
        "Apply the 1/cos(Dec) RA-rate correction in both modes, so the X scale "
        "is the same at any declination.", "scan"),
    Key("calibration", "measure_slit_extent", bool, True,
        "Measure the illuminated extent along the slit in the live frame. It "
        "estimates the slit-axis plate scale and flags a scan that missed the "
        "disk.", "scan"),
    Key("calibration", "slit_extent_bands", int, 48,
        "Bands of the slit extent profile. Enough to see the disk edge, few "
        "enough to stay cheap per frame.", "scan"),

    # --- capture budget (ADR-013, ADR-014) -----------------------------------
    Key("capture", "queue_budget_mb", float, 512.0,
        "Ceiling of the recording queue. Bounded on purpose: a slow disk costs "
        "counted frames, never a stalled capture thread.", "new"),
    Key("capture", "target_fps", float, 120.0,
        "Sustained rate the ROI must reach (ADR-013). The ROI step estimates "
        "the rate of the chosen strip and warns below this figure.", "new"),
    Key("capture", "stall_timeout_s", float, 3.0,
        "Legacy SolarScribe name for fps.capture_stall_seconds; kept so an old "
        "INI still reads, the inherited key wins (ADR-024).", "new"),
    Key("capture", "min_free_disk_gb", float, 1.0,
        "Legacy SolarScribe name for fps.capture_min_free_gb; kept so an old "
        "INI still reads, the inherited key wins (ADR-024).", "new"),

    # --- session -------------------------------------------------------------
    # The prototype let SharpCap choose the folder; SolarScribe owns it.
    Key("session", "session_dir", str, "",
        "Base folder for the session folders. Empty uses the platform default "
        "(config/paths.py). One folder per session, named with its date and "
        "time (DESIGN.md 10).", "new"),
    Key("session", "base_name", str, "sun",
        "Prefix of the files: sun_YYYYMMDD_HHMM_scanNN.ser with its .csv and "
        ".jsonl (DESIGN.md 10).", "new"),
    Key("session", "autosave", bool, True,
        "Save the step state silently after every change, so a crash or a "
        "closed laptop loses nothing (ADR-011).", "new"),

    # --- logging (inherited: the post-processing looks for these files) ------
    Key("logging", "scan_log_path", str, "",
        "CSV with one row per scan. Empty means the session folder, which is "
        "where the post-processing looks (ADR-018).", "scan"),
    Key("logging", "scan_stats_path", str, "",
        "JSON lines with one sample per scan. Empty means the session folder.",
        "scan"),
    Key("logging", "session_meta_path", str, "",
        "JSON with the effective configuration and the plan, for reproducing "
        "the session. Empty means the session folder.", "scan"),

    # --- polar alignment (ADR-007) -------------------------------------------
    Key("polar", "sample_interval_s", float, 180.0,
        "Seconds between two samples of the Sun's Dec. Shorter samples do not "
        "help: the drift is slow and the measurement noise dominates.", "new"),
    Key("polar", "session_minutes", float, 30.0,
        "How long the assistant spreads its samples. 20 to 40 minutes is what "
        "separates the azimuth error from the altitude error (ADR-007).", "new"),
)

# SolarScribe names that predate the reconciliation and duplicate an inherited
# key (ADR-024). The pair is (legacy, canonical). The canonical key owns the
# behaviour; the legacy one is read only when the canonical key is absent from
# the file, and store.py mirrors the resolved value back so an old caller keeps
# seeing the truth. save_settings writes the canonical name alone.
LEGACY_KEYS: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = (
    (("scan", "cycles"), ("scan", "num_cycles")),
    (("scan", "padding_s"), ("scan", "padded_duration")),
    (("scan", "preload_s"), ("scan", "scan_preload_seconds")),
    (("scan", "adaptive_stop"), ("scan", "trailing_limb_stop")),
    (("capture", "stall_timeout_s"), ("fps", "capture_stall_seconds")),
    (("capture", "min_free_disk_gb"), ("fps", "capture_min_free_gb")),
    (("camera", "auto_exposure"), ("scan", "enable_auto_exp")),
)


# @args: section - an INI section name; include_legacy - also list the aliases
# @return: the keys of that section, in schema order, for the settings dialog.
#          Aliases are hidden by default: the dialog shows one control per
#          behaviour, not a control and its old name (ADR-024)
def keys_of(section: str, *, include_legacy: bool = False) -> tuple[Key, ...]:
    aliases = {legacy for legacy, _ in LEGACY_KEYS}
    return tuple(
        key for key in SCHEMA
        if key.section == section
        and (include_legacy or (key.section, key.name) not in aliases)
    )


# @args: section - an INI section; name - a key inside it
# @return: the key's default. Raises KeyError for a key that is not in the
#          schema, because a typo in a key name must fail loudly, not read as 0
def default_value(section: str, name: str) -> object:
    for key in SCHEMA:
        if key.section == section and key.name == name:
            return key.default
    raise KeyError(f"{section}.{name} is not in the schema")


@dataclass(frozen=True)
class TelescopeData:
    # The optics, from the single profile (DESIGN.md 10).
    #
    # The reference instrument is the SHG-700: 714 mm focal and a 7 mm slit.
    # The slit figure is its LENGTH, and the geometry says why it is that size:
    # 7 mm at 714 mm focal subtends 7/714 rad = 33.7', just over the solar
    # diameter of about 32', so one row of a scan can cover the whole disk. The
    # slit WIDTH (the spectral resolution) is not stored: capture does not need
    # it, and inventing a figure here would be worse than leaving it out.
    focal_length_mm: float = 714.0
    aperture_mm: float = 80.0
    slit_length_mm: float = 7.0


@dataclass(frozen=True)
class CameraData:
    # The camera the profile was made for. The pixel size and the binning are
    # what turn pixels into arcseconds, so the scan rate and the mosaic step
    # depend on them.
    model: str = ""
    pixel_size_um: float = 2.0
    binning: int = 1


@dataclass(frozen=True)
class RoiPreset:
    # A ROI preset per camera and optic, persisted in the profile and restored
    # when the camera connects (ADR-010).
    #
    # Only the two rectangles the observer edits are stored: the sensor limits
    # come from the camera at runtime and the analysis sub-regions are computed,
    # never saved. `capture` is in SENSOR pixels and `band` in FRAME pixels, the
    # same convention as capture's RoiModel, which is why a preset converts into
    # a model without arithmetic.
    name: str = "default"
    capture: ROI = (0, 0, 3480, 248)
    band: ROI = (0, 40, 3480, 160)


@dataclass(frozen=True)
class Profile:
    # The single profile (DESIGN.md 10): telescope data, camera data and the ROI
    # presets. JSON v2, the shape of ARCHITECTURE 3.2, so a hand-written file is
    # as valid as one the app saved.
    version: int = PROFILE_VERSION
    telescope: TelescopeData = field(default_factory=TelescopeData)
    camera: CameraData = field(default_factory=CameraData)
    roi_presets: tuple[RoiPreset, ...] = (RoiPreset(),)

    # @args: name - the preset name, as chosen in the ROI step
    # @return: the preset, or None when the profile has no such name
    def preset(self, name: str) -> RoiPreset | None:
        for item in self.roi_presets:
            if item.name == name:
                return item
        return None


class StepStatus(Enum):
    # State of a session step on the rail (ADR-011). The values are the ones the
    # rail paints; SKIPPED exists because navigation is free and the expert user
    # jumps steps without the app pretending they happened.
    PENDING = "pending"
    CURRENT = "current"
    DONE = "done"
    SKIPPED = "skipped"


# The four steps, in rail order (ADR-011): find the Sun, polar alignment, ROI and
# scanning. The spellings are the keys of SessionState.steps and of the saved
# JSON, so they never change without a migration.
SESSION_STEPS: tuple[str, ...] = ("find_sun", "polar", "roi", "scan")


@dataclass
class StepState:
    # State of one step.
    #
    # `metrics` holds numbers only, keyed by stable names ("tilt_deg",
    # "rate_arcsec_s", "dec_error_arcsec"...). The step's text is built by the UI
    # with self.tr() around those numbers (ADR-016), because a sentence stored in
    # a file cannot be translated later and a number without its label means
    # nothing to the observer.
    status: StepStatus = StepStatus.PENDING
    updated_at: str = ""      # ISO-8601 UTC of the last change
    metrics: dict[str, float] = field(default_factory=dict)


# @return: a fresh step map with every step pending, used as the SessionState
#          default and by store.py when a saved file misses a step
def new_steps() -> dict[str, StepState]:
    return {step: StepState() for step in SESSION_STEPS}


@dataclass
class SessionState:
    # Persistent state of the four steps, saved in the session folder as
    # session_state.json and restored silently (ADR-011: auto-save and "reopen
    # step").
    #
    # It is not session_meta.json: that file is the contract with the
    # post-processing (ADR-018) and holds the effective ROI, the tilt, the app
    # version and the drop counters. This one is the app's own memory of where
    # the observer is.
    steps: dict[str, StepState] = field(default_factory=new_steps)
    session_dir: str = ""     # the session folder, "" before the first save
    created_at: str = ""      # ISO-8601 UTC
    updated_at: str = ""      # ISO-8601 UTC
