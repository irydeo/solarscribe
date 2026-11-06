# ADR-023: Módulos de contrato y hogar del modelo de ROI / Contract modules and the home of the ROI model

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-012 (contratos entre capas), ADR-003 (config y perfiles),
ADR-010 (ROI), ADR-011 (sesión), ADR-018 (post-proceso), ADR-022 (tilt).

## Español

**Contexto**: ADR-012 fijó los contratos en `design/ARCHITECTURE.md` como
**bocetos**. Al empezar la implementación, siete agentes necesitan las firmas de
verdad, y el boceto deja cuatro cosas sin decidir:

1. Dónde vive el `RoiModel`, que consume `capture`, edita `ui`, persiste `config`
   y mide `shg`.
2. Dónde vive el estado de la sesión, que ADR-012 situaba en la capa `ui`.
3. Cómo llega `shg` a los frames vivos y a la grabación sin importar `capture`,
   siendo los dos motores hermanos.
4. Qué es un módulo de contrato: ¿tipos con su comportamiento dentro, o solo
   declaraciones?

Sin estas cuatro respuestas cada agente inventa su mitad y la integración se
rompe justo donde ADR-012 quería evitarlo.

**Decisión**:

1. **Los contratos se escriben en código**: `solarscribe/devices/abc.py`,
   `solarscribe/capture/abc.py`, `solarscribe/shg/abc.py` y
   `solarscribe/config/schema.py`. Ese código es la firma autoritativa;
   `design/ARCHITECTURE.md` guarda el inventario y las razones.
2. **Regla de los módulos de contrato**: los tipos de valor (`dataclass`
   congelado, `Enum`) son **concretos**, porque cruzan la capa y todos deben
   coincidir en sus campos y unidades; el comportamiento (`typing.Protocol`) se
   declara **sin cuerpo** y se implementa en los módulos de la capa. Un módulo de
   contrato no contiene ningún algoritmo: `validate_roi()` vive en
   `capture/roi.py` y la lectura del INI en `config/store.py`.
3. **`config` entra en el grafo como hoja de soporte**: importa `devices` (solo el
   alias `ROI`) y nada más de la aplicación; `capture`, `shg`, `ui` y `cli` pueden
   importarla. `ui` y `cli` también pueden importar `devices`: importar hacia abajo
   siempre es seguro, lo prohibido es hacia arriba.
4. **Hogar del modelo de ROI**: `RoiModel`, `RoiWarning`, `RoiIssue` y `Severity`
   viven en `capture/abc.py`. `RoiConstraints` vive en `devices/abc.py`, porque los
   múltiplos, los mínimos y los máximos son hechos del sensor que el SDK declara y
   `CameraInfo` debe poder llevarlos sin que `devices` importe `capture`. Los
   presets (`RoiPreset`) viven en `config/schema.py`, que es persistencia pura. La
   validación es `capture/roi.py: validate_roi(model, *, fps=None)`. Las
   sub-regiones de análisis **no** se guardan: las calcula `shg` desde `capture` y
   `band`, y viajan en `ScanConfig.analysis` con las claves reservadas `"left"`,
   `"right"` y `"limb"`.
5. **El tilt**: la medición es ciencia de `shg` (`TiltMeter`, `TiltResult`,
   ADR-022). `RoiModel` **guarda** los números (`set_tilt(tilt_deg, tilt_px)`) y los
   usa para validar la altura. El paso ROI llama a `shg` y escribe en el modelo, así
   que la matemática y el modelo se quedan cada uno en su capa.
6. **Puertos de `shg`** (inversión de dependencias): `shg` declara `FrameSource`
   (los frames vivos) y `RowRecorder` (la grabación de cada fila del mosaico), con
   `RowCounters` como tipo de valor propio para la contabilidad, de modo que `shg`
   pueda escribir los tres registros de ADR-018 sin importar `capture`.
   `CaptureEngine` cumple `FrameSource` estructuralmente y la UI pasa un adaptador
   de unas líneas para `RowRecorder`. La construcción es
   `shg/engine.py: ScanEngineImpl(mount, frames)`.
7. **Estado de sesión en `config`**: `SessionState`, `StepStatus`, `StepState` y
   `SESSION_STEPS` viven en `config/schema.py`, y se guardan en
   `session_state.json` dentro de la carpeta de la sesión (que no es
   `session_meta.json`, el contrato de ADR-018). `StepState.metrics` guarda solo
   números: la frase la compone la UI con `self.tr()`.
