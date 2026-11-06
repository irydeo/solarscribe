############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - capture ser module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# SER writer (ADR-018, design/ARCHITECTURE.md 2.2).
#
# The SER file is the contract with the post-processing: a 178-byte header
# followed by raw frames, and the standard fields never change shape. The layout
# below is the format as JSol'Ex and the nightscribe-scan tools read it:
#
#   0   14  FileID             "LUCAM-RECORDER"
#   14   4  LuID               int32, 0
#   18   4  ColorID            int32 (SerColorId)
#   22   4  LittleEndian       int32, 1 or 0
#   26   4  ImageWidth         int32
#   30   4  ImageHeight        int32
#   34   4  PixelDepthPerPlane int32, bits (8 or 16)
#   38   4  FrameCount         int32, patched on close()
#   42  40  Observer           ASCII, NUL padded
#   82  40  Instrument         ASCII, NUL padded
#  122  40  Telescope          ASCII, NUL padded
#  162   8  DateTime           int64, .NET ticks
#  170   8  DateTimeUTC        int64, .NET ticks
#
# Why the frame count is patched instead of buffered: the count is unknown when
# the header is written, and a crash must still leave a readable file with the
# frames already on disk. close() flushes, seeks to offset 38, writes the real
# count and closes. A second close() is harmless (ADR-014).
#
# Why a 1 MiB buffer: at ~1.7 MB per frame the buffer absorbs a whole frame, so
# the writer thread wakes the kernel in big chunks instead of per frame. It is a
# fixed size, not a queue: the bounded queue belongs to the engine.

from __future__ import annotations

import io
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from solarscribe.capture.abc import SerHeader, WriterCounters
from solarscribe.devices.abc import Frame

__all__ = [
    "FILE_ID", "HEADER_SIZE", "FRAME_COUNT_OFFSET", "SerWriterImpl",
]

FILE_ID = b"LUCAM-RECORDER"
HEADER_SIZE = 178
FRAME_COUNT_OFFSET = 38

# 1 MiB: one reference frame is ~1.7 MB, so a frame is written in at most a
# couple of kernel calls and the writer thread does not wake up per pixel line.
BUFFER_SIZE = 1 << 20

# .NET ticks: 100 ns intervals since 0001-01-01. The SER header uses this unit
# (it was defined by the .NET Lucam recorder), not Unix seconds.
_TICKS_EPOCH = datetime(1, 1, 1, tzinfo=timezone.utc)
_TICKS_PER_SECOND = 10_000_000


# @args: when - a datetime; None means "now"
# @return: .NET ticks since 0001-01-01 in UTC
def _to_ticks(when: datetime | None) -> int:
    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int((moment - _TICKS_EPOCH).total_seconds() * _TICKS_PER_SECOND)


# @args: text - optional header text
# @return: exactly 40 bytes, ASCII, NUL padded
def _fixed_text(text: str) -> bytes:
    raw = text.encode("ascii", "replace")[:40]
    return raw + b"\x00" * (40 - len(raw))


