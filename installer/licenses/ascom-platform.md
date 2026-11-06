# ASCOM Platform and its .NET runtime

- **Vendor**: ASCOM Initiative
- **Verdict**: prerequisite, not redistributed
- **Homepage**: <https://ascom-standards.org/>
- **Used by**: the Windows mount backend (ASCOM COM, ADR-019)

## Why it is not bundled

The ASCOM Platform is a separate Windows installation with its own licence.
SolarScribe does not redistribute it. The Inno Setup installer checks the
registry for `SOFTWARE\ASCOM\Platform` and, when it is absent, tells the
observer what the mount is missing and where to get it. The camera and the SHG
engine keep working without it, and the mount simulator is available for a dry
run.

The ASCOM Platform installer brings or checks the .NET runtime it needs. The
.NET runtime is an OS component with its own licence and is not part of this
package either.

## What the observer sees

The telescope panel reports that no mount backend is available and names the
ASCOM Platform as the missing piece. Nothing crashes and no scan is started
against a mount that is not there (ADR-014, ADR-019).
