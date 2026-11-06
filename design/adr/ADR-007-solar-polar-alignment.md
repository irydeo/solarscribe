# ADR-007: Alineación polar solar / Solar polar alignment

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

## Español

**Contexto**: de día no se ve Polaris, pero el SHG necesita buen seguimiento (la
tasa de barrido y el centrado en Dec dependen de él). El Sol sobre la rendija da
una referencia precisa en Dec.

**Decisión**: un **asistente de alineación polar solar** basado en deriva.

- Muestrea la posición en Dec del Sol cada pocos minutos (por el limbo o por la
  cuerda) y **resta el movimiento propio del Sol** (efeméride, hasta ~0.4"/min).
- Ajusta la recta de deriva y deduce el error de **azimut** y **altitud**.
- Guía al usuario (cuánto girar cada tornillo) y pide una **segunda medida de
  confirmación**.
- Recomienda **cuándo** medir: cerca del meridiano para la altitud y hacia el
  Este/Oeste para el azimut.

**Alternativas**: medir la Dec solo por la cuerda (tiene zona muerta cerca del
centro: hay que medir en el limbo o desplazar la rendija). Se documenta como
condición de la medida.

**Consecuencias**: alineación polar de día, sin hardware extra. Requiere tiempo
(decenas de minutos) y la geometría del Sol limita qué error se separa en cada
momento.

## English

**Context**: Polaris is not visible during the day, but the SHG needs good
tracking (the scan rate and the Dec centring depend on it). The Sun on the slit
gives a precise Dec reference.

**Decision**: a drift-based **solar polar alignment assistant**.

- Samples the Sun's Dec every few minutes (through the limb or the chord) and
  **subtracts the Sun's own motion** (ephemeris, up to ~0.4"/min).
- Fits the drift line and derives the **azimuth** and **altitude** error.
- Guides the user (how much to turn each knob) and asks for a **second
  confirmation measurement**.
- Recommends **when** to measure: near the meridian for altitude and towards the
  East/West for azimuth.

**Alternatives**: measure Dec by the chord only (it has a dead zone near the
centre: measure at the limb or offset the slit). This is documented as a
condition of the measurement.

**Consequences**: daytime polar alignment with no extra hardware. It takes time
(tens of minutes) and the Sun's geometry limits which error can be separated at
any moment.
