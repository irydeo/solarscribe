############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - performance budget module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The ADR-013 budget, in one place, so the bench and the schema cannot drift
# apart. Every constant below is a number the ADR fixes; `test_budget.py`
# asserts that the INI defaults and the reference ROI still agree with them.
#
# The units are the ones the ADR uses: fps, decimal MB/s (1.73 MB/frame at
# 3480x248x16 bit; 1.73 MB/s x 120 = 207 MB/s), percent, milliseconds and
# seconds. MB here is 10^6 bytes, like disk vendors and like the ADR text.

from __future__ import annotations

from dataclasses import dataclass, field

# The reference strip of DESIGN.md 6.2 and ADR-013. capture is SENSOR pixels;
# band is FRAME pixels (ARCHITECTURE 2.2); the band sits inside the strip.
REFERENCE_CAPTURE = (0, 0, 3480, 248)
REFERENCE_BAND = (0, 40, 3480, 160)
PIXEL_BYTES = 2                          # 16 bit mono, the SER contract
FRAME_BYTES = 3480 * 248 * PIXEL_BYTES   # 1_726_080 bytes = 1.726 MB

# ADR-013, "Presupuesto de rendimiento".
TARGET_FPS = 120.0
MIN_THROUGHPUT_MB_S = 207.0
MAX_DROPPED_PCT = 0.1
MAX_SEQUENCE_GAPS = 0
MAX_LATENCY_MS = 150.0
QUEUE_BUDGET_MB = 512.0
MIN_DISK_MB_S = 250.0
MAX_CAPTURE_START_S = 5.0
MAX_STALL_S = 3.0


@dataclass(frozen=True)
class Measurement:
    # One run of the bench. Every field is measured, not assumed: the report
    # prints it and the gate reads it. A None means "could not be measured"
    # (for example the latency when no frame carried a timestamp), which is
    # reported as unverified instead of silently passing.
    seconds: float = 0.0
    frames: int = 0
    fps: float = 0.0
    frame_bytes: int = 0
    throughput_mb_s: float = 0.0
    dropped_pct: float = 0.0
    sdk_drops: int = 0
    queue_drops: int = 0
    sequence_gaps: int = 0
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    latency_max_ms: float | None = None
    capture_start_s: float = 0.0
    queue_high_water_mb: float = 0.0
    disk_mb_s: float = 0.0
    disk_capability_mb_s: float | None = None
    rss_start_mb: float = 0.0
    rss_peak_mb: float = 0.0
    rss_end_mb: float = 0.0
    cpu_percent: float = 0.0
    recording: bool = False
    notes: tuple[str, ...] = ()
    extras: dict[str, float] = field(default_factory=dict)

    # @args: name - a stable key for the extras
    # @return: the extra measurement, or 0.0 when it was not taken
    def extra(self, name: str) -> float:
        return float(self.extras.get(name, 0.0))


