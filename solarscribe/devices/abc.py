############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices contracts module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Contracts of the devices layer (design/ARCHITECTURE.md 2.1, ADR-012).
#
# This module is the boundary every other layer codes against: the camera and
# mount drivers implement it, capture and shg consume it, ui and cli read it.
# It imports nothing from the application (numpy only), so a driver can never
# drag the app down with it and the whole layer stays testable without hardware
# (ADR-005).
#
# Two kinds of type live here, and the split is a rule (ADR-023):
#   - value types: frozen dataclasses and Enums. They carry data across the
#     boundary, so they are concrete: everybody must agree on their fields.
#   - behaviour: typing.Protocol. Declared here, implemented in the drivers;
#     this file never holds an algorithm.
#
# Enums keep string values and `.value` is what gets persisted (INI, JSON,
# logs): a stable spelling the profiles and the post-processing can rely on.
#
# Coordinates, because mixing them is the classic ROI bug:
#   - SENSOR pixels: every ROI a camera accepts (set_roi, effective_area,
#     CameraInfo caps) is counted from the sensor's top-left corner and
#     expressed in binned pixels.
#   - FRAME pixels: every sub-region of a delivered frame (Frame.cut_roi, the
#     analysis regions of shg, the spectral band) is counted from the frame's
#     top-left corner, so it runs from (0, 0) to (width, height).
#
# runtime_checkable is set where an isinstance check is meaningful: the
# simulators and the mocks of the test suite assert they satisfy the contract.
# isinstance only checks that the names exist, not their signatures, and
# issubclass is not supported on protocols with data members.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias, runtime_checkable

import numpy as np

__all__ = [
    "ROI",
    "Axis",
    "BackendInfo",
    "BackendReason",
    "Camera",
    "CameraCaps",
    "CameraInfo",
    "DeviceError",
    "DeviceKind",
    "DeviceManager",
    "Frame",
    "FrameStats",
    "Mount",
    "MountCaps",
    "MountInfo",
    "MountStatus",
    "Param",
    "ParamRange",
    "RoiConstraints",
]

# ROI: rectangular region in pixels, as (x, y, width, height). A tuple on
# purpose (it is what simple-astro-cap uses, ADR-008): it unpacks, it compares
# and it serialises to a JSON list without a converter. See the coordinate
# rules in the module comment before using one.
ROI: TypeAlias = tuple[int, int, int, int]


@runtime_checkable
class FrameStats(Protocol):
    # Measurements of a frame or of one of its sub-regions.
    #
    # Deliberately two numbers: they are computed inline on the capture thread
    # at 120 fps (ADR-013), so the budget only pays for a mean and a standard
    # deviation. Anything else the SHG engine needs (the bright fraction for
    # the coarse centring, the limb columns, the tilt fit) it computes itself
    # from Frame.data with numpy: the science lives in shg, not in the driver.
    mean: float
    std: float


@runtime_checkable
class Frame(Protocol):
    # One frame the backend already copied out of the SDK buffer and stamped.
    #
    # The copy is what makes the threading model safe (ADR-001, ARCHITECTURE 4):
    # the SDK reuses its own buffers, so anything handed to Python must be
    # owned by Python before the callback returns. Consumers treat a frame as
    # immutable and never write into `data`.
    data: memoryview      # uint8 or uint16, C-contiguous, no row strides
    width: int            # frame pixels, already binned
    height: int
    dtype: np.dtype       # uint8 or uint16; the SER bit depth follows from it
    roi: ROI              # SENSOR ROI this frame was captured from
    sequence: int         # backend counter: a hole means a dropped frame
    timestamp: float      # seconds, taken on receipt, never on write

    # @return: mean and standard deviation of the whole frame
    def stats(self) -> FrameStats: ...

    # @args: roi - sub-region in FRAME pixels, (0, 0) at the frame's top-left
    # @return: the sub-region as a Frame; its `data` stays C-contiguous, so a
    #          full-width strip is a zero-copy view and anything narrower is
    #          copied (a sub-rect of a 2D buffer has row strides, and a strided
    #          memoryview breaks numpy's frombuffer). Consumers read it with
    #          np.frombuffer(f.data, f.dtype).reshape(f.height, f.width).
    def cut_roi(self, roi: ROI) -> Frame: ...


