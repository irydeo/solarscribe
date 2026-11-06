# INDI and indiserver

- **Project**: INDI Library
- **Verdict**: prerequisite, not redistributed
- **Homepage**: <https://www.indilib.org/>
- **Used by**: the Linux mount backend (INDI client, ADR-019)

## Why it is not bundled

INDI is a distribution package (LGPL-2.1-or-later for the library,
GPL-2.0-or-later for the drivers). SolarScribe talks to a running `indiserver`
and does not copy INDI into its own package. The `.deb` recommends `indi-bin`
and the RPM recommends `indi`; neither is a hard dependency, because the
application must install and start on a machine without a mount.

## What the observer sees

The telescope panel reports that no mount backend is reachable and names
`indiserver` as the missing service. The camera and the SHG engine keep
working, and the mount simulator is available for a dry run (ADR-014).
