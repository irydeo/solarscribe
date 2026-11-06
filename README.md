# SolarScribe

Capture application for a solar **spectroheliograph (SHG)**. Cross-platform
(Linux and Windows), SHG-only, no post-processing. Sibling project of
[NightScribe](https://github.com/irydeo/nightscribe), with the same patterns and
development rules.

The design is still in progress; this repository is the application itself.

## Layout

```
solarscribe/
  AGENTS.md                    working rules + agent team
  .opencode/agents/            the seven agent definitions
  design/                      design, contracts and ADRs
  solarscribe/                 the Python package
    devices/ capture/ shg/ ui/ cli/ config/
  tests/  installer/  docs/    tests, installers, user guide
  pyproject.toml
```

## Documentation

- **[docs/user-guide/](docs/user-guide/)**: the user guide (Spanish and English).
- **[docs/install/](docs/install/)**: installation on Windows and Linux.
- **[CHANGELOG.md](CHANGELOG.md)** / **[CHANGELOG.es.md](CHANGELOG.es.md)**.
- **Design**: [design/DESIGN.md](design/DESIGN.md),
  [design/ARCHITECTURE.md](design/ARCHITECTURE.md) and [design/adr/](design/adr/).

## Working

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit        # fast, no hardware
.venv/bin/python -m pytest tests/functional  # mocks, videos and hardware
.venv/bin/python -m solarscribe gui          # start the GUI
```

See [AGENTS.md](AGENTS.md) for the working rules and the agent team.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

GPL-3. See [LICENSE](LICENSE).
