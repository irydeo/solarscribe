# ADR-021: Política de red y efemérides locales / Network policy and local ephemerides

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-016 (i18n y docs), ADR-020 (resultado), ADR-007 (polar).

## Español

**Contexto**: SolarScribe nace como aplicación **local**, sin nube ni telemetría,
pensada para un observatorio que puede no tener conexión. Pero necesita la
posición del Sol (para el GOTO, la geometría del barrido y la alineación polar) y,
opcionalmente, una imagen real del Sol para la visualización.

**Decisión**:

1. **Efemérides locales**: la posición del Sol, su diámetro y ángulo aparente y su
   rotación se calculan **localmente** (sin internet). El GOTO, la geometría del
   barrido y la alineación polar no dependen de la red.
2. **Red solo para la imagen del Sol**: la red se usa **opcionalmente** para la
   imagen real del Sol (SDO) del calendario y de la visualización del barrido. Si
   no hay conexión, se muestra el **disco esquemático** y todo sigue.
3. **Sin telemetría**: nunca se envía nada.

**Alternativas**: servicios externos para las efemérides (dependencia, latencia y
fallo si no hay red); todo online (rompe el uso en un observatorio sin conexión).
Se descartan.

**Consecuencias**: la app funciona completa sin conexión; la imagen real del Sol
es un extra que, si falta, no bloquea nada.

## English

**Context**: SolarScribe is born as a **local** application, with no cloud and no
telemetry, meant for an observatory that may have no connection. But it needs the
Sun's position (for the GOTO, the scan geometry and the polar alignment) and,
optionally, a real Sun image for the visualisation.

**Decision**:

1. **Local ephemerides**: the Sun's position, its apparent diameter and angular
   size and its rotation are computed **locally** (no internet). The GOTO, the scan
   geometry and the polar alignment do not depend on the network.
2. **Network only for the Sun image**: the network is used **optionally** for the
   day's real Sun image (SDO) in the calendar and the scan visualisation. If there
   is no connection, the **schematic disk** is shown and everything carries on.
3. **No telemetry**: nothing is ever sent.

**Alternatives**: external services for the ephemerides (dependency, latency and
failure without a network); everything online (breaks use in an observatory with
no connection). Dropped.

**Consequences**: the app works fully offline; the real Sun image is an extra
that, if missing, blocks nothing.
