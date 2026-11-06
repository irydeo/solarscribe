############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui roi editor module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The controller of the ROI step: the numeric fields, the band drawn on the
# video, the validation and the tilt measurement (ADR-010, ADR-022).
#
# It holds no science: validate_roi_model() is capture's check (ui/roi_checks.py
# delegates to capture/roi.py when present), the tilt is shg's TiltMeter, and
# the rate estimate comes from the engine. The editor's job is to keep the
# fields, the overlay and the sentences in agreement, and to say every number
# with its meaning.
#
# Why the capture rectangle is typed and the band is dragged: the delivered
# frame IS the capture ROI (the camera already cropped the sensor), so a larger
# rectangle drawn over it would be fiction. The band, however, lives inside the
# frame and is exactly what the observer wants to place by eye.

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QComboBox, QLabel, QSpinBox

from solarscribe.capture.abc import RoiIssue, RoiModel, RoiWarning, Severity
from solarscribe.config.schema import default_value

from .roi_checks import validate_roi_model
from .session import Session

__all__ = ["RoiEditor"]


class RoiEditor(QObject):
    changed = Signal()
    warningsChanged = Signal(list)
    applied = Signal(list)

    # @args: session - the live session; viewer - the overlay target or None;
    #        parent - the Qt parent
    # @return: the controller, unbound until bind() is called
    def __init__(self, session: Session, viewer=None, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.viewer = viewer
        self._capture: tuple[QSpinBox, ...] | None = None
        self._band: tuple[QSpinBox, ...] | None = None
        self._warning_label: QLabel | None = None
        self._tilt_label: QLabel | None = None
        self._rate_label: QLabel | None = None
        self._scale_label: QLabel | None = None
        self._preset_combo: QComboBox | None = None

    # @args: capture - (x, y, width, height) spin boxes in SENSOR pixels
    #        band - (x, y, width, height) spin boxes in FRAME pixels
    #        warning_label, tilt_label, rate_label - the sentences
    #        preset_combo - the profile presets, or None
    #        scale_label - the arcseconds-per-pixel sentence, or None
    def bind(self, capture: tuple[QSpinBox, ...], band: tuple[QSpinBox, ...],
             warning_label: QLabel, tilt_label: QLabel, rate_label: QLabel,
             preset_combo: QComboBox | None = None,
             scale_label: QLabel | None = None) -> None:
        self._capture = tuple(capture)
        self._band = tuple(band)
        self._warning_label = warning_label
        self._tilt_label = tilt_label
        self._rate_label = rate_label
        self._scale_label = scale_label
        self._preset_combo = preset_combo
        for spin in self._capture + self._band:
            spin.valueChanged.connect(self._on_field_changed)
        self.reload_presets()
        self.reload()

    # @args: none
    # @return: the rectangles currently in the fields
    def rectangles(self):
        assert self._capture is not None and self._band is not None
        capture = tuple(max(1 if index >= 2 else 0, int(spin.value()))
                        for index, spin in enumerate(self._capture))
        band = tuple(max(1 if index >= 2 else 0, int(spin.value()))
                     for index, spin in enumerate(self._band))
        return capture, band

    # @args: none. Reads the session model into the fields and the video
    def reload(self) -> None:
        if self._capture is None or self._band is None:
            return
        for spin, value in zip(self._capture, self.session.roi.capture):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        for spin, value in zip(self._band, self.session.roi.band):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        self.update_preview()
        self.refresh_warnings()
        self.refresh_tilt()
        self.refresh_rate()
        self.refresh_scale()

    # @args: none. Pushes the band to the viewer overlay
    def update_preview(self) -> None:
        if self.viewer is None or self._band is None:
            return
        band = tuple(int(spin.value()) for spin in self._band)
        self.viewer.set_band(band)

    # @args: band - a band in frame pixels, dragged on the video
    def band_dragged(self, band) -> None:
        if self._band is None:
            return
        for spin, value in zip(self._band, band):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        self.refresh_warnings()
        self.changed.emit()

    # @args: none
    # @return: the findings of the current rectangles, errors first
    def warnings(self) -> list[RoiWarning]:
        capture, band = self.rectangles()
        # Validate the typed rectangles before they reach the session, so the
        # sentence appears while the user is still editing.
        model = RoiModel(capture=capture, band=band,
                         constraints=self.session.constraints,
                         binning=self.session.roi.binning,
                         tilt_deg=self.session.roi.tilt_deg,
                         tilt_px=self.session.roi.tilt_px)
        return validate_roi_model(model, self._typed_fps())

    # @args: none
    # @return: the rate the typed capture rectangle would reach, or None when
    #          there is no engine to estimate it
    def _typed_fps(self) -> float | None:
        if self.session.harness is None or not self.session.has_camera():
            return None
        capture, _ = self.rectangles()
        fps, _ = self.session.harness.estimate_rate(capture[2], capture[3])
        return fps

    # @args: none
    # @return: the current findings
    def current_warnings(self) -> list[RoiWarning]:
        return self.warnings()

    # @args: none. Applies the fields to the session, silently saving the values
    # @return: the findings; the window keeps the scan action off on an error.
    #          An error means the camera would reject the ROI, so it is not sent
    #          and the sentence "not applied" stays true
    def apply(self) -> list[RoiWarning]:
        capture, band = self.rectangles()
        warnings = self.warnings()
        if any(warning.severity is Severity.ERROR for warning in warnings):
            self.refresh_warnings()
            self.applied.emit(warnings)
            return warnings
        self.session.set_roi(capture, band, persist=False)
        warnings = self.session.roi_warnings(self.session.estimated_fps())
        self.refresh_warnings()
        self.refresh_rate()
        self.applied.emit(warnings)
        return warnings

    # @args: warning - one finding
    # @return: a plain sentence with its numbers and its meaning (ADR-016)
    def warning_text(self, warning: RoiWarning) -> str:
        prefix = {
            Severity.ERROR: self.tr("Cannot scan: "),
            Severity.WARNING: self.tr("Recommendation: "),
            Severity.INFO: self.tr("Note: "),
        }[warning.severity]
        args = warning.args
        if warning.issue is RoiIssue.BAND_CLIPPED:
            band_end = args.get("band_x", 0) + args.get("band_width",
                                                       args.get("band_w", 0))
            frame_w = args.get("frame_width", args.get("frame_w", 0))
            return prefix + self.tr(
                "the spectral band reaches x={band_end} but the frame is {frame_w} "
                "pixels wide. The part outside is lost, so the order would be "
                "clipped."
            ).format(band_end=int(band_end), frame_w=int(frame_w))
        if warning.issue is RoiIssue.TILT_HEIGHT:
            return prefix + self.tr(
                "the ROI is {height} px tall, but the band ({band_height} px) plus "
                "the measured tilt drift ({tilt_px} px) and a {margin} px margin "
                "need {needed} px. Either straighten the line or make the ROI "
                "taller."
            ).format(height=int(args.get("capture_height", args.get("height", 0))),
                     band_height=int(args.get("band_height", 0)),
                     tilt_px=round(float(args.get("tilt_px", 0.0)), 1),
                     margin=int(args.get("margin", 0)),
                     needed=int(args.get("needed", 0)))
        if warning.issue is RoiIssue.SDK_MULTIPLE:
            if "axis" in args:
                return prefix + self.tr(
                    "the camera only accepts {axis} values in multiples of "
                    "{multiple}; {value} is not. The driver would reject the ROI."
                ).format(axis=args.get("axis", "width"),
                         multiple=int(args.get("multiple", 1)),
                         value=int(args.get("value", 0)))
            return prefix + self.tr(
                "the camera only accepts widths in multiples of {width_multiple} "
                "and heights in multiples of {height_multiple}; {width} x {height} "
                "does not fit. The driver would reject the ROI."
            ).format(width_multiple=int(args.get("width_multiple", 1)),
                     height_multiple=int(args.get("height_multiple", 1)),
                     width=int(args.get("width", 0)),
                     height=int(args.get("height", 0)))
        if warning.issue is RoiIssue.SDK_BOUNDS:
            if "right" in args:
                return prefix + self.tr(
                    "the ROI leaves the sensor: it ends at ({right}, {bottom}) and "
                    "the sensor is {max_width} x {max_height} pixels. Move it back "
                    "inside before applying it."
                ).format(right=int(args.get("right", 0)),
                         bottom=int(args.get("bottom", 0)),
                         max_width=int(args.get("max_width", 0)),
                         max_height=int(args.get("max_height", 0)))
            return prefix + self.tr(
                "the ROI is {width} x {height} pixels on a sensor of {max_width} x "
                "{max_height}. Move it back inside before applying it."
            ).format(width=int(args.get("width", 0)),
                     height=int(args.get("height", 0)),
                     max_width=int(args.get("max_width", 0)),
                     max_height=int(args.get("max_height", 0)))
        if warning.issue is RoiIssue.BINNING_MISMATCH:
            if "from_binning" in args:
                return prefix + self.tr(
                    "these rectangles were measured at binning {from_binning} and "
                    "the camera is at {to_binning}. Binning changes what a pixel "
                    "means, so the ROI has to be measured again."
                ).format(from_binning=int(args.get("from_binning", 0)),
                         to_binning=int(args.get("to_binning", 0)))
            return prefix + self.tr(
                "these rectangles do not match the camera's binning ({binning}). "
                "Binning changes what a pixel means, so the ROI has to be measured "
                "again."
            ).format(binning=int(args.get("binning", 1)))
        if warning.issue is RoiIssue.LOW_RATE:
            return prefix + self.tr(
                "this strip would run at about {fps} frames per second, below the "
                "{target} fps target. The scan takes longer and the Sun moves "
                "further between rows."
            ).format(fps=int(args.get("fps", 0)),
                     target=int(args.get("target_fps", args.get("target", 120))))
        if warning.issue is RoiIssue.SLIT_OFF_CENTRE:
            return prefix + self.tr(
                "the slit sits {offset} pixels off the centre of the ROI. The scan "
                "still works, but one side has less margin than the other."
            ).format(offset=int(abs(args.get("offset_px", args.get("offset", 0)))))
        return prefix + self.tr("the ROI needs a check before scanning.")

    # @args: none. Reads the arcseconds per pixel from the profile optics
    def refresh_scale(self) -> None:
        if self._scale_label is None:
            return
        try:
            from solarscribe.shg.geometry import pixel_scale_arcsec_px
            scale = pixel_scale_arcsec_px(
                float(self.session.profile.telescope.focal_length_mm),
                float(self.session.profile.camera.pixel_size_um))
        except (ImportError, ValueError, AttributeError):
            self._scale_label.setText(self.tr(
                "Scale: not available until the profile has the optics."))
            self._set_state(self._scale_label, "muted")
            return
        scale *= max(1, int(self.session.roi.binning))
        self._scale_label.setText(self.tr("{value:.2f} arcsec per pixel.").format(
            value=scale))
        self._set_state(self._scale_label, "ok")

    # @args: none. Rebuilds the warning sentence from the current findings
    def refresh_warnings(self) -> None:
        warnings = self.warnings()
        if self._warning_label is not None:
            if not warnings:
                self._warning_label.setText(
                    self.tr("No problems found: this ROI can be scanned."))
                self._set_state(self._warning_label, "ok")
            else:
                self._warning_label.setText(
                    "\n".join(self.warning_text(warning) for warning in warnings))
                # The colour is the worst finding, not the first one: an error
                # can come after a recommendation in the validator's order.
                if any(item.severity is Severity.ERROR for item in warnings):
                    self._set_state(self._warning_label, "error")
                elif any(item.severity is Severity.WARNING for item in warnings):
                    self._set_state(self._warning_label, "warning")
                else:
                    self._set_state(self._warning_label, "muted")
        self.warningsChanged.emit(warnings)

    # @args: none. Runs the tilt meter (shg's, or the demo) and writes the result
    def measure_tilt(self) -> None:
        band = self.rectangles()[1]
        result = self.session.measure_tilt(band)
        if result is None:
            if self._tilt_label is not None:
                self._tilt_label.setText(self.tr("Not measured"))
                self._tilt_label.setToolTip(self.tr(
                    "The tilt meter needs the SHG module, which is not available "
                    "in this build. The ROI is used without a tilt measurement."))
            return
        self.refresh_tilt()
        self.refresh_warnings()

    # @args: none. Reads the last tilt into the label
    def refresh_tilt(self) -> None:
        if self._tilt_label is None:
            return
        tilt = self.session.last_tilt()
        if tilt is None:
            self._tilt_label.setText(self.tr("Not measured"))
            self._set_state(self._tilt_label, "muted")
            return
        if not getattr(tilt, "ok", False):
            self._tilt_label.setText(self.tr("The edge was not found"))
            self._set_state(self._tilt_label, "warning")
            return
        text = self.tr("{deg} deg, {px} px of drift").format(
            deg=round(float(tilt.tilt_deg), 2),
            px=round(float(tilt.tilt_px), 1))
        if float(tilt.edge_std_px) > 1.5:
            text += self.tr(" (edge irregular: treat it with caution)")
            self._set_state(self._tilt_label, "warning")
        else:
            self._set_state(self._tilt_label, "ok")
        self._tilt_label.setText(text)

    # @args: none. Reads the rate estimate into the label, with its budget
    def refresh_rate(self) -> None:
        if self._rate_label is None:
            return
        capture, _ = self.rectangles()
        estimate = None
        if self.session.harness is not None and self.session.has_camera():
            estimate = self.session.harness.estimate_rate(capture[2], capture[3])
        target = int(default_value("capture", "target_fps"))
        if estimate is None:
            self._rate_label.setText(self.tr(
                "Rate: not estimated until the camera is connected."))
            self._set_state(self._rate_label, "muted")
            return
        fps, mb_s = estimate
        text = self.tr("{fps} fps, {mb} MB/s (target {target} fps).").format(
            fps=int(fps), mb=int(mb_s), target=target)
        if self.session.is_simulated():
            # The simulator repaints slowly on purpose; the estimate is the
            # geometry of the rectangle, not the demo's frame rate, and saying so
            # stops the two numbers from looking contradictory.
            text += self.tr(" Simulator.")
        self._rate_label.setText(text)
        self._set_state(self._rate_label, "ok" if fps >= target else "warning")

    # @args: none. Fills the preset combo from the profile
    def reload_presets(self) -> None:
        if self._preset_combo is None:
            return
        current = self._preset_combo.currentText()
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        for preset in self.session.profile.roi_presets:
            self._preset_combo.addItem(preset.name, preset)
        if current:
            index = self._preset_combo.findText(current)
            if index >= 0:
                self._preset_combo.setCurrentIndex(index)
        self._preset_combo.blockSignals(False)

    # @args: index - the combo index the user picked
    def preset_selected(self, index: int) -> None:
        if self._preset_combo is None or index < 0:
            return
        preset = self._preset_combo.itemData(index)
        if preset is not None:
            self.load_preset(preset)

    # @args: preset - a profile preset. Loads it into the fields only: the
    #        camera still has the applied rectangle until Apply is pressed
    def load_preset(self, preset) -> None:
        if self._capture is None or self._band is None:
            return
        for spin, value in zip(self._capture, preset.capture):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        for spin, value in zip(self._band, preset.band):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        self.update_preview()
        self.refresh_warnings()
        self.refresh_rate()
        self.changed.emit()

    # @args: spin - the field that changed; emits and redraws
    def _on_field_changed(self, _value: int) -> None:
        self.update_preview()
        self.refresh_warnings()
        self.refresh_rate()
        self.changed.emit()

    # @args: label - the label to recolour; state - ok, warning, error, muted
    def _set_state(self, label: QLabel, state: str) -> None:
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)
