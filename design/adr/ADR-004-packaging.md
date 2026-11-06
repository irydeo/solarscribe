# ADR-004: Empaquetado multiplataforma / Cross-platform packaging

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

## Español

**Contexto**: SolarScribe debe instalarse en Windows y Linux sin exigir Python,
y los SDK de cámara son binarios propietarios que hay que distribuir. Las dos
plataformas han de estar **funcionales de serie**, no una detrás de la otra.

**Decisión**: Windows 10/11 x64 con **PyInstaller + Inno Setup** y Linux con
**.deb (Debian/Ubuntu) y .rpm (Fedora/RHEL)**, **ambos desde el MVP**. Los
binarios de los SDK viajan dentro del paquete; en Linux se incluyen las reglas
`udev` y (QHY) el firmware. Una **integración continua matricial** construye y
prueba los dos SO. La app **degrada con elegancia** si falta un SDK: dice qué
falta y sigue. Se reutiliza el `installer/` de NightScribe (`.iss`, `.spec`,
`.deb`, `.rpm`), salvando las diferencias de plataforma (`.dll` vs `.so`,
`%APPDATA%` vs XDG, udev vs nada).

**Alternativas**: depender de la instalación del usuario (peor experiencia);
contenedores (no encaja con USB/udev). Pendiente de validar el tamaño y las
licencias de redistribución de cada SDK.

**Consecuencias**: hay que revisar la licencia de redistribución de cada SDK; los
instaladores crecen; el esfuerzo de empaquetado entra en el MVP y no se deja para
el final.

## English

**Context**: SolarScribe must install on Windows and Linux without requiring
Python, and the camera SDKs are proprietary binaries that must be shipped. Both
platforms must be **functional out of the box**, not one behind the other.

**Decision**: Windows 10/11 x64 with **PyInstaller + Inno Setup** and Linux with
**.deb (Debian/Ubuntu) and .rpm (Fedora/RHEL)**, **both from the MVP**. The SDK
binaries travel inside the package; on Linux the `udev` rules and (QHY) firmware
are included. A **matrix CI** builds and tests both OSes. The app **degrades
gracefully** if an SDK is missing: it says so and carries on. NightScribe's
`installer/` is reused (`.iss`, `.spec`, `.deb`, `.rpm`), bridging the platform
differences (`.dll` vs `.so`, `%APPDATA%` vs XDG, udev vs none).

**Alternatives**: rely on the user installing dependencies (worse experience);
containers (they do not fit USB/udev). Size and redistribution licences of each
SDK are still to be validated.

**Consequences**: the redistribution licence of each SDK must be reviewed; the
installers grow; the packaging effort lands in the MVP instead of at the end.
