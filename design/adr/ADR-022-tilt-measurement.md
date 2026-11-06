# ADR-022: Medición de tilt del espectro/rendija / Spectral/slit tilt measurement

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-010 (ROI), ADR-006 (centrado), ADR-018 (post-proceso),
ADR-019 (montura).

## Español

**Contexto**: la rendija y la línea espectral deberían ser **perpendiculares** al
eje de barrido. Si no lo son, hay un **tilt**: la reconstrucción sale **sesgada** y
el **ROI debe ser más alto** para que la banda inclinada quepa (altura =
`banda + ancho·tan(tilt) + márgenes`). El prototipo ya medía la **rectitud del
borde** de la rendija (`edge_flat`, la desviación de su posición), pero sin
formalizarlo ni usarlo.

**Decisión**: el **tilt del espectro/rendija** es una medición de primera clase,
dentro del paso *ROI*:

1. **Medir**: se ajusta una **recta** a la posición del borde de la rendija (o de
   una línea de absorción) a lo largo del ancho del ROI; la **pendiente** es el
   tilt, expresado en **grados** y en **píxeles de deriva** a lo ancho del ROI.
2. **Usar**: (a) **validar la altura del ROI** con la deriva por tilt; (b) **guiar
   al usuario** a dejarlo recto (idealmente ~0°); (c) **registrarlo** en
   `session_meta.json` (con la orientación de cámara) para que el post-proceso lo
   corrija.
3. **Recalcular** si cambia la óptica, el ROI o la orientación de cámara.
4. **Alcance**: solo el tilt del espectro/rendija. El tilt **óptico del sensor**
   (desenfoque en el campo) queda como indicador secundario de la ayuda de
   enfoque.

**Alternativas**: no medirlo (reconstrucción sesgada y ROI mal dimensionado);
corregirlo automáticamente en la captura (deskew, se descarta: el post-proceso lo
corrige mejor y no conviene tocar los datos crudos). Se mide, se guía y se
registra.

**Consecuencias**: el ROI se dimensiona con el tilt real; el observador puede
dejarlo recto; el post-proceso recibe el dato para corregir. El tilt se convierte
en un indicador más del paso *ROI*, en lenguaje llano.

## English

**Context**: the slit and the spectral line should be **perpendicular** to the scan
axis. If they are not, there is **tilt**: the reconstruction comes out **skewed**
and the **ROI must be taller** so the tilted band fits (height =
`band + width·tan(tilt) + margins`). The prototype already measured the slit
edge's **straightness** (`edge_flat`, the spread of its position), but without
formalising it or using it.

**Decision**: the **spectral/slit tilt** is a first-class measurement, inside the
*ROI* step:

1. **Measure**: a **line** is fitted to the slit edge's position (or an absorption
   line's) across the ROI width; the **slope** is the tilt, expressed in **degrees**
   and in **drift pixels** across the ROI.
2. **Use**: (a) **validate the ROI height** with the tilt drift; (b) **guide the
   user** to make it straight (ideally ~0°); (c) **record it** in
   `session_meta.json` (with the camera orientation) so post-processing can correct
   it.
3. **Recalculate** if the optic, the ROI or the camera orientation changes.
4. **Scope**: only the spectral/slit tilt. The sensor's **optical tilt** (field
   defocus) remains a secondary focus-aid indicator.

**Alternatives**: not measure it (skewed reconstruction and badly sized ROI);
correct it automatically in capture (deskew, dropped: post-processing corrects it
better and the raw data should not be touched). It is measured, guided and
recorded.

**Consequences**: the ROI is sized with the real tilt; the observer can make it
straight; post-processing receives the figure to correct. The tilt becomes one more
indicator of the *ROI* step, in plain language.
