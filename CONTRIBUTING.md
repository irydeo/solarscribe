# Contributing to SolarScribe

Thanks for your interest. SolarScribe is a capture application for a solar
spectroheliograph, GPL-3.

## Code rules

- Code is always **English**: identifiers, comments, headers.
- Documentation lives in `docs/`, in Spanish and English.
- **Strict TDD**: no product change without a test written first that fails
  without it.
- The interface is defined in `ui/*.ui`; custom widgets (viewer, histogram, ROI
  overlay) never enter a `.ui`.
- Every GUI-visible string goes through `self.tr()` (ES/EN).
- Docs in natural language: never the em dash; write with ":", "," and ";".

## Working

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit        # fast, no hardware
.venv/bin/python -m pytest tests/functional  # mocks, videos and hardware
.venv/bin/python -m solarscribe gui          # start the GUI
```

## Licence

By contributing you agree that your work is released under GPL-3.
