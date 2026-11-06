############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - fixtures catalogue module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# The catalogue of real captures used by the functional suite (ADR-015).
#
# The captures themselves never travel in the repository: they are big, often
# private, and a git clone must stay light. They live under the directory named
# by SOLARSCRIBE_FIXTURES; this module only records what each one is, where it
# came from and what it proves. A test that needs one skips when it is missing,
# so the suite is green on a fresh clone and stronger on the observer's machine.
#
# Add an entry whenever the user provides a capture; the `what` and `tests`
# fields are the reason the file is worth keeping. `expect` is checked against
# the file itself (SER header fields, for example) before any product code
# touches it, so a truncated or renamed copy fails loudly.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

# Kinds the functional suite knows how to validate. `video` is here for the
# future AVI/SER exports; a test that does not know the kind skips it.
KINDS = ("ser", "csv", "ini", "json", "video")


@dataclass(frozen=True)
class FixtureEntry:
    # One catalogued capture.
    #
    # path is relative to SOLARSCRIBE_FIXTURES and uses forward slashes on every
    # platform. expect is a tuple of pairs (never a dict) so the entry stays
    # frozen and hashable; dict(entry.expect) is the convenient view.
    id: str
    path: str
    kind: str
    what: str
    tests: str
    source: str
    required: bool = False
    expect: tuple[tuple[str, object], ...] = ()

    # @args: none
    # @return: the expected fields as a plain dict
    def expected(self) -> dict[str, object]:
        return dict(self.expect)


# The session that exposed the scan-rate calibration bug in nightscribe-scan.
# The prototype tests at nightscribe-scan/tests/test_calibration.py read the
# same file; keeping it here anchors SolarScribe's calibration to the real
# observations, not to a synthetic curve.
SCAN_LOG = FixtureEntry(
    id="scan-log-calibration-bug",
    path="scan_log.csv",
    kind="csv",
    what=(
        "The 2026-11-04 nightscribe-scan session log that exposed the scan-rate "
        "calibration bug: actual_xy 3.4 to 4.1 and calibration_factor 0.242, "
        "about 4.6x too slow"
    ),
    tests=(
        "SHG calibration regression: the old target/measured factor must stay "
        "rejected and the corrected rate must make the sky move at "
        "PIXEL_SCALE x fps"
    ),
    source="nightscribe-scan tests/fixtures (real user session)",
    expect=(
        ("min_rows", 5),
        ("min_fps", 100.0),
        ("min_actual_xy", 3.0),
        ("max_calibration_factor", 0.5),
    ),
)

# One strip of the reference ROI, mono 16 bit. It is the smallest useful SER:
# it exercises the header, the byte order and the frame size without gigabytes.
REFERENCE_STRIP = FixtureEntry(
    id="reference-strip-ser",
    path="reference_3480x248_16bit.ser",
    kind="ser",
    what="The reference capture ROI, mono 16 bit, 3480x248 px",
    tests=(
        "SER header/ROI contract (ADR-018) and the SHG limb and tilt metrics "
        "on the reference strip"
    ),
    source="user capture, reference Touptek G3M678M",
    expect=(
        ("width", 3480),
        ("height", 248),
        ("bit_depth", 16),
        ("color_id", 0),
    ),
)

# One full daylight sweep, one row of a mosaic. This is the fixture that checks
# the science end to end: limb, calibration and the shape of the reconstructed
# disk.
REAL_SCAN = FixtureEntry(
    id="real-scan-ser",
    path="sun_reference_scan01.ser",
    kind="ser",
    what="One complete daylight sweep of the disk (one mosaic row), mono 16 bit",
    tests=(
        "SHG engine metrics end to end: limb detection, scan-rate calibration "
        "and Dec centring on a real sweep"
    ),
    source="user capture",
    expect=(
        ("bit_depth", 16),
        ("color_id", 0),
    ),
)

# The metadata of the same take: the contract with the post-processing
# (ADR-018), including the effective ROI, the tilt and the drop counters.
SESSION_META = FixtureEntry(
    id="session-meta",
    path="session_meta.json",
    kind="json",
    what="session_meta.json of the same take: effective ROI, tilt, drops, version",
    tests="ADR-018 post-processing contract: the fields the tools already read",
    source="user capture",
)

# The prototype INI of the same session. It locks the ADR-003 inheritance to a
# file the user actually ran, not to a hand-written test string.
SESSION_CFG = FixtureEntry(
    id="session-cfg",
    path="session.cfg",
    kind="ini",
    what="The nightscribe-scan INI of the same session",
    tests=(
        "ADR-003 inheritance: the prototype sections and keys load with the "
        "same meanings and the SolarScribe defaults fill the rest"
    ),
    source="nightscribe-scan tests/fixtures (real user profile)",
)


CATALOGUE: tuple[FixtureEntry, ...] = (
    SCAN_LOG,
    REFERENCE_STRIP,
    REAL_SCAN,
    SESSION_META,
    SESSION_CFG,
)


# @args: path - the catalogue path field
# @return: whether it is a safe relative path that cannot escape the fixtures
#          root (absolute paths and ".." are rejected)
def is_safe_relative(path: str) -> bool:
    if not path or "\\" in path:
        return False
    pure = PurePosixPath(path)
    return bool(pure.parts) and not pure.is_absolute() and ".." not in pure.parts


# @args: entry_id - the stable id used by the tests
# @return: the entry, or None when the id is not catalogued
def by_id(entry_id: str) -> FixtureEntry | None:
    for entry in CATALOGUE:
        if entry.id == entry_id:
            return entry
    return None
