# ADR-008: Base en simple-astro-cap / Base on simple-astro-cap

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

## Español

**Contexto**: la parte más cara y arriesgada de SolarScribe es la capa de cámara
(muchos SDK, alta tasa). Existe un proyecto, `simple-astro-cap`
(<https://github.com/sweisman/simple-astro-cap>), que ya resuelve esa capa para
cuatro marcas con Python + PySide6 + `ctypes`.

**Decisión**: derivar de `simple-astro-cap` la **capa de cámara** (ABC
`CameraBase`, agregador `MultiCamera` y los backends ZWO/QHY/Player One/Touptek
con sus SDK), el **pipeline** (harness de hilos y cola) y el **grabador SER**,
integrándolos en `devices/` y `capture/`. Se conserva la **atribución** (aviso de
copyright y de modificaciones) y se mantiene **GPL-3**, la misma licencia que
NightScribe y que la suya. El resto (motor SHG, montura, UI, configuración) es
propio.

**Alternativas**: implementar la capa de cámara desde cero (mucho más coste y
riesgo); usar INDI como camino principal (peor rendimiento). Se descartan.

**Consecuencias**: el riesgo de la capa de cámara queda prácticamente resuelto;
se hereda también su deuda (Player One y Touptek sin probar, QHY con quirks,
proyecto Linux-only con notas de portabilidad a Windows). Obligaciones de la
GPL-3: mantener la licencia, los avisos y señalar los cambios.

## English

**Context**: the most expensive and risky part of SolarScribe is the camera
layer (many SDKs, high rate). A project exists, `simple-astro-cap`
(<https://github.com/sweisman/simple-astro-cap>), that already solves that layer
for four brands with Python + PySide6 + `ctypes`.

**Decision**: derive from `simple-astro-cap` the **camera layer** (`CameraBase`
ABC, `MultiCamera` aggregator and the ZWO/QHY/Player One/Touptek backends with
their SDKs), the **pipeline** (thread/queue harness) and the **SER recorder**,
integrating them into `devices/` and `capture/`. **Attribution** is kept
(copyright and modification notices) and **GPL-3** is maintained, the same
licence as NightScribe and as theirs. Everything else (SHG engine, mount, UI,
configuration) is our own.

**Alternatives**: implement the camera layer from scratch (far more cost and
risk); use INDI as the main path (worse performance). Dropped.

**Consequences**: the camera layer risk is essentially resolved; its debt is
inherited too (Player One and Touptek untested, QHY quirks, Linux-only project
with Windows porting notes). GPL-3 obligations: keep the licence, the notices
and state the changes.
