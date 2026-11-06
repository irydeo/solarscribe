# ADR-014: Errores y degradación / Errors and degradation

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-002 (backends), ADR-004 (empaquetado), ADR-013 (presupuesto).

## Español

**Contexto**: en captura hay fallos esperables que no deben tumbar la app:
un SDK que no está, una cámara que se desconecta a mitad de barrido, el disco que
se llena, el stream que se atasca. La respuesta a cada uno debe estar decidida,
no improvisada.

**Decisión**: una política explícita de degradación y de error.

- **SDK ausente**: el backend no aparece; la app dice qué falta y sigue con los
  demás (degradación elegante).
- **Desconexión de dispositivo**: se pausa y se aborta el barrido, se **preserva
  el SER ya escrito**, se avisa en lenguaje llano y se ofrece reconectar.
- **Disco lleno**: antes de empezar, si hay menos de 1 GB libre se avisa y no se
  arranca; durante el barrido, se detiene de forma limpia y se preserva el SER.
- **Stall del stream**: si pasan más de 3 s sin frames, se aborta el barrido y se
  marca el SER.
- **Frames perdidos**: se contabilizan siempre; si se supera la tolerancia
  (ADR-013), se avisa y queda registrado en `session_meta.json`.
- **Error de SDK**: se captura, se traduce a un mensaje llano (con qué dispositivo
  y qué se puede hacer) y nunca se muestra un código crudo.

**Alternativas**: dejar que una excepción suba y cierre la app (pierde el trabajo
del observador); silenciar los fallos (peor: corrompe la reconstrucción sin
avisar). Se descartan.

**Consecuencias**: el peor caso es una sesión parcial pero íntegra y explicada; el
QE prueba cada camino con el simulador (desconexión, disco lleno, stall).

## English

**Context**: in capture there are expected failures that must not take the app
down: a missing SDK, a camera disconnecting mid-scan, a disk filling up, a stalled
stream. The response to each must be decided, not improvised.

**Decision**: an explicit degradation and error policy.

- **Missing SDK**: the backend does not appear; the app says what is missing and
  carries on with the others (graceful degradation).
- **Device disconnect**: the scan is paused and aborted, the **SER already
  written is preserved**, a plain-language warning is shown and reconnecting is
  offered.
- **Full disk**: before starting, if less than 1 GB is free it warns and does not
  start; during the scan it stops cleanly and preserves the SER.
- **Stream stall**: if more than 3 s pass without frames, the scan is aborted and
  the SER is flagged.
- **Dropped frames**: always counted; if the tolerance is exceeded (ADR-013), it
  warns and is recorded in `session_meta.json`.
- **SDK error**: caught, translated into a plain message (which device and what
  can be done) and never shown as a raw code.

**Alternatives**: let an exception bubble up and close the app (loses the
observer's work); silence the failures (worse: corrupts the reconstruction
silently). Dropped.

**Consequences**: the worst case is a partial but whole and explained session; QE
tests each path with the simulator (disconnect, full disk, stall).