class Param(Enum):
    # Camera properties addressed by name, so a backend can refuse the ones its
    # SDK does not expose (DeviceError) instead of the app guessing an index.
    #
    # The units are fixed here once, because every SDK uses its own and a
    # mismatch silently doubles or halves the exposure.
    EXPOSURE = "exposure"        # microseconds: the native unit of ASI, QHY,
                                 # Player One and Touptek
    GAIN = "gain"                # SDK gain index, not dB
    OFFSET = "offset"            # SDK offset index: the ADU pedestal
    BIT_DEPTH = "bit_depth"      # bits per pixel (8 or 16); read-only on most
                                 # SDKs, so read it before writing the SER
    BINNING = "binning"          # factor: 1, 2, 3 or 4
    READOUT = "readout"          # readout / USB traffic control in SDK units
                                 # (ZWO: USB traffic %, Touptek: speed index)
    TEMPERATURE = "temperature"  # degrees C; read-only without a cooler
    COOLER = "cooler"            # 0 off, 1 on. The MVP does not control the
                                 # temperature (DESIGN.md 5.1): the keys exist
                                 # so diagnostics can report them


@dataclass(frozen=True)
class ParamRange:
    # What a parameter accepts. The UI needs it to build a slider and to say
    # why a value was refused: a number without its range is not actionable
    # (AGENTS.md: no figure without an explanation).
    minimum: float
    maximum: float
    step: float = 0.0     # 0.0: continuous; > 0: discrete (binning, bit depth)


@dataclass(frozen=True)
class RoiConstraints:
    # Sensor and SDK limits on the hardware ROI, in binned pixels.
    #
    # They live in devices, not in capture, because they are pure sensor facts
    # the SDK states: a ROI that breaks them is rejected by the driver, so the
    # ROI step validates against them before calling set_roi (ADR-010).
    max_width: int
    max_height: int
    min_width: int = 1
    min_height: int = 1
    width_multiple: int = 1     # ASI and QHY want widths multiple of 8
    height_multiple: int = 1    # ... and heights multiple of 2
    offset_multiple: int = 1    # x and y multiples, on the SDKs that ask for it


@dataclass(frozen=True)
class CameraCaps:
    # What a camera can do. Known at discovery time, before open(): the UI
    # builds its controls from this, so it must not need an open camera to
    # decide whether a 16 bit or a binning 2 option exists.
    roi: RoiConstraints
    is_color: bool = False                  # False: mono, the SHG case
    bit_depths: tuple[int, ...] = (16,)     # what the SDK can deliver
    binnings: tuple[int, ...] = (1,)        # accepted binning factors
    has_cooler: bool = False
    reports_temperature: bool = False


@dataclass(frozen=True)
class CameraInfo:
    # Identity of a camera, as reported by discovery.
    #
    # camera_id is unique across backends and is the key of
    # DeviceManager.open_camera(); the manager builds it as
    # "<backend>:<serial or index>" so two brands cannot collide.
    camera_id: str
    vendor: str
    model: str
    backend: str        # which backend found it: "touptek", "asi", "sim"...
    caps: CameraCaps


