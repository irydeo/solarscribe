#!/bin/sh
# SolarScribe vendor SDK fetch wrapper (Linux and macOS).
# The real work lives in fetch_deps.py so the Windows PowerShell wrapper runs
# exactly the same logic.
set -eu
here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$here/fetch_deps.py" "$@"
