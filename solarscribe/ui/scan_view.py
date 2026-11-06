############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui scan view module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The scan visualisation (ADR-020): the captured strip, the slit line and the
# percentage, wired to the ScanProgress the engine publishes.
#
# The widget itself is SunDiscWidget; this class only translates the engine's
# dataclass into the drawing and spells the result in plain language. Keeping
# the translation here means the window has no geometry of its own, which is
# the rule of the ui layer.

from __future__ import annotations

from solarscribe.shg.abc import ScanProgress, ScanResult, ScanStatus

from .sun_disc import SunDiscWidget

__all__ = ["ScanVisualisation"]


class ScanVisualisation(SunDiscWidget):
    # @args: progress - the engine's live ScanProgress
    def set_progress_from(self, progress: ScanProgress) -> None:
        self.set_progress(progress.progress, progress.row)

    # @args: result - the engine's ScanResult; rows - rows in the plan
    def set_result_from(self, result: ScanResult, rows: int = 1) -> None:
        self.set_rows(rows)
        if result.status is ScanStatus.COMPLETED:
            self.set_progress(1.0)
            self.set_result(self.tr("Completed: {frames} frames in {seconds} s").format(
                frames=result.frames_written, seconds=int(result.duration_s)))
        elif result.status is ScanStatus.ABORTED:
            self.set_result(self.tr("Stopped: the frames already written are kept"))
        else:
            self.set_result(self.tr("Failed: {reason}").format(
                reason=self._reason(result.reason_code)))

    # @args: code - a stable reason code from shg
    # @return: a plain sentence. Never a raw code on screen (ADR-014)
    def _reason(self, code: str) -> str:
        if code == "no_limb":
            return self.tr("the limb was not found; check that the Sun is on the slit")
        if code == "sun_lost":
            return self.tr("the Sun left the slit; recentre and try again")
        if code == "calibration_failed":
            return self.tr("the sweep rate did not converge; check the mount rate")
        if code == "mount_no_rate":
            return self.tr("the mount cannot move by rate; the scan needs it")
        if code == "disk_full":
            return self.tr("the disk filled up; free space and retry")
        if code == "device_lost":
            return self.tr("a device disconnected; reconnect it and retry")
        if code == "stalled":
            return self.tr("frames stopped arriving; the SER is preserved")
        if code == "aborted":
            return self.tr("it was stopped on purpose")
        if code == "no_edge":
            return self.tr("the slit edge was not found")
        if code == "low_contrast":
            return self.tr("the image has too little contrast for a measurement")
        return self.tr("the engine reported a problem; see the log")