@runtime_checkable
class Camera(Protocol):
    # What the app and the SHG engine use: lifecycle, properties and stream.
    # Every backend (native SDK, simulator, ASCOM, INDI) implements exactly
    # this, so nothing above devices knows which brand it is talking to.

    # @args: none. Raises DeviceError if the device is gone or busy
    def open(self) -> None: ...

    # @args: none. Idempotent: closing twice is not an error
    def close(self) -> None: ...

    # @return: whether the device is open and usable
    def is_open(self) -> bool: ...

    # @return: identity and capabilities; valid before and after open()
    def info(self) -> CameraInfo: ...

    # @return: the current hardware ROI, in SENSOR pixels
    def get_roi(self) -> ROI: ...

    # @args: roi - SENSOR pixels, binned; it must satisfy RoiConstraints or the
    #              backend raises DeviceError instead of cropping silently
    def set_roi(self, roi: ROI) -> None: ...

    # @return: the biggest ROI the sensor accepts at the current binning
    def effective_area(self) -> ROI: ...

    # @args: p - the property to read
    # @return: its value in the unit fixed by Param. Raises DeviceError when the
    #          SDK does not expose it (the UI then hides the control)
    def get_param(self, p: Param) -> float: ...

    # @args: p - the property; value - in the unit fixed by Param
    def set_param(self, p: Param, value: float) -> None: ...

    # @args: p - the property
    # @return: the accepted interval, so the UI can bound its inputs
    def param_range(self, p: Param) -> ParamRange: ...

    # @return: frames the SDK itself reports as lost since start_stream(). It is
    #          one of the three places drops are counted (ADR-013): inside the
    #          SDK, in the recording queue and in the sequence holes
    def dropped_frames(self) -> int: ...

    # @args: on_frame - called on the capture thread with each frame. It must
    #                   return in well under the frame interval (8.3 ms at
    #                   120 fps) and never block: this thread is the project's
    #                   critical path (ADR-013)
    def start_stream(self, on_frame: Callable[[Frame], None]) -> None: ...

    # @args: none. Stops the stream and joins the capture thread
    def stop_stream(self) -> None: ...


class Axis(Enum):
    # Mount axes for rate movement. The scan is a movement in RA and the Dec
    # centring is a movement in DEC (ADR-019), so these two are all the MVP
    # needs.
    RA = "ra"
    DEC = "dec"


@dataclass(frozen=True)
class MountCaps:
    # What a mount can do. The SHG engine reads this before planning: without
    # rate movement there is no scan at all, and the calibrated rate must fall
    # inside the accepted interval or the mount will not follow.
    supports_axis_rates: bool = False       # move_axis(): the scan needs it
    can_slew: bool = False
    can_sync: bool = False
    can_track: bool = False
    can_park: bool = False
    can_abort: bool = False
    reports_position_while_moving: bool = False
    min_rate_arcsec_s: float = 0.0
    max_rate_arcsec_s: float = 0.0


@dataclass(frozen=True)
class MountStatus:
    # Live state the telescope panel paints (ADR-019). Kept apart from
    # position() because reading it must stay cheap: the panel polls it while
    # the mount is moving.
    tracking: bool = False
    slewing: bool = False
    parked: bool = False


@dataclass(frozen=True)
class MountInfo:
    # Identity of a mount, as reported by discovery. The capabilities are not
    # here: most backends only know them once connected, so they come from
    # Mount.capabilities().
    mount_id: str
    name: str
    backend: str        # "ascom" on Windows, "indi" on Linux, "sim" in tests


