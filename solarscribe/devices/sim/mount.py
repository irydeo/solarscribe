############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - devices sim mount module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# First-class mount simulator (ADR-005, ADR-019).
#
# The scan is a rate movement in RA and the Dec centring is a small movement in
# Dec, so the simulator has to integrate rates, not just record them. Position
# is kept in the astronomical convention the contract fixes: RA in hours, Dec in
# degrees.
#
# The clock is injectable on purpose. A unit test must be able to say "ten
# seconds passed" without sleeping, and the same object then runs the SHG scan
# tests off a real monotonic clock. Integration is time-based, so no test depends
# on how fast the machine is.

from __future__ import annotations

import threading
import time

from solarscribe.devices.abc import (
    Axis, DeviceError, MountCaps, MountInfo, MountStatus,
)

__all__ = ["SimMount"]

# Sidereal rate in arcseconds of RA coordinate per second. One hour of RA is
# 15 degrees, so 15.041 arcsec/s is the real solar/sidereal drift.
SIDEREAL_ARCSEC_S = 15.041

# A parked mount does not move; a rate above this is almost certainly a bug in
# the caller (the real scan runs at tens of arcsec/s, not thousands).
MAX_RATE_ARCSEC_S = 5000.0


class SimMount:
    # Mount contract backed by a tiny integrator (ADR-012).

    # @args: ra_hours - starting RA, 0..24
    #        dec_deg - starting Dec, -90..90
    #        mount_id - identity reported by discovery
    #        clock - seconds source; injectable so tests do not sleep
    def __init__(
        self,
        ra_hours: float = 12.0,
        dec_deg: float = 0.0,
        mount_id: str = "sim:mount0",
        clock=None,
        name: str = "SimMount",
    ) -> None:
        self._ra = float(ra_hours) % 24.0
        self._dec = max(-90.0, min(90.0, float(dec_deg)))
        self._mount_id = mount_id
        self._name = name
        self._clock = clock or time.monotonic
        self._last = self._clock()
        self._rate_ra = 0.0
        self._rate_dec = 0.0
        self._tracking = False
        self._parked = False
        self._connected = False
        # The camera reads position() on the capture thread while the scan
        # engine moves the mount on its own thread. One reentrant lock keeps
        # the integrator consistent without serialising the rest of the app.
        self._lock = threading.RLock()

    # @args: none. Idempotent
    # @return: none
    def connect(self) -> None:
        with self._lock:
            self._connected = True
            self._last = self._clock()

    # @args: none. Idempotent
    # @return: none
    def close(self) -> None:
        with self._lock:
            self.stop()
            self._connected = False

    # @return: whether the mount is connected
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    # @return: (ra_hours, dec_degrees) after integrating the elapsed time
    def position(self) -> tuple[float, float]:
        with self._lock:
            self._integrate()
            return self._ra, self._dec

    # @args: axis - RA or DEC; rate - arcsec/s, signed
    # @return: none
    def move_axis(self, axis: Axis, rate: float) -> None:
        with self._lock:
            if not self._connected:
                raise DeviceError("mount is not connected", code="not_connected",
                                  device_id=self._mount_id)
            if self._parked:
                raise DeviceError("mount is parked", code="parked",
                                  device_id=self._mount_id)
            if abs(rate) > MAX_RATE_ARCSEC_S:
                raise DeviceError(
                    f"rate {rate} arcsec/s above the simulated limit "
                    f"{MAX_RATE_ARCSEC_S}",
                    code="rate_rejected", device_id=self._mount_id,
                )
            self._integrate()
            if axis == Axis.RA:
                self._rate_ra = float(rate)
            elif axis == Axis.DEC:
                self._rate_dec = float(rate)
            else:
                raise DeviceError(f"unknown axis {axis}", code="not_supported",
                                  device_id=self._mount_id)

    # @args: none
    # @return: none. Stops both axes but keeps tracking as it was
    def stop(self) -> None:
        with self._lock:
            self._integrate()
            self._rate_ra = 0.0
            self._rate_dec = 0.0

    # @args: ra - hours; dec - degrees. The simulator slews instantly
    # @return: none
    def slew(self, ra: float, dec: float) -> None:
        with self._lock:
            self._require_connected()
            self.stop()
            self._ra = float(ra) % 24.0
            self._dec = max(-90.0, min(90.0, float(dec)))
            self._last = self._clock()

    # @args: ra - hours; dec - degrees
    # @return: none
    def sync(self, ra: float, dec: float) -> None:
        self.slew(ra, dec)

    # @args: on - tracking enabled or disabled
    # @return: none
    def set_tracking(self, on: bool) -> None:
        with self._lock:
            self._require_connected()
            self._integrate()
            self._tracking = bool(on)

    # @args: none
    # @return: none
    def park(self) -> None:
        with self._lock:
            self._require_connected()
            self.stop()
            self._tracking = False
            self._parked = True

    # @args: none
    # @return: none
    def unpark(self) -> None:
        with self._lock:
            self._require_connected()
            self._parked = False

    # @args: none
    # @return: none
    def abort_slew(self) -> None:
        with self._lock:
            self.stop()

    # @return: live state for the telescope panel
    def status(self) -> MountStatus:
        with self._lock:
            return MountStatus(
                tracking=self._tracking,
                slewing=False,       # the simulator slews instantly
                parked=self._parked,
            )

    # @return: what the simulator can do
    def capabilities(self) -> MountCaps:
        return MountCaps(
            supports_axis_rates=True,
            can_slew=True,
            can_sync=True,
            can_track=True,
            can_park=True,
            can_abort=True,
            reports_position_while_moving=True,
            min_rate_arcsec_s=0.01,
            max_rate_arcsec_s=MAX_RATE_ARCSEC_S,
        )

    # @return: identity; discovery builds the id as "sim:<index>"
    def info(self) -> MountInfo:
        return MountInfo(mount_id=self._mount_id, name=self._name, backend="sim")

    # @args: none
    # @return: none. Raises DeviceError when the mount is not connected
    def _require_connected(self) -> None:
        if not self._connected:
            raise DeviceError("mount is not connected", code="not_connected",
                              device_id=self._mount_id)

    # @args: none
    # @return: none. Moves the coordinates by the elapsed time times the rate
    def _integrate(self) -> None:
        now = self._clock()
        dt = max(0.0, now - self._last)
        self._last = now
        if dt == 0.0:
            return
        ra_rate = self._rate_ra
        if self._tracking:
            ra_rate += SIDEREAL_ARCSEC_S
        if ra_rate:
            # 1 hour of RA is 15 degrees = 54000 arcsec.
            self._ra = (self._ra + ra_rate * dt / 54000.0) % 24.0
        if self._rate_dec:
            self._dec = max(-90.0, min(90.0,
                                       self._dec + self._rate_dec * dt / 3600.0))
