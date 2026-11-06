# ADR-020: Resultado de la sesión, visualización del barrido y recon rápido / Session result, scan visualisation and quick recon

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-009 (UI), ADR-011 (flujo de sesión), ADR-018 (post-proceso),
ADR-021 (red).

## Español

**Contexto**: un barrido SHG dura varios minutos y el observador necesita saber
**si va bien** y **si salió bien** sin esperar al post-proceso. Además, el
barrido es abstracto: la rendija se mueve por el disco y sin una representación
visual es difícil seguir qué parte ya se ha capturado.

**Decisión**:

1. **Visualización del barrido en vivo**: sobre una imagen del Sol se dibuja la
   **franja ya capturada**, la **línea de la rendija** y el **porcentaje**
   completado. El fondo es un **disco esquemático** (funciona sin red) y, si hay
   conexión, la **imagen real del Sol** del día (ADR-021).
2. **Recon rápido al terminar**: una reconstrucción **ligera y no autoritativa**
   del disco, para saber si el barrido salió bien. Se ve **solo en pantalla** (no
   se exporta) y **no sustituye al post-proceso**.
3. **Resumen de la sesión**: frames capturados, frames perdidos, duración y ruta,
   con un botón para **abrir la carpeta** de la sesión.

**Alternativas**: no mostrar nada (el observador no sabe si salió bien hasta el
post-proceso); exportar el recon rápido (confunde y compite con el post-proceso).
Se descartan.

**Consecuencias**: feedback inmediato durante y después del barrido; el
post-proceso real (JSol'Ex y las herramientas) sigue siendo externo y el recon
rápido no toca los datos.

## English

**Context**: an SHG scan lasts several minutes and the observer needs to know
**whether it is going well** and **whether it went well** without waiting for
post-processing. On top of that, the scan is abstract: the slit moves across the
disk and without a visual representation it is hard to follow which part has
already been captured.

**Decision**:

1. **Live scan visualisation**: on an image of the Sun, the **already-captured
   strip**, the **slit line** and the **percentage** completed are drawn. The
   background is a **schematic disk** (works offline) and, if there is a
   connection, the day's **real Sun image** (ADR-021).
2. **Quick recon on finish**: a **light, non-authoritative** reconstruction of the
   disk, to know whether the scan went well. It is shown **on screen only** (not
   exported) and **does not replace post-processing**.
3. **Session summary**: captured frames, dropped frames, duration and path, with a
   button to **open the session folder**.

**Alternatives**: show nothing (the observer does not know it went well until
post-processing); export the quick recon (confuses and competes with
post-processing). Dropped.

**Consequences**: immediate feedback during and after the scan; the real
post-processing (JSol'Ex and the tools) remains external and the quick recon does
not touch the data.
