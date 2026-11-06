############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - ui step rail module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The four-step rail of the session (ADR-011, ADR-026).
#
# It is a custom widget and lives in code instead of a .ui because its content
# is a function of SessionState: four chips, each with a live status. What the
# .ui cannot express is the rule the rail exists to serve: navigation is FREE.
# A chip that is pending is not disabled; clicking it enters the step and the
# status changes to "in progress". The rail guides, it never blocks.
#
# ADR-026 slimmed it from a 64 px, two-line rail to one 28 px line: the image is
# the point, the rail is an indicator. The status is still spelled out in words
# ("Pending", "In progress", "Done", "Skipped") on the same line, because a
# colour alone would leave the colour-blind user without the information.

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from solarscribe.config.schema import SESSION_STEPS, SessionState, StepStatus

__all__ = ["StepRail", "STEP_TITLES"]


# The full visible names of the five steps. They are plain language on purpose
# (ADR-011): "Find the Sun", not "stage_1_goto". Kept here for the page titles
# and the docs; the rail uses a shorter label (Find Sun, Polar, Scan) so five
# chips fit on a 13 inch laptop without clipping (ADR-026).
STEP_TITLES = {
    "find_sun": "Find the Sun",
    "polar": "Polar alignment",
    "focus": "Focus",
    "roi": "ROI",
    "scan": "Scanning",
}


class StepRail(QWidget):
    stepActivated = Signal(str)

    # @args: parent - the Qt parent
    # @return: four chips, all idle until set_state() paints them
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StepRail")
        self._buttons: dict[str, QToolButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for index, step in enumerate(SESSION_STEPS, start=1):
            button = QToolButton(self)
            button.setObjectName(f"step_{step}")
            button.setCheckable(True)
            button.setProperty("rail", True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(26)
            button.setMaximumHeight(28)
            button.setText(f"{index}. {self._title(step)}")
            button.setToolTip(self.tr(
                "Go to this step. Steps never block: you can come back at any "
                "time and the state is saved as you go."))
            button.clicked.connect(lambda _=False, s=step: self._activate(s))
            layout.addWidget(button, 1)
            self._buttons[step] = button
            self._group.addButton(button)

    # @args: step - a session step key
    # @return: its chip, for the window and for the tests
    def button(self, step: str) -> QToolButton:
        return self._buttons[step]

    # @args: none
    # @return: True when every step has a chip, in rail order
    def steps(self) -> tuple[str, ...]:
        return tuple(self._buttons)

    # @args: state - the persisted session state
    #        current - the step whose panel is open; None uses SessionState only
    def set_state(self, state: SessionState, current: str | None = None) -> None:
        for step, button in self._buttons.items():
            status = state.steps[step].status
            button.setProperty("stepStatus", status.value)
            self._refresh_style(button)
            title = self._title(step)
            button.setText(f"{self._index(step)}. {title} · {self._status_text(status)}")
            checked = step == current
            button.setChecked(checked)

    # @args: step - a session step
    # @return: its translated name. Literals on purpose: lupdate cannot extract
    #          a string behind a dictionary lookup (ADR-016)
    def _title(self, step: str) -> str:
        # The rail is an indicator, not the page title: short labels let the
        # five chips and their status words fit at 1024 px (ADR-026).
        if step == "find_sun":
            return self.tr("Find Sun")
        if step == "polar":
            return self.tr("Polar")
        if step == "focus":
            return self.tr("Focus")
        if step == "roi":
            return self.tr("ROI")
        return self.tr("Scan")

    # @args: current - the step now open. Marks the chip selected without
    #                 changing any status
    def set_current(self, current: str) -> None:
        for step, button in self._buttons.items():
            button.setChecked(step == current)

    # @args: step - the step clicked
    def _activate(self, step: str) -> None:
        # Emitted even when the step is done or skipped: re-entering is a
        # feature ("reopen step", ADR-011), not a mistake.
        self.set_current(step)
        self.stepActivated.emit(step)

    # @args: step - a session step
    # @return: its 1-based position, the number the user sees
    def _index(self, step: str) -> int:
        return SESSION_STEPS.index(step) + 1

    # @args: status - the persisted status
    # @return: the plain sentence under the step name. A state colour without a
    #          word is not accessible, so the word is always there
    def _status_text(self, status: StepStatus) -> str:
        if status is StepStatus.DONE:
            return self.tr("Done")
        if status is StepStatus.CURRENT:
            return self.tr("In progress")
        if status is StepStatus.SKIPPED:
            return self.tr("Skipped")
        return self.tr("Pending")

    # @args: button - the chip whose dynamic property changed
    def _refresh_style(self, button: QToolButton) -> None:
        # Qt does not repaint on a dynamic property change by itself; the
        # unpolish/polish pair is what makes the QSS selector apply.
        button.style().unpolish(button)
        button.style().polish(button)

    # @args: event - resize; unused beyond keeping the styles applied after a
    #        show, which is when Qt first knows the font metrics
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
