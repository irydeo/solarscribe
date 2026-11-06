# ADR-017: Empaquetado, CI, versionado y licencias / Packaging, CI, versioning and licences

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-004 (empaquetado), ADR-002 (backends), ADR-016 (docs).

## Español

**Contexto**: ADR-004 fijó Windows y Linux desde el MVP. Falta cómo se construye,
se versiona y se licencia, sobre todo porque los SDK de cámara son binarios
propietarios que viajan dentro.

**Decisión**:

- **Integración continua matricial**: el CI construye y prueba en Windows 10/11
  x64 y en Linux; un release no se corta hasta que ambos están verdes.
- **Versionado semántico** (`MAJOR.MINOR.PATCH`); el número vive en un único sitio
  y se refleja en el instalador y en `session_meta.json`.
- **CHANGELOG bilingüe** por release.
- **Licencias**: se revisa la licencia de **redistribución** de cada SDK antes de
  incluirlo; se guarda un fichero de atribución por SDK. Si una licencia lo
  prohíbe, ese SDK no viaja dentro y la app **degrada con elegancia** (dice qué
  falta).
- Se reutiliza el `installer/` de NightScribe (`.iss`, `.spec`, `.deb`, `.rpm`),
  puenteando las diferencias de plataforma (`.dll` vs `.so`, `%APPDATA%` vs XDG,
  udev vs nada).

**Alternativas**: un solo SO en el MVP (contradice el requisito "de serie");
empaquetar los SDK sin revisar licencias (riesgo legal). Se descartan.

**Consecuencias**: el empaquetado es trabajo del MVP, no del final; el tamaño del
instalador crece; cada SDK nuevo exige su revisión de licencia.

## English

**Context**: ADR-004 fixed Windows and Linux from the MVP. How it is built,
versioned and licensed is still missing, especially because the camera SDKs are
proprietary binaries that travel inside.

**Decision**:

- **Matrix CI**: CI builds and tests on Windows 10/11 x64 and Linux; a release is
  not cut until both are green.
- **Semantic versioning** (`MAJOR.MINOR.PATCH`); the number lives in one place and
  is reflected in the installer and in `session_meta.json`.
- **Bilingual CHANGELOG** per release.
- **Licences**: the **redistribution** licence of each SDK is reviewed before it is
  bundled; an attribution file per SDK is kept. If a licence forbids it, that SDK
  does not travel inside and the app **degrades gracefully** (it says what is
  missing).
- NightScribe's `installer/` is reused (`.iss`, `.spec`, `.deb`, `.rpm`), bridging
  the platform differences (`.dll` vs `.so`, `%APPDATA%` vs XDG, udev vs none).

**Alternatives**: a single OS in the MVP (contradicts the "out of the box"
requirement); bundling the SDKs without reviewing licences (legal risk). Dropped.

**Consequences**: packaging is MVP work, not an afterthought; the installer grows;
every new SDK requires its licence review.
