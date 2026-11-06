# ADR-028: Raíl de cinco pasos con Focus / Five-step rail with Focus

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-011 (flujo de sesión por pasos), ADR-006 (centrado), ADR-010
(ROI), ADR-022 (tilt), ADR-023 (estado de sesión), ADR-026 (interfaz imagen
primero).

## Español

**Contexto**: ADR-011 fijó un flujo de **cuatro pasos**: buscar el Sol, alineación
polar, ROI y escaneado. Durante la construcción, el enfoque del SHG (los tres
focusers y la alineación de la rendija con Dec) creció hasta necesitar métricas en
vivo propias, una tarjeta con tres grupos y una acción principal distinta de la
del ROI. Meterlo dentro del paso ROI escondía la mitad de los controles y mezclaba
dos tareas: ajustar el espectrógrafo y elegir la tira que se va a capturar. El
agente `ux` separó el paso y `SESSION_STEPS` pasó a cinco.

**Decisión**: el raíl tiene **cinco pasos**, en este orden y con estas claves
estables en `SESSION_STEPS`:

1. `find_sun`: GOTO al Sol por efeméride y centrado grueso.
2. `polar`: asistente de alineación polar solar.
3. `focus`: los tres focusers y la alineación rendija-Dec, con las métricas de
   `shg.focus` y el tilt de `shg.tilt` en vivo. El paso ROI conserva una medición
   rápida del tilt porque la altura de la tira la necesita.
4. `roi`: selección del ROI de captura y validación de la tira.
5. `scan`: preparación (centrado fino y autocalibración) y barrido.

Reglas:

- Los nombres son **claves estables** del `session_state.json`; añadir un paso es
  añadir una clave al final del orden, no renombrar las existentes.
- `load_session_state()` parte de `new_steps()`: un fichero guardado con cuatro
  pasos carga con `focus` en `PENDING` y los otros cuatro intactos.
- `save_session_state()` escribe los cinco en orden y descarta cualquier paso que
  no esté en `SESSION_STEPS`.
- La UI pinta el raíl recorriendo `SESSION_STEPS`, no una lista propia.
- `StepState.metrics` sigue siendo solo números; las frases las compone la UI con
  `self.tr()` (ADR-016, ADR-023).

**Migración**: los `session_state.json` anteriores cargan sin pérdida: el paso que
falta se añade pendiente. No hay migración de código porque la UI ya recorría la
tupla; ADR-011 queda como la decisión histórica del flujo de cuatro pasos y este
ADR concreta el quinto. El resto de sus principios (navegación libre,
recomendaciones, autoguardado silencioso y reabrir paso) siguen en vigor.

**Alternativas**:

- **Mantener Focus dentro de ROI**: oculta los controles y mezcla dos tareas. Se
  descarta.
- **Un diálogo aparte de enfoque**: rompe el flujo por pasos y el visor en vivo
  compartido. Se descarta.
- **Renombrar los pasos existentes al añadir Focus**: rompe los ficheros de sesión
  ya guardados sin ganar nada. Se descarta.
- **No migrar los ficheros antiguos**: perderían el estado de la sesión. Se
  descarta.

**Consecuencias**: la sesión enseña el enfoque como una tarea propia, con su
tarjeta y sus métricas, sin perder el estado de las sesiones anteriores. El coste
es un paso más en el raíl y una tupla que mantener; añadir otro paso exige un ADR
nuevo que referencie este, porque el orden es contrato de los ficheros guardados.

## English

**Context**: ADR-011 fixed a **four-step** flow: find the Sun, polar alignment,
ROI and scanning. During the build, SHG focusing (the three focusers and the
slit-to-Dec alignment) grew until it needed its own live metrics, a card with
three groups and a primary action different from the ROI step's. Keeping it
inside ROI hid half the controls and mixed two tasks: adjusting the spectrograph
and choosing the strip to capture. The `ux` agent split the step and
`SESSION_STEPS` became five.

**Decision**: the rail has **five steps**, in this order and with these stable
keys in `SESSION_STEPS`:

1. `find_sun`: GOTO to the Sun by ephemeris and coarse centring.
2. `polar`: solar polar alignment assistant.
3. `focus`: the three focusers and the slit-to-Dec alignment, with the live
   `shg.focus` metrics and the `shg.tilt` measurement. The ROI step keeps a quick
   tilt measurement because the strip height needs it.
4. `roi`: capture ROI selection and strip validation.
5. `scan`: preparation (fine centring and autocalibration) and scanning.

Rules:

- The names are **stable keys** of `session_state.json`; adding a step means
  adding a key at the end of the order, not renaming the existing ones.
- `load_session_state()` starts from `new_steps()`: a file saved with four steps
  loads with `focus` `PENDING` and the other four intact.
- `save_session_state()` writes the five in order and drops any step that is not
  in `SESSION_STEPS`.
- The UI paints the rail by iterating `SESSION_STEPS`, not a list of its own.
- `StepState.metrics` stays numeric only; the UI builds the sentences with
  `self.tr()` (ADR-016, ADR-023).

**Migration**: previous `session_state.json` files load without loss: the missing
step is added pending. There is no code migration because the UI already iterated
the tuple; ADR-011 remains the historical decision for the four-step flow and this
ADR makes the fifth concrete. The rest of its principles (free navigation,
recommendations, silent auto-save and "reopen step") stay in force.

**Alternatives**:

- **Keep Focus inside ROI**: it hides controls and mixes two tasks. Dropped.
- **A separate focus dialog**: it breaks the step flow and the shared live
  viewer. Dropped.
- **Rename the existing steps when adding Focus**: it breaks already saved session
  files with nothing gained. Dropped.
- **Do not migrate old files**: they would lose the session state. Dropped.

**Consequences**: the session shows focusing as its own task, with its card and
metrics, without losing the state of previous sessions. The cost is one more step
in the rail and one tuple to maintain; adding another step requires a new ADR
referencing this one, because the order is a contract of the saved files.
