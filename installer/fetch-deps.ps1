# SolarScribe vendor SDK fetch wrapper (Windows PowerShell).
# The real work lives in fetch_deps.py so the Linux wrapper runs the same
# logic. Run from the repository root:
#   .\installer\fetch-deps.ps1 -Platform windows -AcceptLicences
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
python "$here\fetch_deps.py" @args
exit $LASTEXITCODE