@runtime_checkable
class Mount(Protocol):
    # Connection, position, movement, tracking and park.
    #
    # The SHG engine and the telescope panel use the same contract, and the
    # backend is ASCOM with native COM on Windows and INDI against indiserver
    # on Linux (ADR-019): nothing above devices knows the platform.
    #
    # Angles: RA in HOURS (0..24) and Dec in DEGREES, the convention of the
    # astronomical backends. Rates in arcseconds per second; the sign of a rate
    # selects the direction (positive: increasing coordinate).

    # @args: none. Raises DeviceError if the platform or the server is missing
    def connect(self) -> None: ...

    # @args: none. Idempotent
    def close(self) -> None: ...

    # @return: whether the mount is connected
    def is_connected(self) -> bool: ...

    # @return: (ra_hours, dec_degrees) as the mount reports them
    def position(self) -> tuple[float, float]: ...

    # @args: axis - RA or DEC; rate - arcsec/s, signed. Used by the scan (RA)
    #              and by the Dec centring (DEC)
    def move_axis(self, axis: Axis, rate: float) -> None: ...

    # @args: none. Stops every axis at once: the safe reaction to any anomaly
    def stop(self) -> None: ...

    # @args: ra - hours; dec - degrees. GOTO, used by "go to the Sun"
    def slew(self, ra: float, dec: float) -> None: ...

    # @args: ra - hours; dec - degrees. Tells the mount where it really is
    def sync(self, ra: float, dec: float) -> None: ...

    # @args: on - tracking enabled or disabled
    def set_tracking(self, on: bool) -> None: ...

    # @args: none
    def park(self) -> None: ...

    # @args: none
    def unpark(self) -> None: ...

    # @args: none. Cancels a running GOTO without parking
    def abort_slew(self) -> None: ...

    # @return: live state for the telescope panel
    def status(self) -> MountStatus: ...

    # @return: what this mount supports; valid once connected
    def capabilities(self) -> MountCaps: ...


class DeviceKind(Enum):
    # Which hardware family a backend serves. Some backends (ASCOM, INDI) serve
    # both, so a backend appears once per kind it offers.
    CAMERA = "camera"
    MOUNT = "mount"


class BackendReason(Enum):
    # Why a backend is not usable. A closed set on purpose: the UI maps each
    # value to a translated sentence (ADR-016) and never shows a raw SDK code
    # (ADR-014). `BackendInfo.detail` carries the technical text for the log.
    AVAILABLE = "available"
    SDK_MISSING = "sdk_missing"                  # the shared library is not there
    PLATFORM_MISSING = "platform_missing"        # no ASCOM Platform
    SERVER_MISSING = "server_missing"            # no indiserver running
    OS_UNSUPPORTED = "os_unsupported"            # ASCOM on Linux, for instance
    ERROR = "error"                              # anything else, explained in detail


@dataclass(frozen=True)
class BackendInfo:
    # A backend, present or absent, with the reason. Listing the absent ones is
    # the point: the app degrades gracefully and says what is missing instead of
    # silently offering less (ADR-014).
    name: str                       # "native/touptek", "ascom", "indi", "sim"
    kind: DeviceKind
    available: bool
    reason: BackendReason = BackendReason.AVAILABLE
    detail: str = ""                # for the log and the diagnostics dialog


@runtime_checkable
class DeviceManager(Protocol):
    # Discovers backends and devices and hands out open devices.
    #
    # Threading: discovery talks to SDKs and can block for a second or more
    # (enumerating USB, probing an indiserver), so the UI calls it from a worker
    # thread, never from the GUI thread.

    # @return: every known backend, available or not, with the reason
    def backends(self) -> list[BackendInfo]: ...

    # @return: the cameras found across every available backend
    def cameras(self) -> list[CameraInfo]: ...

    # @return: the mounts found across every available backend
    def mounts(self) -> list[MountInfo]: ...

    # @args: camera_id - as reported by cameras()
    # @return: an unopened Camera; the caller decides when to open() it
    def open_camera(self, camera_id: str) -> Camera: ...

    # @args: mount_id - as reported by mounts()
    # @return: an unconnected Mount; the caller decides when to connect() it
    def open_mount(self, mount_id: str) -> Mount: ...


class DeviceError(RuntimeError):
    # The single failure type of the device layer.
    #
    # Every backend translates its SDK's errors into this, so the layers above
    # catch one exception and the UI shows one plain message with the device and
    # what can be done (ADR-014). A raw SDK code never reaches the observer.
    #
    # @args: message - technical description, for the log
    #        code - stable snake_case key the UI translates ("device_lost",
    #               "roi_rejected", "not_supported"...)
    #        device_id - which device failed, "" when unknown
    def __init__(self, message: str, *, code: str = "error", device_id: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.device_id = device_id