class SerWriterImpl:
    # Buffered SER writer implementing the capture.SerWriter contract.

    # @args: when - start timestamp to write in the header; injectable so the
    #              header bytes can be asserted exactly in a test
    def __init__(self, *, when: datetime | None = None) -> None:
        self._when = when
        self._path: Path | None = None
        self._header: SerHeader | None = None
        self._raw = None
        self._buffer = None
        self._open = False
        self._frames_written = 0
        self._bytes_written = 0
        self._started = 0.0
        self._last_write = 0.0

    # @args: path - the .ser file to create
    #        header - standard fields of the file
    # @return: none
    def open(self, path: Path, header: SerHeader) -> None:
        if self._open:
            raise RuntimeError("the SER writer is already open")
        if header.width <= 0 or header.height <= 0:
            raise ValueError(f"invalid SER size {header.width}x{header.height}")
        if header.bit_depth not in (8, 16):
            raise ValueError(f"invalid SER bit depth {header.bit_depth}")
        self._path = Path(path)
        self._header = header
        self._raw = open(self._path, "wb")
        self._buffer = io.BufferedWriter(self._raw, buffer_size=BUFFER_SIZE)
        self._buffer.write(self._header_bytes(header, frame_count=0))
        self._open = True
        self._frames_written = 0
        self._bytes_written = 0
        self._started = time.monotonic()
        self._last_write = self._started

    # @args: frame - the frame to append
    # @return: none
    def write(self, frame: Frame) -> None:
        if not self._open or self._buffer is None or self._header is None:
            raise RuntimeError("the SER writer is not open")
        if frame.width != self._header.width or frame.height != self._header.height:
            raise ValueError(
                f"frame is {frame.width}x{frame.height}, header says "
                f"{self._header.width}x{self._header.height}",
            )
        expected = np.uint8 if self._header.bit_depth == 8 else np.uint16
        if np.dtype(frame.dtype) != np.dtype(expected):
            raise ValueError(
                f"frame dtype {frame.dtype} does not match a "
                f"{self._header.bit_depth}-bit SER",
            )
        array = np.frombuffer(frame.data, dtype=frame.dtype).reshape(
            frame.height, frame.width,
        )
        if not array.flags["C_CONTIGUOUS"]:
            array = np.ascontiguousarray(array)
        if not self._header.little_endian:
            # The SER stores little-endian words. The frame from a big-endian
            # SDK has to be swapped before it is written.
            array = array.byteswap()
        # Write the numpy buffer directly: BufferedWriter accepts a C-contiguous
        # buffer object, so a full frame avoids an extra copy on the writer
        # thread (at 207 MB/s a copy is real bandwidth).
        self._buffer.write(array)
        self._frames_written += 1
        self._bytes_written += int(array.nbytes)
        self._last_write = time.monotonic()

    # @args: none. Flushes, patches the frame count and closes. Idempotent
    # @return: none
    def close(self) -> None:
        if not self._open:
            return
        self._open = False
        try:
            if self._buffer is not None:
                self._buffer.flush()
            if self._raw is not None:
                # The count lives at a fixed offset, and the file is already
                # complete: patch it in place so a crash before the next frame
                # still leaves a valid header.
                self._raw.seek(FRAME_COUNT_OFFSET)
                self._raw.write(struct.pack("<i", self._frames_written))
                self._raw.flush()
        finally:
            if self._buffer is not None:
                self._buffer.close()   # closes the raw file too
            self._buffer = None
            self._raw = None

    # @return: the accounting so far; valid while open and after close()
    def counters(self) -> WriterCounters:
        return WriterCounters(frames_written=self._frames_written)

    # @return: bytes handed to the file so far
    def bytes_written(self) -> int:
        return self._bytes_written

    # @return: seconds between open() and the last write (0 before the first)
    def elapsed_s(self) -> float:
        if not self._started:
            return 0.0
        end = self._last_write if self._last_write else time.monotonic()
        return max(0.0, end - self._started)

    # @return: write rate in MB/s (decimal MB, the unit of ADR-013)
    def mb_per_s(self) -> float:
        elapsed = self.elapsed_s()
        if elapsed <= 0.0:
            return 0.0
        return self._bytes_written / 1_000_000.0 / elapsed

    # @return: the header the file was opened with
    def header(self) -> SerHeader | None:
        return self._header

    # @args: header - standard fields; frame_count - the count to patch later
    # @return: the 178-byte header
    def _header_bytes(self, header: SerHeader, *, frame_count: int) -> bytes:
        when = self._when or datetime.now(timezone.utc)
        ticks = _to_ticks(when)
        return b"".join((
            FILE_ID,
            struct.pack("<i", 0),                       # LuID
            struct.pack("<i", int(header.color_id)),    # ColorID
            struct.pack("<i", 1 if header.little_endian else 0),
            struct.pack("<i", header.width),
            struct.pack("<i", header.height),
            struct.pack("<i", header.bit_depth),
            struct.pack("<i", frame_count),
            _fixed_text(""),                            # Observer
            _fixed_text("SolarScribe"),                 # Instrument
            _fixed_text(""),                            # Telescope
            struct.pack("<q", ticks),                   # DateTime
            struct.pack("<q", ticks),                   # DateTimeUTC
        ))
