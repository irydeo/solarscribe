# Real fixtures (external, never committed)

The functional suite reads real captures from the directory named by
`SOLARSCRIBE_FIXTURES` (ADR-015). The captures do not live in this repository:
they are big, often private, and a clone must stay light.

```bash
export SOLARSCRIBE_FIXTURES=/path/to/your/captures
.venv/bin/python -m pytest tests/functional -q
```

`catalogue.py` is the list of what the suite expects: the file name, what it
contains, where it came from and what it proves. A test whose file is missing
skips with that description, so a fresh clone is green and the observer's
machine is stronger.

To add a capture:

1. Copy the file into the external directory.
2. Add a `FixtureEntry` to `catalogue.py` with a stable `id`, a relative
   `path`, its `kind` (`ser`, `csv`, `ini`, `json`, `video`), a `what` and a
   `tests` sentence. For a SER, add the `expect` fields the header must show.
3. Run `pytest tests/functional -q` and check that the new entry is validated.

The known entries, in catalogue order:

| id | file | kind | proves |
| --- | --- | --- | --- |
| `scan-log-calibration-bug` | `scan_log.csv` | csv | the real session that exposed the ~4.6x fast calibration bug |
| `reference-strip-ser` | `reference_3480x248_16bit.ser` | ser | SER header and the reference strip |
| `real-scan-ser` | `sun_reference_scan01.ser` | ser | limb, rate and centring on a real sweep |
| `session-meta` | `session_meta.json` | json | the post-processing contract (ADR-018) |
| `session-cfg` | `session.cfg` | ini | the ADR-003 inheritance from nightscribe-scan |
