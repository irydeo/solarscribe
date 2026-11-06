############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - capture contracts module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Contracts of the capture layer (design/ARCHITECTURE.md 2.2, ADR-012).
#
# capture owns the stream, the frame statistics, the SER writer and the ROI
# model. It imports devices and nothing else from the application: no Qt (the
# engines are logic, ARCHITECTURE 1) and no shg (they are siblings, so shg
# reaches the stream through the ports it declares itself, ARCHITECTURE 2.3).
#
# Value types are concrete dataclasses and Enums; behaviour is a Protocol with
# no body here. The implementations live in this layer's own modules:
#   - capture/engine.py: CaptureEngine (pipeline, inline consumers, counters).
#   - capture/ser.py: SerWriter (ADR-018: the standard SER fields never change).
#   - capture/roi.py: validate_roi(model, *, fps=None), preset_to_model(preset,
#     constraints) and model_to_preset(model, name). The ROI model is a value
#     type declared here, but validating it is an algorithm and belongs to the
#     layer that owns the capture ROI (ADR-010, ADR-023).
#
# Threading (ARCHITECTURE 4): the capture thread only gets frames from the SDK
# and hands them to cheap inline consumers plus a bounded recording queue. An
# inline callback that blocks costs frames, so every callback in this contract
# is documented with what it may and may not do.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from solarscribe.devices.abc import ROI, Camera, Frame, FrameStats, RoiConstraints

__all__ = [
    "CaptureEngine",
    "CaptureParams",
    "RoiIssue",
    "RoiModel",
    "RoiWarning",
    "SerColorId",
    "SerHeader",
    "Severity",
    "StreamCounters",
    "WriterCounters",
]


@dataclass(frozen=True)
class CaptureParams:
    # How the stream runs. The engine applies each field to the camera through
    # devices.Param, so the units are the ones Param fixes (exposure in
    # microseconds, gain and offset as SDK indices).
    exposure_us: float = 1000.0
    gain: float = 0.0
    offset: float = 0.0
    binning: int = 1
    bit_depth: int = 16             # the SER is written at 16 bit (DESIGN.md 6)
    readout: float = 0.0            # 0.0: leave the SDK's own default
    auto_exposure: bool = True
    # Target mean as a fraction of the maximum ADU for the bit depth. A quarter
    # of the range fills the histogram and still leaves 4x headroom for the
    # bright chromosphere features, which is what must not clip. Provisional:
    # video and QE tune it against real frames (ADR-013 phase 0).
    auto_exposure_target: float = 0.25
    queue_budget_mb: float = 512.0  # bounded recording queue (ADR-013)
    stall_timeout_s: float = 3.0    # abort when no frame arrives (ADR-014)


class SerColorId(IntEnum):
    # Colour IDs of the SER format. Integers on purpose: they are written raw
    # into the header, and post-processing reads them (ADR-018). The MVP writes
    # MONO (the SHG reference camera is mono); the Bayer and RAW IDs are here
    # because the same writer serves the colour cameras of the other backends.
    MONO = 0
    BAYER_RGGB = 8
    BAYER_GRBG = 9
    BAYER_GBRG = 10
    BAYER_BGGR = 11
    RAW8 = 102
    RAW16 = 103


@dataclass(frozen=True)
class SerHeader:
    # What the SER writer needs to open a file.
    #
    # width, height, bit_depth, color_id and little_endian are the standard SER
    # fields and must not change shape: JSol'Ex and the nightscribe-scan tools
    # read them (ADR-018). The frame count is not here because it is unknown at
    # open time: the writer patches it into the header on close().
    #
    # `roi` is metadata, not a SER field: the format has no place for it, so the
    # writer records it in session_meta.json next to the file, which is how
    # post-processing learns which sensor region was captured. Per-frame
    # timestamps travel in Frame.timestamp and land in scan_log.csv; if video
    # adds an extended SER block for them, the standard fields above stay
    # untouched (ADR-018).
    width: int
    height: int
    bit_depth: int = 16
    color_id: SerColorId = SerColorId.MONO
    little_endian: bool = True
    roi: ROI = (0, 0, 0, 0)     # SENSOR ROI the frames come from


