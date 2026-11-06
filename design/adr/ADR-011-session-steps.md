# ADR-011: Flujo de sesión por pasos / Session step flow

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-006 (centrado), ADR-007 (alineación polar), ADR-009 (UI),
ADR-010 (ROI). En NightScribe: ADR-038 (prominencia y lenguaje llano), ADR-043
(pasos y reabrir paso), ADR-055 (asistente en línea).

## Español

**Contexto**: una sesión SHG es una secuencia de puesta en marcha (buscar el Sol,
alinear, preparar la toma) antes de barrer. Si la interfaz presenta todos los
controles a la vez, el observador no sabe por dónde empezar. NightScribe ya
resolvió lo mismo con un flujo de **pasos de proyecto** por los que el usuario se
mueve libremente, con recomendaciones y autoguardado.

**Decisión**: la vista principal es una **sesión por pasos** con el mismo
lenguaje de NightScribe: un **raíl** con el estado de cada paso (pendiente / en
curso / hecho), **navegación libre**, **recomendaciones** (no puertas que
bloqueen), **autoguardado silencioso** y **«reabrir paso»** en los completados.
**Todos los controles están visibles siempre**: el raíl guía, no esconde; no hay
un modo experto aparte.

Los pasos son cuatro:

1. **Buscar el Sol**: GOTO automático al Sol por efeméride y centrado grueso
   sobre la rendija (§8.1–8.2).
2. **Alineación polar**: asistente de alineación solar (§8.3).
3. **ROI**: el usuario selecciona el ROI de captura, se mide el **tilt** y se
   alinea la rendija; se estiman FPS y caudal (§6.1, ADR-010, ADR-022).
4. **Escaneado**: preparación (centrado fino y autocalibración de la tasa, §7) y
   barrido simple o mosaico, con progreso, frames perdidos y stats.

El **centrado/calibrado** no es un paso aparte: es la **preparación del
escaneado** y vive dentro del paso *Escaneado*. Cada paso muestra, en **lenguaje
llano**, qué hace y por qué, un indicador en vivo y **una sola acción principal**
destacada. El visor en vivo y el overlay de ROI permanecen visibles.

**Alternativas**: un formulario único con todos los controles (no guía); un
asistente modal obligatorio (bloquea y no perdona). Se descartan: se guía sin
forzar.

**Consecuencias**: la sesión se lee como una secuencia clara y accesible; el
usuario experto puede saltar pasos y el novel se deja llevar; el estado se
recupera solo. La interfaz se parece a la de NightScribe, así que se aprende una
vez.

## English

**Context**: an SHG session is a setup sequence (find the Sun, align, prepare the
take) before scanning. If the UI shows every control at once, the observer does
not know where to start. NightScribe already solved the same problem with a flow
of **project steps** the user moves through freely, with recommendations and
auto-save.

**Decision**: the main view is a **session by steps** with the same language as
NightScribe: a **rail** showing each step's state (pending / current / done),
**free navigation**, **recommendations** (not blocking gates), **silent
auto-save** and **"reopen step"** on completed ones. **Every control is always
visible**: the rail guides, it does not hide; there is no separate expert mode.

The steps are four:

1. **Find the Sun**: automatic GOTO to the Sun by ephemeris and coarse centring on
   the slit (§8.1–8.2).
2. **Polar alignment**: solar alignment assistant (§8.3).
3. **ROI**: the user selects the capture ROI, the **tilt** is measured and the slit
   is aligned; FPS and data rate are estimated (§6.1, ADR-010, ADR-022).
4. **Scanning**: preparation (fine centring and scan-rate autocalibration, §7) and
   single or mosaic scan, with progress, dropped frames and stats.

**Centring/calibration** is not a separate step: it is the **scan preparation** and
lives inside the *Scanning* step. Each step shows, in **plain language**, what it
does and why, a live indicator and **a single prominent primary action**. The live
viewer and the ROI overlay stay visible.

**Alternatives**: a single form with every control (no guidance); a mandatory
modal wizard (blocking and unforgiving). Dropped: it guides without forcing.

**Consequences**: the session reads as a clear, accessible sequence; the expert
user can skip steps and the newcomer is carried along; the state recovers on its
own. The UI looks like NightScribe's, so it is learned once.