8. **Miembros añadidos a los contratos**, cada uno con su razón en
   `design/ARCHITECTURE.md` §2: `Camera.param_range()`, `Camera.dropped_frames()`,
   `Mount.status()`, `CaptureEngine.on_frame()`, `CaptureEngine.counters()`,
   `CaptureEngine.is_running()`, `CaptureEngine.is_recording()`,
   `ScanEngine.pause()`, `ScanEngine.resume()` y el parámetro `recorder` de
   `ScanEngine.run()`. Sin ellos el panel de salud, el editor de ROI en vivo, la
   pausa cuando el Sol se sale de la rendija y el mosaico habrían quedado sin
   contrato.
9. **El test de capas** (`tests/unit/test_layers.py`) parsea las fuentes con `ast`
   en vez de importarlas, y comprueba algo más de lo que ADR-012 pedía: que
   `devices` y `config` no importan de la aplicación, que `capture` y `shg` no se
   importan entre sí ni importan `ui`/`cli`, que Qt solo entra en `ui`, que
   `ctypes`/`cffi` solo entra en `devices`, y que los cuatro módulos de contrato
   importan limpios sin perder nombres de su superficie.

**Migración**: no hay código escrito contra los bocetos v0, así que no hay nada que
migrar. Los bocetos de `design/ARCHITECTURE.md` v0 quedan **sustituidos** por el
código de los cuatro módulos, y el documento pasa a v1 con el inventario y las
razones. ADR-012 sigue en vigor: este ADR lo concreta, no lo deroga.

**Alternativas**:

- `RoiModel` en `devices`: contamina la única capa que no conoce la aplicación con
  conceptos del SHG (banda espectral, tilt). Se descarta.
- `RoiModel` en `shg`: obligaría a `capture` a importar a su hermano para
  `configure()`. Se descarta.
- `RoiModel` en `config`: mezclaría persistencia con validación y con geometría de
  medida, y obligaría a `config` a importar `devices` y numpy para la ciencia. Se
  descarta.
- Un único `solarscribe/contracts.py`: es la opción monolítica que ADR-012 ya
  descartó y aleja cada contrato de su dueño. Se descarta.
- `SessionState` en `ui`: la CLI no podría reabrir una sesión sin importar la GUI.
  Se descarta.
- Que `shg` importe `capture`: rompe la regla de hermanos y arrastra el escritor
  SER y la cola de grabación al motor científico. Se descarta.
- Dejar los contratos solo en prosa (ADR-012 sin código): cada agente escribiría su
  propia versión de las firmas. Se descarta.

**Consecuencias**: las firmas están en el código y las razones en el documento; los
siete agentes implementan contra la misma frontera sin adivinar. `capture` y `shg`
quedan desacoplados a cambio de dos puertos y un adaptador pequeño en la UI, que es
cableado y no lógica de negocio. `config` gana una segunda responsabilidad (el
estado de sesión) a cambio de ser legible desde cualquier capa. El test de capas es
más estricto de lo que ADR-012 pedía, así que una violación nueva falla en CI antes
de llegar a la integración. Cambiar una firma exige pasar por el `lead` y actualizar
`design/ARCHITECTURE.md`. Quedan tres contratos por formalizar, asignados a `shg` y
listados en §2.3 del documento: las regiones de análisis, el centrado del Sol del
paso *Buscar el Sol* y el asistente de alineación polar.

## English

**Context**: ADR-012 fixed the contracts in `design/ARCHITECTURE.md` as
**sketches**. When the implementation starts, seven agents need the real
signatures, and the sketch leaves four things undecided:

1. Where `RoiModel` lives, which `capture` consumes, `ui` edits, `config` persists
   and `shg` measures.
2. Where the session state lives, which ADR-012 placed in the `ui` layer.
3. How `shg` reaches the live frames and the recording without importing
   `capture`, the two engines being siblings.
4. What a contract module is: types with their behaviour inside, or declarations
   only.

Without those four answers each agent invents its own half and integration breaks
exactly where ADR-012 meant to prevent it.

**Decision**:

1. **The contracts are written in code**: `solarscribe/devices/abc.py`,
   `solarscribe/capture/abc.py`, `solarscribe/shg/abc.py` and
   `solarscribe/config/schema.py`. That code is the authoritative signature;
   `design/ARCHITECTURE.md` keeps the inventory and the reasons.
2. **Rule of the contract modules**: value types (frozen `dataclass`, `Enum`) are
   **concrete**, because they cross the layer and everybody must agree on their
   fields and units; behaviour (`typing.Protocol`) is declared **with no body** and
   implemented in the layer's own modules. A contract module holds no algorithm:
   `validate_roi()` lives in `capture/roi.py` and the INI parsing in
   `config/store.py`.
3. **`config` enters the graph as a support leaf**: it imports `devices` (only the
   `ROI` alias) and nothing else from the application; `capture`, `shg`, `ui` and
   `cli` may import it. `ui` and `cli` may also import `devices`: importing
   downwards is always safe, upwards is what is forbidden.