@dataclass(frozen=True)
class WriterCounters:
    # Accounting of one recording. A concrete value type (not a Protocol) so the
    # UI, the logs and the tests all read the same fields.
    #
    # frames_dropped_queue is the second of the three places drops are counted
    # (ADR-013): the queue is bounded on purpose, because a slow disk must cost
    # frames that are reported, never stall the capture thread.
    frames_written: int = 0
    frames_dropped_queue: int = 0
    queue_high_water_mb: float = 0.0


@dataclass(frozen=True)
class StreamCounters:
    # Live health of the stream: what the status bar and the health panel show,
    # and the raw material of the G3 gate (ADR-013). Every figure the UI shows
    # from here comes with its meaning: a drop count without the budget is
    # noise to the observer.
    frames_received: int = 0
    frames_dropped_sdk: int = 0     # the SDK's own counter
    sequence_gaps: int = 0          # holes in Frame.sequence seen by the host
    fps: float = 0.0                # real rate over the last second
    disk_mb_s: float = 0.0          # write rate while recording, 0.0 when idle


@runtime_checkable
class SerWriter(Protocol):
    # Buffered SER writing with drop accounting. It runs on its own thread, fed
    # by the bounded queue: a slow disk never stops the acquisition (ADR-001).

    # @args: path - the .ser file to create; header - what to write in it
    def open(self, path: Path, header: SerHeader) -> None: ...

    # @args: frame - the frame to append. Called from the writer thread, never
    #                from the capture thread
    def write(self, frame: Frame) -> None: ...

    # @args: none. Flushes, patches the frame count into the header and closes.
    #              Idempotent: a crash path can call it twice and the file stays
    #              readable (ADR-014: the SER already written is preserved)
    def close(self) -> None: ...

    # @return: the accounting so far; valid while open and after close()
    def counters(self) -> WriterCounters: ...


@runtime_checkable
class CaptureEngine(Protocol):
    # Stream, statistics and recording. It knows no Qt: the UI adapts it.
    #
    # Implementations are built with no arguments and receive the camera through
    # configure(), so one engine serves the whole session and a camera change is
    # just another configure().

    # @args: camera - the device to stream from; roi - the ROI model whose
    #              `capture` region is applied to the hardware; params - how to
    #              run. May be called at any time: while streaming it restarts
    #              the stream with the new settings (this is what makes the live
    #              ROI editor possible, ADR-010), and while recording it stops
    #              the recording cleanly first so the SER stays readable
    def configure(self, camera: Camera, roi: RoiModel, params: CaptureParams) -> None: ...

    # @args: none. Starts the stream; the first frame must arrive within the
    #              ADR-013 start budget (5 s)
    def start(self) -> None: ...

    # @args: none. Stops the stream and joins the capture thread
    def stop(self) -> None: ...

    # @return: whether the stream is running
    def is_running(self) -> bool: ...

    # @args: cb - inline consumer called on the capture thread with every frame.
    #              It must return in well under the frame interval (8.3 ms at
    #              120 fps) and never block. The UI registers its DisplayBridge
    #              here: a one-frame mailbox that drops frames when the GUI is
    #              slow, instead of queueing them (ARCHITECTURE 4)
    def on_frame(self, cb: Callable[[Frame], None]) -> None: ...

    # @args: cb - inline consumer called on the capture thread with the stats of
    #              every frame. Same budget as on_frame
    def on_stats(self, cb: Callable[[FrameStats], None]) -> None: ...

    # @args: path - the .ser file; header - built from the configured ROI and
    #              bit depth. Frames go to the bounded queue from here on
    def start_recording(self, path: Path, header: SerHeader) -> None: ...

    # @return: the accounting of the recording that just closed
    def stop_recording(self) -> WriterCounters: ...

    # @return: whether a recording is open
    def is_recording(self) -> bool: ...

    # @return: the live counters; cheap to poll from the GUI thread
    def counters(self) -> StreamCounters: ...


