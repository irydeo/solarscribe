# ADR-002: Backends de cámara del MVP / MVP camera backends

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-019 (control de montura por plataforma, que sustituye la
elección de montura de esta ADR).

## Español

**Contexto**: hay que elegir qué marcas de cámara soporta el MVP y con qué
protocolo entra primero la montura.

**Decisión**: los cuatro backends que ya aporta `simple-astro-cap` (ZWO
`libASICamera2`, QHY `libqhyccd`, Player One `libPlayerOneCamera`, Touptek
`libtoupcam`), más el simulador. Se validan primero **Touptek G3M678M** (la
cámara de referencia) y **ZWO** (la más común). La montura entra primero por
**ASCOM/Alpaca**.

**Alternativas**: empezar con un único backend; usar INDI como camino principal
de cámara. Se descarta por rendimiento y porque los backends nativos ya existen.

**Consecuencias**: el riesgo de la capa de cámara baja mucho. Los backends de
Player One y Touptek están escritos pero sin probar en hardware (según su propio
README), así que hay que validarlos; el de QHY tiene quirks conocidos (handle
USB, orden de init) que conviene aislar y probar.

## English

**Context**: the MVP must choose which camera brands it supports and which
protocol the mount uses first.

**Decision**: the four backends `simple-astro-cap` already provides (ZWO
`libASICamera2`, QHY `libqhyccd`, Player One `libPlayerOneCamera`, Touptek
`libtoupcam`), plus the simulator. **Touptek G3M678M** (the reference camera) and
**ZWO** (the most common) are validated first. The mount enters first through
**ASCOM/Alpaca**.

**Alternatives**: start with a single backend; use INDI as the main camera path.
Dropped for performance and because the native backends already exist.

**Consequences**: the camera layer risk drops sharply. The Player One and
Touptek backends are written but untested on hardware (per their own README), so
they must be validated; the QHY one has known quirks (USB handle, init order)
that are best isolated and tested.