4. **Home of the ROI model**: `RoiModel`, `RoiWarning`, `RoiIssue` and `Severity`
   live in `capture/abc.py`. `RoiConstraints` lives in `devices/abc.py`, because the
   multiples, minimums and maximums are sensor facts the SDK states and `CameraInfo`
   must be able to carry them without `devices` importing `capture`. The presets
   (`RoiPreset`) live in `config/schema.py`, which is pure persistence. Validation
   is `capture/roi.py: validate_roi(model, *, fps=None)`. The analysis sub-regions
   are **not** stored: `shg` computes them from `capture` and `band`, and they
   travel in `ScanConfig.analysis` with the reserved keys `"left"`, `"right"` and
   `"limb"`.
5. **The tilt**: the measurement is shg's science (`TiltMeter`, `TiltResult`,
   ADR-022). `RoiModel` **stores** the numbers (`set_tilt(tilt_deg, tilt_px)`) and
   uses them to validate the height. The ROI step calls `shg` and writes into the
   model, so the maths and the model each stay in their layer.
6. **shg's ports** (dependency inversion): `shg` declares `FrameSource` (the live
   frames) and `RowRecorder` (the recording of each mosaic row), with `RowCounters`
   as its own value type for the accounting, so `shg` can write the three logs of
   ADR-018 without importing `capture`. `CaptureEngine` satisfies `FrameSource`
   structurally and the UI passes a few-lines adapter for `RowRecorder`.
   Construction is `shg/engine.py: ScanEngineImpl(mount, frames)`.
7. **Session state in `config`**: `SessionState`, `StepStatus`, `StepState` and
   `SESSION_STEPS` live in `config/schema.py` and are saved to `session_state.json`
   inside the session folder (which is not `session_meta.json`, ADR-018's contract).
   `StepState.metrics` holds numbers only: the UI builds the sentence with
   `self.tr()`.
8. **Members added to the contracts**, each with its reason in
   `design/ARCHITECTURE.md` §2: `Camera.param_range()`, `Camera.dropped_frames()`,
   `Mount.status()`, `CaptureEngine.on_frame()`, `CaptureEngine.counters()`,
   `CaptureEngine.is_running()`, `CaptureEngine.is_recording()`,
   `ScanEngine.pause()`, `ScanEngine.resume()` and the `recorder` parameter of
   `ScanEngine.run()`. Without them the health panel, the live ROI editor, the pause
   when the Sun leaves the slit and the mosaic would have stayed without a contract.
9. **The layer test** (`tests/unit/test_layers.py`) parses the sources with `ast`
   instead of importing them, and checks more than ADR-012 asked: that `devices` and
   `config` import nothing from the application, that `capture` and `shg` import
   neither each other nor `ui`/`cli`, that Qt only enters `ui`, that
   `ctypes`/`cffi` only enters `devices`, and that the four contract modules import
   cleanly without losing names from their surface.

**Migration**: no code was written against the v0 sketches, so there is nothing to
migrate. The sketches of `design/ARCHITECTURE.md` v0 are **superseded** by the code
of the four modules, and the document becomes v1 with the inventory and the reasons.
ADR-012 stays in force: this ADR makes it concrete, it does not repeal it.

**Alternatives**:

- `RoiModel` in `devices`: it pollutes the only layer that knows nothing about the
  application with SHG concepts (spectral band, tilt). Dropped.
- `RoiModel` in `shg`: it would force `capture` to import its sibling for
  `configure()`. Dropped.
- `RoiModel` in `config`: it would mix persistence with validation and with
  measurement geometry, and force `config` to import `devices` and numpy for the
  science. Dropped.
- A single `solarscribe/contracts.py`: the monolithic option ADR-012 already
  dropped, and it moves every contract away from its owner. Dropped.
- `SessionState` in `ui`: the CLI could not reopen a session without importing the
  GUI. Dropped.
- `shg` importing `capture`: it breaks the sibling rule and drags the SER writer and
  the recording queue into the science engine. Dropped.
- Keeping the contracts in prose only (ADR-012 without code): each agent would write
  its own version of the signatures. Dropped.

**Consequences**: the signatures are in the code and the reasons in the document;
the seven agents implement against the same boundary without guessing. `capture` and
`shg` stay decoupled at the cost of two ports and a small adapter in the UI, which is
wiring and not business logic. `config` gains a second responsibility (the session
state) in exchange for being readable from every layer. The layer test is stricter
than ADR-012 asked, so a new violation fails in CI before reaching integration.
Changing a signature requires going through `lead` and updating
`design/ARCHITECTURE.md`. Three contracts remain to be formalised, assigned to `shg`
and listed in §2.3 of the document: the analysis regions, the Sun centring of the
*Find the Sun* step and the polar alignment assistant.