class RoiIssue(Enum):
    # What can be wrong with a ROI. The list is ADR-010's validation list, one
    # code per check, so the UI maps each code to a translated sentence and to
    # the numbers that justify it.
    BAND_CLIPPED = "band_clipped"            # the spectral band does not fit
    TILT_HEIGHT = "tilt_height"              # height < band + tilt drift + margin
    SDK_MULTIPLE = "sdk_multiple"            # width, height or offset multiple
    SDK_BOUNDS = "sdk_bounds"                # over the sensor or under the minimum
    BINNING_MISMATCH = "binning_mismatch"    # the rects are from another binning
    LOW_RATE = "low_rate"                    # estimated fps under the budget
    SLIT_OFF_CENTRE = "slit_off_centre"      # slit and spectrum not aligned


class Severity(Enum):
    # How much a warning matters. ERROR means the ROI cannot be scanned: the ROI
    # step says so plainly and the scan action stays disabled (ADR-010 locks the
    # preset before scanning), while WARNING and INFO are recommendations, never
    # gates (ADR-011).
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class RoiWarning:
    # One finding of the ROI validation.
    #
    # It carries a code and numbers, never a sentence: the sentence is built by
    # the UI with self.tr() (ADR-016) and must explain every figure (AGENTS.md).
    # `args` holds the numbers the sentence needs, keyed by stable names
    # ("width", "multiple", "band_height", "tilt_px", "fps"...).
    issue: RoiIssue
    severity: Severity
    args: dict[str, float] = field(default_factory=dict)


@dataclass
class RoiModel:
    # The ROI of a session: the four regions of ADR-010 reduced to the two the
    # user edits, plus the sensor limits and the measured tilt.
    #
    # It lives in capture, not in devices, shg or config (ADR-023):
    #   - devices must stay free of application concepts, and a spectral band or
    #     a tilt are SHG concepts;
    #   - shg is a sibling of capture, so putting it there would make capture
    #     import shg;
    #   - config only persists the two rectangles, as a RoiPreset.
    # The output ROI is not a field: it is always `capture` (region 4 of
    # ADR-010), which output() states once.
    #
    # The analysis sub-regions (left and right halves, limb strip) are not here
    # either: they are computed, never stored (ADR-010), and shg computes them
    # from `capture` and `band` because it owns the measurement geometry.
    #
    # capture: SENSOR pixels, binned. It is what set_roi() takes, what fixes the
    #          frame rate and what is written to the SER. The user chooses it in
    #          the ROI step; nothing proposes it automatically.
    # band:    FRAME pixels, so (0, 0) is the top-left of the delivered frame.
    #          The useful strip of the dispersed spectrum; it must fit inside
    #          `capture` or the order is clipped.
    capture: ROI
    band: ROI
    constraints: RoiConstraints
    binning: int = 1        # the binning these rectangles refer to: changing it
                            # invalidates them (ADR-010 coherence check)
    tilt_deg: float = 0.0   # measured tilt of the spectral line (ADR-022)
    tilt_px: float = 0.0    # its drift across the ROI width, in pixels

    # @return: the ROI written to the SER, identical to capture (ADR-010)
    def output(self) -> ROI:
        return self.capture

    # @args: tilt_deg - slope of the fitted line, in degrees
    #        tilt_px - drift across the ROI width, in pixels
    # The measurement itself is shg's (ADR-022): the ROI step calls shg's
    # TiltMeter and records the result here through plain numbers, so capture
    # never imports shg.
    def set_tilt(self, tilt_deg: float, tilt_px: float) -> None:
        self.tilt_deg = tilt_deg
        self.tilt_px = tilt_px
