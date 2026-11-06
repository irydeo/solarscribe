############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - performance bench script module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################

# Standalone ADR-013 bench, for a gate report without pytest's output.
#
#   .venv/bin/python -m tests.perf.bench_capture --seconds 5 \
#       --out /tmp/opencode/g3-capture.md
#
# Exit codes: 0 the budget holds, 1 a metric failed (blocked), 2 the rig is not
# available yet (the simulator or the capture engine is missing), which is not
# a product failure but leaves the budget unverified.

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from tests.perf.budget import report_markdown, violations
from tests.perf.harness import build_rig, measure


# @args: argv - command-line arguments, None for sys.argv
# @return: 0 pass, 1 blocked with numbers, 2 rig unavailable
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SolarScribe ADR-013 capture bench")
    parser.add_argument("--seconds", type=float, default=3.0,
                        help="measurement window after the first frame")
    parser.add_argument("--out", type=Path, default=None,
                        help="write the Markdown report here")
    args = parser.parse_args(argv)

    built = build_rig()
    if built.rig is None:
        print(f"bench not runnable: {built.reason}")
        return 2

    workdir = Path(tempfile.mkdtemp(prefix="solarscribe-bench-"))
    try:
        result = measure(built.rig, args.seconds, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    report = report_markdown(result)
    print(report)
    if args.out is not None:
        args.out.write_text(report, encoding="utf-8")

    failures = violations(result)
    if failures:
        print("\nBLOCKED:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
