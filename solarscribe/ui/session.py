############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui session module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The session the window paints: four steps, two rectangles and the settings.
#
# The rule of ARCHITECTURE 2.4: the session state does NOT live in ui (ADR-023).
# It is config.schema.SessionState, saved by config/store.py as
# session_state.json in the session folder, and this class is only the live
# handle the widgets share:
#   - it keeps the state, the RoiModel and the Settings in one place;
#   - it translates a click into a state change and autosaves silently;
#   - it never computes science. ROI validation is capture's, the tilt is shg's,
#     the scan is shg's; when those modules are missing the session says so and
#     the simulator fills in (demo.py).
#
# Persistence is not duplicated here: config/store.py reads and writes the INI,
# the profile and the session state, and config/paths.py says where they live.
# This module only decides WHEN to call it (after a change, silently).
#
# Free navigation is a rule, not a preference (ADR-011): select_step() always
# works, a step is never a gate. Recommendations are a sentence the window
# composes from recommended_step().

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from solarscribe.capture.abc import RoiModel, RoiWarning
from solarscribe.capture.roi import model_to_preset, preset_to_model, validate_roi
from solarscribe.config import paths, store
from solarscribe.config.schema import (
    SessionState,
    StepState,
    StepStatus,
)
from solarscribe.config.store import Settings
from solarscribe.devices.abc import DeviceError, RoiConstraints

from .roi_checks import validate_roi_model

__all__ = ["Session"]

# Roi constraints used until a camera connects. They are generous on purpose:
# flagging a real camera's limits without the camera would be a lie, so the
# fallback only catches "outside any sensor" mistakes. The real constraints
# replace them the moment the camera is opened (ADR-010).
FALLBACK_CONSTRAINTS = RoiConstraints(max_width=20000, max_height=20000)


