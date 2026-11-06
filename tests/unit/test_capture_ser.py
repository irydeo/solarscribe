############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - SER writer test module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The SER header is the contract with the post-processing (ADR-018): its
# standard fields must not move, and the frame count must be patched on close so
# an interrupted recording is still readable.

import struct
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from solarscribe.capture.abc import SerColorId, SerHeader, SerWriter, WriterCounters
from solarscribe.capture.ser import (
    FILE_ID, FRAME_COUNT_OFFSET, HEADER_SIZE, SerWriterImpl,
)
from solarscribe.devices.sim import SimFrame


def _frame(width=8, height=4, fill=7, dtype=np.uint16):
    array = np.full((height, width), fill, dtype=dtype)
    return SimFrame(array, (0, 0, width, height), sequence=0, timestamp=0.0)


def _read_header(path):
    raw = Path(path).read_bytes()
    return raw, {
        "file_id": raw[0:14],
        "luid": struct.unpack_from("<i", raw, 14)[0],
        "color_id": struct.unpack_from("<i", raw, 18)[0],
        "little_endian": struct.unpack_from("<i", raw, 22)[0],
        "width": struct.unpack_from("<i", raw, 26)[0],
        "height": struct.unpack_from("<i", raw, 30)[0],
        "bit_depth": struct.unpack_from("<i", raw, 34)[0],
        "frame_count": struct.unpack_from("<i", raw, 38)[0],
    }


def test_writer_satisfies_the_contract():
    assert isinstance(SerWriterImpl(), SerWriter)


def test_header_has_the_standard_fields(tmp_path):
    path = tmp_path / "one.ser"
    when = datetime(2026, 11, 6, 12, 0, 0, tzinfo=timezone.utc)
    writer = SerWriterImpl(when=when)
    writer.open(path, SerHeader(width=8, height=4, bit_depth=16,
                                color_id=SerColorId.MONO, roi=(0, 0, 8, 4)))
    writer.close()

    raw, header = _read_header(path)
    assert len(raw) == HEADER_SIZE
    assert header["file_id"] == FILE_ID
    assert header["luid"] == 0
    assert header["color_id"] == int(SerColorId.MONO)
    assert header["little_endian"] == 1
    assert header["width"] == 8
    assert header["height"] == 4
    assert header["bit_depth"] == 16
    assert header["frame_count"] == 0
    # .NET ticks since 0001-01-01.
    ticks = struct.unpack_from("<q", raw, 162)[0]
    assert ticks == int((when - datetime(1, 1, 1, tzinfo=timezone.utc))
                        .total_seconds() * 10_000_000)


def test_frames_are_written_raw_and_the_count_is_patched(tmp_path):
    path = tmp_path / "three.ser"
    writer = SerWriterImpl()
    writer.open(path, SerHeader(width=8, height=4, bit_depth=16))
    for i in range(3):
        writer.write(_frame(fill=i + 1))
    assert writer.counters() == WriterCounters(frames_written=3)
    writer.close()

    raw, header = _read_header(path)
    assert header["frame_count"] == 3
    assert len(raw) == HEADER_SIZE + 3 * 8 * 4 * 2
    first = np.frombuffer(raw[HEADER_SIZE:HEADER_SIZE + 8 * 4 * 2],
                          dtype="<u2")
    assert np.all(first == 1)
    second = np.frombuffer(raw[HEADER_SIZE + 8 * 4 * 2:
                               HEADER_SIZE + 2 * 8 * 4 * 2], dtype="<u2")
    assert np.all(second == 2)


def test_close_is_idempotent_and_preserves_the_file(tmp_path):
    path = tmp_path / "twice.ser"
    writer = SerWriterImpl()
    writer.open(path, SerHeader(width=8, height=4))
    writer.write(_frame())
    writer.close()
    writer.close()
    _, header = _read_header(path)
    assert header["frame_count"] == 1


def test_eight_bit_frames_are_written_as_one_byte_per_pixel(tmp_path):
    path = tmp_path / "eight.ser"
    writer = SerWriterImpl()
    writer.open(path, SerHeader(width=8, height=4, bit_depth=8))
    writer.write(_frame(dtype=np.uint8, fill=3))
    writer.close()
    raw, header = _read_header(path)
    assert header["bit_depth"] == 8
    assert len(raw) == HEADER_SIZE + 8 * 4
    assert raw[HEADER_SIZE] == 3


def test_wrong_frame_shape_or_depth_is_refused(tmp_path):
    writer = SerWriterImpl()
    writer.open(tmp_path / "bad.ser", SerHeader(width=8, height=4, bit_depth=16))
    with pytest.raises(ValueError):
        writer.write(_frame(width=7))
    with pytest.raises(ValueError):
        writer.write(_frame(dtype=np.uint8))
    writer.close()
    with pytest.raises(RuntimeError):
        writer.write(_frame())


def test_big_endian_header_swaps_the_frame_words(tmp_path):
    path = tmp_path / "be.ser"
    writer = SerWriterImpl()
    writer.open(path, SerHeader(width=2, height=1, bit_depth=16,
                                little_endian=False))
    writer.write(_frame(width=2, height=1, fill=0x0102))
    writer.close()
    raw, header = _read_header(path)
    assert header["little_endian"] == 0
    # 0x0102 native little endian is 02 01; swapped it is 01 02.
    assert raw[HEADER_SIZE:HEADER_SIZE + 2] == b"\x01\x02"


def test_write_rate_is_available_to_the_engine(tmp_path):
    path = tmp_path / "rate.ser"
    writer = SerWriterImpl()
    writer.open(path, SerHeader(width=8, height=4))
    for _ in range(10):
        writer.write(_frame())
    writer.close()
    assert writer.bytes_written() == 10 * 8 * 4 * 2
    assert writer.mb_per_s() >= 0.0
    assert writer.header().width == 8
