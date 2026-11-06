############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui health panel module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The health panel of ARCHITECTURE 5 and ADR-013: the live counters of the
# capture stream, each one written with what it measures and the budget it has
# to meet.
#
# The rule that shapes every sentence here is "no figure without an
# explanation": "0.4%" alone means nothing, "0.4% of 12,000 frames lost: each
# one is a gap in the SER" tells the observer whether the scan is safe. The
# verdict line is the shortest possible answer to "is it going well?", and it
# names the budget when the answer is no.

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from solarscribe.capture.abc import StreamCounters, WriterCounters
from solarscribe.config.schema import default_value

from .ui_loader import load_ui

__all__ = ["HealthPanel"]

# ADR-013: the budget for the reference strip. Kept here as the fallback when
# the schema cannot be read; the schema stays the source of truth.
DEFAULT_TARGET_FPS = 120.0
DROPPED_BUDGET_PCT = 0.1


class HealthPanel(QWidget):
    # @args: parent - the Qt parent
    # @return: the panel, with the schema budget already loaded
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        ui = load_ui("health_panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(ui)
        self._ui = ui
        self._target_fps = float(default_value("capture", "target_fps"))
        self._queue_budget_mb = float(default_value("capture", "queue_budget_mb"))
        self._min_free_gb = float(default_value("capture", "min_free_disk_gb"))
        self._counters: StreamCounters | None = None
        self._simulated = False

    # @args: target - the sustained rate the ROI must reach
    def set_target_fps(self, target: float) -> None:
        self._target_fps = float(target)

    # @args: counters - the live StreamCounters
    #        writer - the WriterCounters of the recording, or None when idle
    #        free_gb - free space on the session disk, or None
    #        roi - the capture rectangle, to explain the sensor data rate
    #        simulated - True when the numbers come from the simulator, so the
    #                    verdict never claims a camera measurement
    def set_counters(self, counters: StreamCounters,
                     writer: WriterCounters | None = None,
                     free_gb: float | None = None,
                     roi: tuple[int, int, int, int] | None = None,
                     simulated: bool = False) -> None:
        self._counters = counters
        self._simulated = bool(simulated)
        fps = float(counters.fps)
        received = int(counters.frames_received)
        dropped = int(counters.frames_dropped_sdk)
        percent = (dropped / received * 100.0) if received else 0.0

        self._text("fpsValue", self.tr("{fps:.0f} fps, target {target:.0f}").format(
            fps=fps, target=self._target_fps))
        self._state("fpsValue", "ok" if fps >= self._target_fps else "warning")

        if received:
            self._text("droppedValue", self.tr(
                "{dropped} frames ({percent:.2f}% of {total}). Each one is a gap "
                "in the SER.").format(dropped=dropped, percent=percent,
                                      total=received))
            self._state("droppedValue",
                        "ok" if percent <= DROPPED_BUDGET_PCT else "error")
        else:
            self._text("droppedValue", self.tr("--"))
            self._state("droppedValue", "muted")

        gaps = int(counters.sequence_gaps)
        self._text("gapsValue", self.tr(
            "{gaps} holes seen by the host. Zero is the only healthy figure."
        ).format(gaps=gaps))
        self._state("gapsValue", "ok" if gaps == 0 else "error")

        high_water = float(writer.queue_high_water_mb) if writer else 0.0
        self._text("queueValue", self.tr(
            "{used:.0f} MB peak of a {budget:.0f} MB budget. The queue is bounded "
            "so a slow disk drops counted frames instead of stalling the camera."
        ).format(used=high_water, budget=self._queue_budget_mb))
        self._state("queueValue", "ok" if high_water < self._queue_budget_mb
                    else "warning")

        disk = float(counters.disk_mb_s)
        self._text("diskValue", self.tr(
            "{rate:.0f} MB/s written. The budget is about 250 MB/s sustained."
        ).format(rate=disk))
        self._state("diskValue", "ok" if disk <= 250.0 else "warning")

        if free_gb is not None:
            self._text("freeDiskValue", self.tr(
                "{free:.1f} GB free. A recording does not start below {limit:.1f} "
                "GB.").format(free=free_gb, limit=self._min_free_gb))
            self._state("freeDiskValue", "ok" if free_gb >= self._min_free_gb
                        else "error")
        else:
            self._text("freeDiskValue", self.tr("--"))
            self._state("freeDiskValue", "muted")

        if roi is not None:
            width, height = int(roi[2]), int(roi[3])
            mb_s = width * height * 2.0 * fps / 1e6
            self._text("bandwidthValue", self.tr(
                "{width} x {height} px at {fps:.0f} fps needs about {mb:.0f} MB/s "
                "of sensor data. Height costs rate: doubling it halves the fps."
            ).format(width=width, height=height, fps=fps, mb=mb_s))
        else:
            self._text("bandwidthValue", self.tr("--"))

        verdict = self.findChild(QLabel, "healthVerdict")
        if verdict is not None:
            if self._simulated and not received:
                verdict.setText(self.tr(
                    "Waiting for the first simulated frame. The numbers below "
                    "prove the wiring; only the real camera can prove the rate."))
                self._set_state(verdict, "muted")
            elif self._simulated:
                verdict.setText(self.tr(
                    "Simulator at {fps:.0f} fps. The {target:.0f} fps budget can "
                    "only be measured with the real camera, so this figure proves "
                    "the wiring, not the hardware.").format(
                    fps=fps, target=self._target_fps))
                self._set_state(verdict, "warning")
            elif not received:
                verdict.setText(self.tr(
                    "Waiting for frames. The verdict appears as soon as the "
                    "stream starts."))
                self._set_state(verdict, "muted")
            elif percent > DROPPED_BUDGET_PCT:
                verdict.setText(self.tr(
                    "Not healthy: {percent:.2f}% of the frames were lost, above "
                    "the {budget}% budget. The SER will have gaps.").format(
                    percent=percent, budget=DROPPED_BUDGET_PCT))
                self._set_state(verdict, "error")
            elif fps < self._target_fps:
                verdict.setText(self.tr(
                    "Below the rate budget: {fps:.0f} fps against {target:.0f}. "
                    "The scan will take longer; check the ROI height and the "
                    "exposure.").format(fps=fps, target=self._target_fps))
                self._set_state(verdict, "warning")
            else:
                verdict.setText(self.tr(
                    "Healthy: {fps:.0f} fps with {percent:.2f}% dropped, inside "
                    "the budget.").format(fps=fps, percent=percent))
                self._set_state(verdict, "ok")

    # @args: none
    # @return: the sentences shown, keyed by the label name, for the tests
    def texts(self) -> dict[str, str]:
        values = {}
        for name in ("fpsValue", "droppedValue", "gapsValue", "queueValue",
                     "diskValue", "freeDiskValue", "bandwidthValue"):
            label = self.findChild(QLabel, name)
            values[name] = label.text() if label is not None else ""
        verdict = self.findChild(QLabel, "healthVerdict")
        values["healthVerdict"] = verdict.text() if verdict is not None else ""
        return values

    # @args: name - the label object name; text - the sentence
    def _text(self, name: str, text: str) -> None:
        label = self.findChild(QLabel, name)
        if label is not None:
            label.setText(text)

    # @args: name - the label; state - ok, warning, error, muted
    def _state(self, name: str, state: str) -> None:
        label = self.findChild(QLabel, name)
        if label is not None:
            self._set_state(label, state)

    # @args: label - a QLabel; state - the QSS state
    def _set_state(self, label: QLabel, state: str) -> None:
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)