class Session(QObject):
    changed = Signal()
    stepChanged = Signal(str)
    roiChanged = Signal()
    message = Signal(str)
    saved = Signal(str)

    # @args: settings - a Settings or a test map; profile - the single profile;
    #        state - a restored SessionState; folder - the session folder;
    #        demo - build the simulator; autosave - save after each change;
    #        settings_path, profile_path - where to persist, or None
    # @return: the live session, with the first recommended step open
    def __init__(self, settings: Settings | dict | None = None,
                 profile=None, state: SessionState | None = None,
                 folder: str | Path | None = None, demo: bool = False,
                 autosave: bool = True,
                 settings_path: str | Path | None = None,
                 profile_path: str | Path | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.settings = self._as_settings(settings)
        self.profile = profile if profile is not None else store.load_profile(
            paths.profile_path())
        self.state = state if state is not None else SessionState()
        self._settings_path = Path(settings_path) if settings_path else None
        self._profile_path = Path(profile_path) if profile_path else None
        self.autosave = bool(autosave)
        self.demo = bool(demo)
        self.constraints = FALLBACK_CONSTRAINTS
        self._current = "find_sun"
        self.harness = None
        self._last_tilt = None

        self.folder = self._resolve_folder(folder)
        self.state.session_dir = str(self.folder)
        if not self.state.created_at:
            self.state.created_at = _now()
        self.state.updated_at = self.state.updated_at or self.state.created_at

        self.roi = self._model_from_settings()
        self._current = self.recommended_step()

        if self.demo:
            # The default simulator now runs the real capture, centring and
            # scan engines over a scene-coupled camera. The old UI-only demo is
            # kept as a last-resort fallback for a machine where the engines
            # cannot even construct.
            try:
                from .engines import EngineHarness
                self.harness = EngineHarness(
                    folder=self.folder, settings=self.settings,
                    profile=self.profile, roi=self.roi, simulated=True,
                    parent=self)
            except Exception:  # noqa: BLE001 - graceful degradation
                from .demo import DemoHarness
                self.harness = DemoHarness(self.folder, self.roi.band,
                                           width=self.roi.capture[2],
                                           height=self.roi.capture[3], parent=self)
                self.harness.set_frame_size(self.roi.capture[2],
                                            self.roi.capture[3])
                self.harness.latitude_deg = float(
                    self.value("observatory", "latitude_deg"))
            self.harness.rateEstimate.connect(self._rate_announced)
            # The initial simulator camera is a camera connection too: restore
            # the profile preset for its sensor, not whatever ROI keys the INI
            # happened to leave behind.
            info = self.camera_info()
            if info is not None:
                self.constraints = info.caps.roi
                model = self._preset_for_camera(info)
                self.set_roi(model.capture, model.band, persist=False)
                self.roi.constraints = self.constraints
                self.roi.binning = int(self.value("camera", "binning"))
                if hasattr(self.harness, "apply_roi"):
                    self.harness.apply_roi(self.roi)
        else:
            # No simulator: keep an empty engine harness so the camera panel can
            # attach a real camera later. Without this, --no-demo could never
            # open anything.
            try:
                from .engines import EngineHarness
                self.harness = EngineHarness(
                    folder=self.folder, settings=self.settings,
                    profile=self.profile, roi=self.roi, simulated=False,
                    camera=None, parent=self)
                self.harness.rateEstimate.connect(self._rate_announced)
            except Exception:  # noqa: BLE001 - the empty window is still valid
                self.harness = None

    # ------------------------------------------------------------------ values

    # @args: settings - a config.store.Settings, a plain map from a test, or None
    # @return: a Settings with every key present
    def _as_settings(self, settings) -> Settings:
        if isinstance(settings, Settings):
            return settings
        complete = store.default_settings()
        if isinstance(settings, dict):
            complete.values.update(settings)
        return complete

    # @args: section, name - a key of config.schema.SCHEMA
    # @return: its live value
    def value(self, section: str, name: str):
        return self.settings.get(section, name)

    # @args: section, name - the key; value - the new value
    def set_value(self, section: str, name: str, value) -> None:
        self.settings.values[(section, name)] = value
        self.changed.emit()

    # @args: none
    # @return: the RoiModel the fields and the video show
    def _model_from_settings(self) -> RoiModel:
        capture = (
            int(self.value("roi", "capture_x")),
            int(self.value("roi", "capture_y")),
            int(self.value("roi", "capture_width")),
            int(self.value("roi", "capture_height")),
        )
        band = (
            int(self.value("roi", "band_x")),
            int(self.value("roi", "band_y")),
            int(self.value("roi", "band_width")),
            int(self.value("roi", "band_height")),
        )
        return RoiModel(capture=capture, band=band,
                        constraints=self.constraints,
                        binning=int(self.value("camera", "binning")),
                        tilt_deg=float(self.value("roi", "tilt_deg")),
                        tilt_px=float(self.value("roi", "tilt_px")))

    # @args: capture, band - the two rectangles the observer edits
    #        persist - write the last values to the INI (silent, as ADR-011 asks)
    def set_roi(self, capture, band, persist: bool = False) -> None:
        self.roi.capture = tuple(int(v) for v in capture)
        self.roi.band = tuple(int(v) for v in band)
        for name, value in zip(
            ("capture_x", "capture_y", "capture_width", "capture_height"),
            self.roi.capture,
        ):
            self.settings.values[("roi", name)] = int(value)
        for name, value in zip(
            ("band_x", "band_y", "band_width", "band_height"), self.roi.band
        ):
            self.settings.values[("roi", name)] = int(value)
        if persist:
            self.save_settings()
        self.roiChanged.emit()
        self.changed.emit()

    # @args: tilt - a shg TiltResult; keep the numbers and the last result
    def set_tilt(self, tilt) -> None:
        self._last_tilt = tilt
        if getattr(tilt, "ok", False):
            self.roi.set_tilt(float(tilt.tilt_deg), float(tilt.tilt_px))
            self.settings.values[("roi", "tilt_deg")] = float(tilt.tilt_deg)
            self.settings.values[("roi", "tilt_px")] = float(tilt.tilt_px)
        # No roiChanged here: the geometry did not move, and reloading the
        # editor would throw away the typed band the measurement was taken on.
        self.changed.emit()

    # @args: none
    # @return: the last TiltResult, or None before the first measurement
    def last_tilt(self):
        return self._last_tilt

    # @args: constraints - the camera's real RoiConstraints
    def set_constraints(self, constraints: RoiConstraints) -> None:
        self.constraints = constraints
        self.roi.constraints = constraints
        self.roiChanged.emit()

    # @args: fps - estimated rate, or None when unknown
    # @return: the ROI findings, errors first
    def roi_warnings(self, fps: float | None = None) -> list[RoiWarning]:
        return validate_roi_model(self.roi, fps)

    # @args: none
    # @return: True when any finding is an error (the ROI cannot be scanned).
    #          The step stays navigable: only the scan action is gated, and the
    #          window explains why
    def roi_has_errors(self) -> bool:
        return any(warning.severity.value == "error"
                   for warning in self.roi_warnings(self.estimated_fps))

    # ------------------------------------------------------------------- steps

    # @args: step - one of config.schema.SESSION_STEPS
    # @return: none. Free navigation: no state is required to enter a step
    def select_step(self, step: str) -> None:
        if step not in self.state.steps:
            raise ValueError(f"unknown session step: {step}")
        self._current = step
        current = self.state.steps[step]
        if current.status in (StepStatus.PENDING, StepStatus.SKIPPED):
            current.status = StepStatus.CURRENT
            current.updated_at = _now()
            self._autosave()
        self.stepChanged.emit(step)
        self.changed.emit()

    # @args: none
    # @return: the step the side panel is showing
    def current_step(self) -> str:
        return self._current

    # @args: step - a session step
    # @return: its persisted state
    def step_state(self, step: str) -> StepState:
        return self.state.steps[step]

    # @args: step - a session step
    # @return: the status the rail paints
    def status_of(self, step: str) -> StepStatus:
        return self.state.steps[step].status

    # @args: step - the step that just finished; metrics - numbers only, with
    #        stable names ("tilt_deg", "rate_arcsec_s", "dec_error_arcsec")
    def complete_step(self, step: str, **metrics: float) -> None:
        state = self.state.steps[step]
        state.status = StepStatus.DONE
        state.updated_at = _now()
        for name, value in metrics.items():
            state.metrics[name] = float(value)
        self._autosave()
        self.changed.emit()

    # @args: step - a completed step the observer wants to do again
    def reopen_step(self, step: str) -> None:
        state = self.state.steps[step]
        state.status = StepStatus.CURRENT
        state.updated_at = _now()
        self._current = step
        self._autosave()
        self.stepChanged.emit(step)
        self.changed.emit()

    # @args: step - a step the expert user is skipping on purpose
    def skip_step(self, step: str) -> None:
        state = self.state.steps[step]
        state.status = StepStatus.SKIPPED
        state.updated_at = _now()
        self._autosave()
        self.changed.emit()

    # @args: none
    # @return: the first step not done yet, or "scan" when all are done. The
    #          window turns it into a recommendation, never into a gate
    def recommended_step(self) -> str:
        for step in self.state.steps:
            if self.state.steps[step].status in (StepStatus.PENDING,
                                                 StepStatus.CURRENT):
                return step
        return "scan"

    # -------------------------------------------------------------- persistence

    # @args: folder - a session folder or None to create a fresh one
    def new_session(self, folder: str | Path | None = None) -> None:
        self.folder = self._resolve_folder(folder, fresh=True)
        self.state = SessionState(session_dir=str(self.folder),
                                  created_at=_now(), updated_at=_now())
        self._current = "find_sun"
        self.save()
        self.stepChanged.emit(self._current)
        self.changed.emit()

    # @args: none
    # @return: the session_state.json path inside the session folder
    def state_path(self) -> Path:
        return store.session_state_path(self.folder)

    # @args: none
    # @return: the path written, or None when autosave is off
    def save(self) -> Path | None:
        target = self.state_path()
        self.state.session_dir = str(self.folder)
        self.state.updated_at = _now()
        store.save_session_state(self.state, target)
        self.saved.emit(str(target))
        return target

    # @args: none
    def _autosave(self) -> None:
        if not self.autosave:
            return
        try:
            self.save()
        except OSError as error:
            # A full or read-only disk must not abort the click the user just
            # made: report it and keep going (ADR-014).
            self.message.emit(str(error))

    # @args: folder - a session folder holding session_state.json
    # @return: the Session, with its step state restored silently (ADR-011)
    @classmethod
    def load(cls, folder: str | Path, **kwargs) -> "Session":
        state = store.load_session_state(store.session_state_path(Path(folder)))
        return cls(state=state, folder=folder, **kwargs)

    # @args: other - a session loaded from another folder
    def adopt(self, other: "Session") -> None:
        # Only the persisted part moves: the engines and the demo harness stay
        # with this window, so opening another session does not restart the
        # camera or lose the frames already arriving.
        self.state = other.state
        self.folder = other.folder
        self._current = self.recommended_step()
        self.state.session_dir = str(self.folder)
        self._autosave()
        self.stepChanged.emit(self._current)
        self.changed.emit()

    # @args: none
    def save_settings(self) -> Path | None:
        # Only when the caller gave a path: the window does, a test may not, and
        # a test must never write into the user's real config file.
        if self._settings_path is None:
            return None
        store.save_settings(self.settings, self._settings_path)
        return self._settings_path

    # @args: none
    # @return: the INI path this session writes to, or None
    def settings_file(self) -> Path | None:
        return self._settings_path

    # @args: none
    # @return: the profile path this session writes to, or None
    def profile_file(self) -> Path | None:
        return self._profile_path

    # @args: name - the preset name; capture, band - the rectangles to store. The
    #        typed values are passed when the observer saves before applying, so
    #        the preset is what is on screen, not the last applied rectangle
    # @return: the preset stored in the in-memory profile
    def save_preset(self, name: str, capture=None, band=None) -> object:
        from solarscribe.config.schema import RoiPreset
        preset = RoiPreset(
            name=name,
            capture=tuple(capture) if capture is not None else self.roi.capture,
            band=tuple(band) if band is not None else self.roi.band,
        )
        presets = [item for item in self.profile.roi_presets
                   if item.name != name]
        presets.append(preset)
        self.profile = replace(self.profile, roi_presets=tuple(presets))
        if self._profile_path is not None:
            store.save_profile(self.profile, self._profile_path)
        self.changed.emit()
        return preset

    # @args: preset - a profile preset
    def apply_preset(self, preset) -> None:
        # Kept for programmatic callers: it adopts the preset as the applied
        # model. The ROI step loads it into the fields instead, so the observer
        # still presses Apply and the scan cannot start on a rectangle the
        # camera has not received.
        self.set_roi(preset.capture, preset.band)

    # @args: settings - the Settings the settings dialog produced
    def update_settings(self, settings) -> None:
        self.settings = self._as_settings(settings)
        if self.harness is not None and hasattr(self.harness, "update_settings"):
            self.harness.update_settings(self.settings)
        self.roi = self._model_from_settings()
        self.roi.constraints = self.constraints
        self.changed.emit()
        self.roiChanged.emit()

    # @args: camera - the camera to stream from; info - its identity, or None to
    #        ask the camera
    # @return: True when the camera started with a ROI preset that fits it
    def use_camera(self, camera, info=None) -> bool:
        if self.harness is None or not hasattr(self.harness, "use_camera"):
            return False
        info = info or camera.info()
        self.constraints = info.caps.roi
        model = self._preset_for_camera(info)
        self.set_roi(model.capture, model.band, persist=False)
        self.roi.constraints = self.constraints
        self.roi.binning = int(self.value("camera", "binning"))
        try:
            ok = self.harness.use_camera(
                camera, info, simulated=info.backend == "sim", roi=self.roi)
        except DeviceError as error:
            self.message.emit(self._device_error_text(error))
            return False
        if ok:
            self.save_settings()
            self.roiChanged.emit()
            self.changed.emit()
        else:
            self.message.emit(self.tr(
                "The camera did not start. The device diagnostics say why; the "
                "telescope and the session are unaffected."))
        return bool(ok)

    # @args: none. Stops the stream and closes the camera
    def close_camera(self) -> None:
        if self.harness is not None and hasattr(self.harness, "close_camera"):
            self.harness.close_camera()
        self.changed.emit()

    # @args: none
    # @return: whether a camera is attached and open
    def has_camera(self) -> bool:
        return bool(self.harness is not None
                    and getattr(self.harness, "camera", None) is not None)

    # @args: none
    # @return: the CameraInfo of the attached camera, or None
    def camera_info(self):
        return getattr(self.harness, "camera_info", None) if self.harness else None

    # @args: info - the new camera's identity
    # @return: a ROI model from the named profile preset, or the best fit for
    #          this sensor when no preset fits. Restoring a preset that does not
    #          fit would send a rejected rectangle to the driver
    def _preset_for_camera(self, info) -> RoiModel:
        constraints = info.caps.roi
        name = str(self.value("roi", "preset") or "default")
        presets = list(self.profile.roi_presets)
        ordered = [p for p in presets if p.name == name] + [
            p for p in presets if p.name != name]
        for preset in ordered:
            model = preset_to_model(
                preset, constraints,
                binning=int(self.value("camera", "binning")),
                tilt_deg=float(self.value("roi", "tilt_deg")),
                tilt_px=float(self.value("roi", "tilt_px")),
            )
            if not any(warning.severity.value == "error"
                       for warning in validate_roi(model)):
                return model
        width = constraints.max_width
        height = constraints.max_height
        if constraints.width_multiple > 1:
            width = max(constraints.min_width,
                        (width // constraints.width_multiple)
                        * constraints.width_multiple)
        if constraints.height_multiple > 1:
            height = max(constraints.min_height,
                         (height // constraints.height_multiple)
                         * constraints.height_multiple)
        band_height = max(1, int(height * 0.6))
        band_y = max(0, (height - band_height) // 2)
        return RoiModel(
            capture=(0, 0, int(width), int(height)),
            band=(0, band_y, int(width), band_height),
            constraints=constraints,
            binning=int(self.value("camera", "binning")),
            tilt_deg=float(self.value("roi", "tilt_deg")),
            tilt_px=float(self.value("roi", "tilt_px")),
        )

    # @args: none
    # @return: True when the camera accepted the ROI and the stream restarted
    def apply_roi(self) -> bool:
        if self.harness is not None and hasattr(self.harness, "apply_roi"):
            try:
                self.harness.apply_roi(self.roi)
            except DeviceError as error:
                self.message.emit(self._device_error_text(error))
                return False
            except Exception:  # noqa: BLE001 - a bad camera must not crash
                self.message.emit(self.tr(
                    "The camera refused the change. The log has the technical "
                    "detail; the previous ROI is still in the model."))
                return False
        self.save_settings()
        self.save_current_preset()
        self.changed.emit()
        return True

    # @args: none. Writes the two rectangles back to the named profile preset
    def save_current_preset(self) -> None:
        if self._profile_path is None:
            return
        name = str(self.value("roi", "preset") or "default")
        preset = model_to_preset(self.roi, name)
        presets = [item for item in self.profile.roi_presets
                   if item.name != name]
        presets.append(preset)
        self.profile = replace(self.profile, roi_presets=tuple(presets))
        store.save_profile(self.profile, self._profile_path)

    # @args: error - a DeviceError from the camera
    # @return: a sentence with no raw SDK code (ADR-014)
    def _device_error_text(self, error: DeviceError) -> str:
        code = getattr(error, "code", "error")
        if code in ("roi_rejected", "sdk_bounds"):
            return self.tr(
                "The camera rejected the ROI. The warnings in the ROI step say "
                "which limit it broke; nothing was sent to the SER.")
        if code == "param_rejected":
            return self.tr(
                "The camera rejected one of the capture settings. Check the "
                "exposure, gain and binning in Settings.")
        if code == "device_lost":
            return self.tr(
                "The camera disconnected while applying the ROI. Reconnect it "
                "and try again.")
        if code == "not_open":
            return self.tr(
                "The camera is not open. Use the camera panel to open it before "
                "applying a ROI.")
        return self.tr(
            "The camera refused the change. The log has the technical detail; "
            "the previous ROI is still in the model.")

    # @args: none. Starts the real SunCenteringImpl
    def center_sun(self) -> bool:
        if self.harness is None or not hasattr(self.harness, "center_sun"):
            return False
        return bool(self.harness.center_sun())

    # @args: none. Plans and prepares the scan in the engine harness
    def prepare_scan(self) -> bool:
        if self.harness is None or not hasattr(self.harness, "start_prepare"):
            return False
        return bool(self.harness.start_prepare())

    # @args: cycles - cycles to run; recenter - recentre between cycles
    def start_scan(self, cycles: int | None = None,
                   recenter: bool = False) -> bool:
        if self.harness is None or not hasattr(self.harness, "start_scan"):
            return False
        try:
            return bool(self.harness.start_scan(cycles, recenter))
        except TypeError:
            # The last-resort UI demo has the older one-argument signature.
            return bool(self.harness.start_scan(cycles))

    # @args: none
    def pause_scan(self) -> None:
        if self.harness is not None and hasattr(self.harness, "pause_scan"):
            self.harness.pause_scan()

    # @args: none
    def resume_scan(self) -> None:
        if self.harness is not None and hasattr(self.harness, "resume_scan"):
            self.harness.resume_scan()

    # @args: none
    def abort_scan(self) -> None:
        if self.harness is not None and hasattr(self.harness, "abort_scan"):
            self.harness.abort_scan()

    # @args: none
    # @return: the base folder the next session goes in
    def _resolve_folder(self, folder: str | Path | None,
                        fresh: bool = False) -> Path:
        if folder:
            return Path(folder)
        if self.state.session_dir and not fresh:
            return Path(self.state.session_dir)
        base = str(self.value("session", "session_dir") or "")
        root = Path(base) if base else paths.default_session_base()
        # store.py names the folder (and adds a suffix on a same-minute
        # collision), so no layer invents its own session name.
        return store.session_folder(root, datetime.now())

    # ------------------------------------------------------------------ helpers

    # @args: none
    # @return: estimated fps of the current ROI, or None when no engine can say
    def estimated_fps(self) -> float | None:
        if self.harness is not None and self.has_camera():
            fps, _ = self.harness.estimate_rate(self.roi.capture[2],
                                                self.roi.capture[3])
            return fps
        return None

    # @args: none
    # @return: (fps, MB/s) of the current ROI, or None
    def rate_estimate(self) -> tuple[float, float] | None:
        if self.harness is not None and self.has_camera():
            return self.harness.estimate_rate(self.roi.capture[2],
                                              self.roi.capture[3])
        return None

    # @args: fps, mb_s - the rate the engine announced
    def _rate_announced(self, fps: float, mb_s: float) -> None:
        self.changed.emit()
        self.roiChanged.emit()

    # @args: band - the band to fit, in FRAME pixels; None uses the applied one.
    #        The ROI step passes the typed band, because the observer is looking
    #        at the overlay, not at the last applied rectangle
    # @return: a tilt measurement, or None when shg is not available. The real
    #          call is shg's TiltMeter (ADR-022); the simulator's frame is
    #          measured with the same maths, so the step exercises the real code
    def measure_tilt(self, band=None):
        from solarscribe.shg.tilt import measure_tilt as shg_measure
        frame = self.harness.last_frame() if self.harness is not None else None
        if frame is None:
            return None
        try:
            result = shg_measure(frame, tuple(band) if band is not None
                                 else self.roi.band)
        except (ValueError, TypeError):
            from solarscribe.shg.abc import TiltResult
            result = TiltResult(ok=False, reason_code="no_edge")
        self.set_tilt(result)
        return self._last_tilt

    # @args: none
    # @return: the Sun's (ra hours, dec degrees), or None when the local
    #          ephemeris is unavailable. RA and Dec are geocentric: they do not
    #          depend on the observatory, so the GOTO can point even before the
    #          location is filled in. The location still matters for the
    #          altitude, the polar assistant and the sky calendar's horizon
    def sun_position(self):
        lat = float(self.value("observatory", "latitude_deg"))
        lon = float(self.value("observatory", "longitude_deg"))
        try:
            from solarscribe.shg.ephemeris import solar_position_now
            position = solar_position_now(lat, lon, float(
                self.value("observatory", "elevation_m")))
        except (ImportError, ValueError):
            return None
        return position.ra_hours, position.dec_deg

    # @args: none
    # @return: the figures of the sky calendar's Sun tab, or {} when the local
    #          ephemeris is not available in this build
    def sun_info(self) -> dict:
        lat = float(self.value("observatory", "latitude_deg"))
        lon = float(self.value("observatory", "longitude_deg"))
        try:
            from solarscribe.shg.ephemeris import solar_position_now
            position = solar_position_now(lat, lon)
        except (ImportError, ValueError):
            return {}
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "diameter_arcmin": position.diameter_arcsec / 60.0,
            "ra_hours": position.ra_hours,
            "dec_deg": position.dec_deg,
            "rotation": position.position_angle_deg,
            "heliographic": self.tr(
                "B0 {b0:+.2f} deg, L0 {l0:.2f} deg").format(
                    b0=position.heliographic_latitude_deg,
                    l0=position.heliographic_longitude_deg),
            "source": "ephemeris",
        }

    # @args: none
    # @return: the demo mount, or None when the layer is real
    def demo_mount(self):
        return self.harness.mount if self.harness is not None else None

    # @args: none
    # @return: whether the numbers come from the simulator, so the window can
    #          label them. A real camera connected through the camera panel
    #          turns this false even though the harness exists
    def is_simulated(self) -> bool:
        if self.harness is None:
            return False
        return bool(getattr(self.harness, "simulated", True))


# @args: none
# @return: ISO-8601 UTC, the stamp StepState stores
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
