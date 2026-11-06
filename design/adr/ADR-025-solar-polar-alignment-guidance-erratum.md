# ADR-025: Corrección de la guía de alineación polar solar / Solar polar alignment guidance erratum

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-007 (asistente de alineación polar solar), ADR-006
(centrado), ADR-021 (efemérides locales), `solarscribe/shg/polar.py`.

## Español

**Contexto**: ADR-007 decide un asistente de alineación polar por deriva: mide
la Dec del Sol cada pocos minutos, resta el movimiento propio del Sol por
efeméride (ADR-021), ajusta la deriva y deduce el error de azimut y de altitud.
Su decisión es correcta y no se toca.

La guía de **cuándo** medir que ADR-007 escribe está invertida: dice "cerca del
meridiano para la altitud, y hacia el Este/Oeste para el azimut". La derivación
con vectores de rotación da la relación opuesta. Con `H` el ángulo horario, `φ`
la latitud, `α` el error de altitud (positivo, eje demasiado alto) y `β` el error
de azimut (positivo, eje al este del polo):

```
d(Dec)/dt = -omega * [ alpha * sin(H) + beta * cos(phi) * cos(H) ]
```

En el meridiano (`H = 0`) solo contribuye el azimut; en el horizonte este u
oeste (`H = +-90 grados`) solo contribuye la altitud. El procedimiento clásico
de deriva (AstroPixels, F. Espenak, "Polar Alignment Using Drift Method")
también mide el azimut en el meridiano y la altitud en el horizonte este u
oeste. La frase de ADR-007 intercambió las dos ventanas. Un ADR aceptado no se
reescribe, así que la corrección vive en este ADR.

**Decisión**:

1. **La guía corregida es: azimut cerca del meridiano (`H ~ 0`), altitud cerca
   del horizonte este u oeste (`|H| ~ 90 grados`).** Es la ventana en la que el
   término correspondiente domina y el otro se anula; fuera de ella los dos
   errores se mezclan y el ajuste no los separa.
2. **Los signos son los de la derivación y los de la tabla publicada.** Un eje
   al este del polo hace derivar el Sol al sur en el meridiano; un eje
   demasiado alto lo hace derivar al sur en el horizonte oeste y al norte en el
   este. El contrato `PolarResult` conserva su convención: azimut positivo al
   este, altitud positiva demasiado alta.
3. **La decisión de ADR-007 no cambia**: muestreo, resta de la efeméride,
   ajuste de la deriva, guía al usuario y segunda medida de confirmación siguen
   siendo el modelo. Cambia solo la ventana recomendada y la explicación.
4. **El código es la referencia.** `solarscribe/shg/polar.py` implementa la
   relación y sus pruebas fijan los signos y las tasas (una desviación de 60"
   da 0.262"/min en el máximo, Canburytech). La UI debe recomendar las ventanas
   corregidas y la documentación no debe repetir la frase invertida.
5. **La geometría del Sol limita la medida.** De día el Sol recorre de este a
   oeste; para separar azimut y altitud hay que muestrear en las dos ventanas,
   lo que reparte la medida en decenas de minutos. Esto ya era una consecuencia
   de ADR-007 y sigue vigente.

**Alternativas**:

- **Dejar ADR-007 como está y que el código lo contradiga**: el lector seguiría
  la guía equivocada y mediría cada error en la ventana donde no domina. Se
  descarta.
- **Reescribir ADR-007**: los ADR aceptados no se reescriben; el proceso exige
  un ADR nuevo que los referencie. Se descarta.
- **Medir solo un error cada vez con una sola ventana**: más lento y no separa
  los dos errores; la segunda medida de confirmación ya cubre la validación.
  Se descarta.
- **Corregir la inclinación con la deriva en RA**: la deriva en RA está dominada
  por el error de reloj y por la refracción; la Dec es la señal limpia. Se
  descarta.

**Consecuencias**: la guía escrita coincide con la física y con el procedimiento
publicado; la UI puede decir al observador en qué momento medir cada tornillo;
el modelo y el contrato de ADR-007 siguen valiendo sin cambios. El coste es una
errata documentada y una frase corregida en la guía de usuario y en DESIGN.md
§8.3. La separación real de los dos errores sigue limitada por la hora angular
del Sol, como ADR-007 ya advertía.

## English

**Context**: ADR-007 decides a drift-based polar alignment assistant: it samples
the Sun's Dec every few minutes, subtracts the Sun's own motion from the local
ephemeris (ADR-021), fits the drift and derives the azimuth and altitude error.
That decision is correct and is not touched.

The guidance about **when** to measure that ADR-007 writes is inverted: it says
"near the meridian for altitude, and towards the East/West for azimuth". The
rotation-vector derivation gives the opposite relation. With `H` the hour angle,
`φ` the latitude, `α` the altitude error (positive, axis too high) and `β` the
azimuth error (positive, axis east of the pole):

```
d(Dec)/dt = -omega * [ alpha * sin(H) + beta * cos(phi) * cos(H) ]
```

At the meridian (`H = 0`) only azimuth contributes; at the eastern or western
horizon (`H = +-90 degrees`) only altitude contributes. The classic drift
procedure (AstroPixels, F. Espenak, "Polar Alignment Using Drift Method") also
measures azimuth on the meridian and altitude at the eastern or western
horizon. ADR-007's sentence swapped the two windows. An accepted ADR is not
rewritten, so the correction lives in this ADR.

**Decision**:

1. **The corrected guidance is: azimuth near the meridian (`H ~ 0`), altitude
   near the eastern or western horizon (`|H| ~ 90 degrees`).** That is the
   window where the corresponding term dominates and the other vanishes;
   outside it the two errors mix and the fit cannot separate them.
2. **The signs are the ones of the derivation and of the published table.** An
   axis east of the pole makes the Sun drift south on the meridian; an axis too
   high makes it drift south at the western horizon and north at the eastern
   one. The `PolarResult` contract keeps its convention: azimuth positive east,
   altitude positive too high.
3. **ADR-007's decision does not change**: sampling, ephemeris subtraction,
   drift fit, user guidance and the second confirmation measurement remain the
   model. Only the recommended window and its explanation change.
4. **The code is the reference.** `solarscribe/shg/polar.py` implements the
   relation and its tests pin the signs and the rates (a 60" offset gives
   0.262"/min at the maximum, Canburytech). The UI must recommend the corrected
   windows and the documentation must not repeat the inverted sentence.
5. **The Sun's geometry limits the measurement.** By day the Sun travels from
   east to west; separating azimuth from altitude requires sampling in both
   windows, which spreads the measurement over tens of minutes. That was
   already a consequence of ADR-007 and still holds.

**Alternatives**:

- **Leave ADR-007 as it is and let the code contradict it**: the reader would
  follow the wrong guidance and measure each error in the window where it does
  not dominate. Dropped.
- **Rewrite ADR-007**: accepted ADRs are not rewritten; the process requires a
  new ADR that references them. Dropped.
- **Measure only one error at a time with a single window**: slower and it does
  not separate the two errors; the second confirmation measurement already
  covers validation. Dropped.
- **Correct the tilt from the RA drift**: RA drift is dominated by the clock
  error and by refraction; Dec is the clean signal. Dropped.

**Consequences**: the written guidance matches the physics and the published
procedure; the UI can tell the observer when to measure each knob; ADR-007's
model and contract remain valid unchanged. The cost is a documented erratum and
a corrected sentence in the user guide and in DESIGN.md §8.3. The actual
separation of the two errors is still limited by the Sun's hour angle, as
ADR-007 already warned.