# @args: measurement - one bench run
# @return: [(metric, measured, budget, verdict)] with verdict in
#          {"pass", "FAIL", "unverified"}. Unverified is not a pass: the gate
#          report names it, and the bench test that owns that metric skips.
def checks(measurement: Measurement) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []

    def add(name: str, measured: float, budget: float, ok: bool, unit: str):
        rows.append((name, f"{measured:.3f} {unit}".strip(),
                     f"{budget:.3f} {unit}".strip(),
                     "pass" if ok else "FAIL"))

    add("fps", measurement.fps, TARGET_FPS, measurement.fps >= TARGET_FPS, "fps")
    add("throughput", measurement.throughput_mb_s, MIN_THROUGHPUT_MB_S,
        measurement.throughput_mb_s >= MIN_THROUGHPUT_MB_S, "MB/s")
    add("dropped", measurement.dropped_pct, MAX_DROPPED_PCT,
        measurement.dropped_pct <= MAX_DROPPED_PCT, "%")
    add("sequence gaps", float(measurement.sequence_gaps),
        float(MAX_SEQUENCE_GAPS),
        measurement.sequence_gaps <= MAX_SEQUENCE_GAPS, "")
    add("capture start", measurement.capture_start_s, MAX_CAPTURE_START_S,
        measurement.capture_start_s <= MAX_CAPTURE_START_S, "s")

    if measurement.latency_p95_ms is None:
        rows.append(("viewer latency", "not measured", f"<= {MAX_LATENCY_MS:.0f} ms",
                     "unverified"))
    else:
        add("viewer latency (p95)", measurement.latency_p95_ms, MAX_LATENCY_MS,
            measurement.latency_p95_ms <= MAX_LATENCY_MS, "ms")

    if measurement.recording:
        add("queue high water", measurement.queue_high_water_mb, QUEUE_BUDGET_MB,
            measurement.queue_high_water_mb <= QUEUE_BUDGET_MB, "MB")
        # The writer must keep up with the stream it is fed. Comparing it to
        # the 250 MB/s disk figure would be wrong here: the disk check below
        # measures the storage, this one measures the writer at the achieved
        # stream rate. A 2% tolerance absorbs the measurement window.
        keep_up = measurement.disk_mb_s + 1e-6 >= 0.98 * measurement.throughput_mb_s
        rows.append((
            "disk writer",
            f"{measurement.disk_mb_s:.3f} MB/s",
            f">= {0.98 * measurement.throughput_mb_s:.3f} MB/s (stream)",
            "pass" if keep_up else "FAIL",
        ))
    else:
        rows.append(("queue high water", "not measured",
                     f"<= {QUEUE_BUDGET_MB:.0f} MB", "unverified"))
        rows.append(("disk writer", "not measured", ">= stream", "unverified"))

    # ADR-013's 250 MB/s is a storage capability, measured with a raw write.
    if measurement.disk_capability_mb_s is None:
        rows.append(("disk capability", "not measured",
                     f">= {MIN_DISK_MB_S:.0f} MB/s", "unverified"))
    else:
        add("disk capability", measurement.disk_capability_mb_s, MIN_DISK_MB_S,
            measurement.disk_capability_mb_s >= MIN_DISK_MB_S, "MB/s")

    return rows


# @args: measurement - one bench run
# @return: the failing checks as sentences with the numbers, so a blocked gate
#          can be quoted without opening the report
def violations(measurement: Measurement) -> list[str]:
    return [
        f"{name}: measured {measured}, budget {budget}"
        for name, measured, budget, verdict in checks(measurement)
        if verdict == "FAIL"
    ]


# @args: measurement - one bench run
# @return: a Markdown table plus the notes, ready for the gate report
def report_markdown(measurement: Measurement) -> str:
    lines = [
        "| Metric | Measured | Budget | Verdict |",
        "| --- | --- | --- | --- |",
    ]
    for name, measured, budget, verdict in checks(measurement):
        lines.append(f"| {name} | {measured} | {budget} | {verdict} |")

    lines += [
        "",
        f"- frames: {measurement.frames} over {measurement.seconds:.3f} s",
        f"- frame size: {measurement.frame_bytes} bytes",
        f"- SDK drops: {measurement.sdk_drops}; queue drops: "
        f"{measurement.queue_drops}; host sequence gaps: "
        f"{measurement.sequence_gaps}",
        f"- latency p50/max: {_fmt(measurement.latency_p50_ms)} / "
        f"{_fmt(measurement.latency_max_ms)} ms",
        f"- writer rate: {measurement.disk_mb_s:.1f} MB/s; disk capability: "
        f"{_fmt(measurement.disk_capability_mb_s)} MB/s",
        f"- RSS start/peak/end: {measurement.rss_start_mb:.1f} / "
        f"{measurement.rss_peak_mb:.1f} / {measurement.rss_end_mb:.1f} MB",
        f"- process CPU: {measurement.cpu_percent:.1f}% of one core "
        f"(includes the simulator thread; not an isolated pipeline figure)",
        f"- recording: {'yes' if measurement.recording else 'no'}",
    ]
    for note in measurement.notes:
        lines.append(f"- NOTE: {note}")
    return "\n".join(lines)


# @args: value - a float or None
# @return: a fixed-format string, or "n/a" when the metric was not measured
def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"
