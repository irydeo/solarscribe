# Informe de gate QE / QE gate report: 2026-11-06

Nota interna de trabajo (no se publica). Custodia: agente QE, ADR-005 y ADR-015.
No sustituye a los ADRs; los números y las decisiones viven allí.

Estado de este cambio: **G1 verde, G2 verde con simulador y fixtures, G3 PASS
provisional con margen estrecho**. No se ha hecho commit.

> Pasada final sobre el árbol integrado: ver
> [`QE-FINAL-GATE-2026-11-06.md`](QE-FINAL-GATE-2026-11-06.md).

---

## Español

### 1. Qué se ha probado y con qué

**Contratos (unit, sin hardware).** `tests/unit/test_layers.py` sigue siendo la
puerta estricta de `design/ARCHITECTURE.md` §1 y §2. Fija, sin depender de una
implementación:

- La superficie de los Protocol: métodos de `Frame`, `Camera`, `Mount`,
  `DeviceManager`, `SerWriter`, `CaptureEngine`, `FrameSource`, `RowRecorder`,
  `ScanEngine`, `TiltMeter`, `SunCenteringService` y
  `PolarAlignmentAssistant`, y los nombres de sus parámetros.
- Los tipos de valor: dataclass congelados (ADR-023), con la excepción
  deliberada de `RoiModel`, `StepState` y `SessionState`; todos sus
  `get_type_hints` resuelven.
- Las unidades y coordenadas: `ROI = (x, y, width, height)`, `capture` en
  píxeles de sensor y `band` en píxeles de frame, `output() == capture`, y los
  nombres de campo que llevan su unidad (`_us`, `_s`, `_arcsec`, `_deg`,
  `_hours`). Los valores por defecto del INI y de `RoiPreset` coinciden con los
  dos rectángulos del modelo, sin aritmética que pueda mezclar espacios.
- Las enumeraciones persistidas: conjunto cerrado y ortografía `snake_case`
  estable de `Param`, `Axis`, `DeviceKind`, `BackendReason`, `RoiIssue`,
  `Severity`, `ScanMode`, `DecCenterMethod`, `PreparePhase`, `ScanState`,
  `ScanStatus` y `StepStatus`; los IDs SER estándar (`SerColorId`).
- Los códigos de motivo: `reason_code` vacío cuando todo va bien, `DeviceError`
  con `code`/`device_id`, y ningún campo de frase en `RoiWarning`.
- Los valores por defecto que son contrato: `CaptureParams` (512 MB de cola,
  3 s de stall, 16 bits), `SerHeader`, contadores, `ScanConfig` (3 ciclos,
  `analysis` vacío y por instancia), `PrepareResult`, `ScanResult`,
  `TiltResult`, `CenteringStatus`, `CenteringResult`, `PolarSample`,
  `PolarProgress` y `PolarResult`.
- El esquema de configuración: nombres de fichero, `PROFILE_VERSION = 2`, orden
  de `SESSION_STEPS`, secciones del MVP, geometría de la rendija (7 mm a 714 mm
  son 33,7'), `keys_of`/`default_value`, y los números de ADR-013 sin deriva
  (120 fps, 512 MB, 1 GB libre, 3480x248).
- La regla de ADR-023: los módulos de contrato no contienen algoritmos. Un
  análisis con `ast` acepta solo cuerpos `...` y la lista blanca de accesores
  (`RoiModel.output`, `RoiModel.set_tilt`, `DeviceError.__init__`,
  `Profile.preset`, `new_steps`, `keys_of`, `default_value`).
- Las funciones que ARCHITECTURE 2.2 y 2.3 nombran y ya tienen implementación:
  `analysis_regions` (claves reservadas `left`/`right`/`limb`, regiones en
  píxeles de frame y mitades que cubren la banda), `validate_roi` (códigos
  `RoiIssue` con su `Severity`: ERROR bloquea, WARNING recomienda),
  `preset_to_model`/`model_to_preset` (ida y vuelta sin aritmética) y
  `ScanEngineImpl(mount, frames)`.

**Simuladores (funcional).** `tests/functional/test_simulators.py` prueba la
frontera de `devices` contra `SimCamera` y `SimMount` reales, con descubrimiento
en `tests/support.py`: `isinstance` contra los Protocol, ROI y tamaño de frame,
`data` C-contiguo, `stats().mean/std` contra numpy, secuencias crecientes,
timestamps no decrecientes, la copia de `cut_roi` (tira a ancho completo y
sub-rectángulo) y la integración de tasas de la montura. El agente `video`
añadió además `tests/functional/test_capture_sim.py`, que también pasa.

**Fixtures reales (funcional).** `tests/fixtures/catalogue.py` cataloga cinco
capturas externas; `tests/functional/test_fixtures.py` valida el catálogo sin
datos (ids únicos, rutas relativas que no escapan) y, cuando
`SOLARSCRIBE_FIXTURES` está puesto, valida los ficheros: la cabecera SER de 178
bytes, el tamaño de payload contra `FrameCount`, el JSON de `session_meta`, y la
firma del bug de calibración en el `scan_log.csv` real (`actual_xy > 3`,
`calibration_factor < 0.5`, `fps_used > 100`).

**Rendimiento (perf).** `tests/perf/` mide ADR-013 en modo caja negra, solo con
los contratos de `devices` y `capture`: constantes y lógica pass/FAIL/
unverified; el arnés (fps, caudal, pérdidas SDK/cola/huecos, edad del frame,
arranque, RSS, CPU, cola máxima, ritmo del escritor y capacidad de disco); la
puerta G3 en la franja de referencia; el suelo del simulador; una autoprueba del
arnés con un motor de prueba a 640x64; y `bench_capture.py`, el mismo banco sin
pytest. El banco está opt-in (`SOLARSCRIBE_PERF=1`) para no ralentizar la suite
normal; su ventana por defecto son 5 s.

### 2. Resultados

```
.venv/bin/python -m pytest tests/unit/test_layers.py tests/perf tests/functional -q
78 passed, 20 skipped       # todo lo que custodia QE

.venv/bin/python -m pytest tests -q
460 passed, 20 skipped      # instantánea verde al cerrar la nota

SOLARSCRIBE_FIXTURES=/tmp/opencode/solarscribe-fixtures \
.venv/bin/python -m pytest tests/functional -q
18 passed, 3 skipped        # scan_log.csv y session.cfg reales + un SER válido

SOLARSCRIBE_PERF=1 .venv/bin/python -m pytest tests/perf -q
22 passed                   # la puerta G3 completa, con sus números
```

El fixture externo de prueba se montó en `/tmp/opencode/solarscribe-fixtures`
con el `scan_log.csv` y el `session.cfg` reales del prototipo, un
`session_meta.json` mínimo y un SER sintético con cabecera válida de 3480x248,
16 bits y un frame. El `real-scan-ser` no estaba y se saltó con su descripción,
que es el comportamiento buscado. Durante la pasada, los tests de otras ramas
(`config_store`, `shg`, `ui`) estuvieron rojos mientras aterrizaban sus módulos:
se vieron fallos en `test_config_store.py`, `test_shg_engine.py` y
`test_ui_*`, y desaparecieron al completarse cada módulo. La red de QE estuvo
verde en todo momento; la última ejecución completa observada terminó en 460
passed, 20 skipped. Como los demás agentes siguen trabajando, ese número es una
instantánea, no una promesa.

### 3. Presupuesto ADR-013 (motor de captura real)

Comando: `.venv/bin/python -m tests.perf.bench_capture --seconds 10`.
Rig: `SimCamera(3480x248, 16 bits, 120 fps)` + `CaptureEngineImpl` + escritor
SER real sobre `/tmp`.

| Métrica | Presupuesto | Medido | Veredicto |
| --- | --- | --- | --- |
| FPS sostenidos | >= 120 | 120,149 | pass |
| Caudal | ~207 MB/s | 207,386 MB/s | pass |
| Frames perdidos | <= 0,1 % | 0,000 % | pass |
| Huecos de secuencia | 0 | 0 | pass |
| Latencia del visor (p95) | <= 150 ms | 2,846 ms | pass |
| Arranque de captura | <= 5 s | 0,018 s | pass |
| Cola de grabación | <= 512 MB | 1,726 MB | pass |
| Escritor frente al stream | >= caudal | 207,105 >= 203,239 MB/s | pass |
| Disco sostenido | >= 250 MB/s | 1 487,507 MB/s | pass |

Traza: 1215 frames en 10,112 s; p50/max de latencia 2,29/5,00 ms; RSS
35,0 / 51,1 / 51,1 MB (arranque, pico, final); CPU del proceso 36,2 % de un
núcleo, que **incluye el hilo del simulador** y no es overhead aislado del
pipeline.

**Margen.** El presupuesto se cumple, pero por poco: tres repeticiones de 5 s
dieron 120,36 fps y 207,75 MB/s, y tres de 10 s dieron 120,15 a 120,19 fps y
207,39 a 207,45 MB/s. Una ejecución de 10 s con la máquina cargada por otros
agentes midió 119,77 fps y 206,74 MB/s (0,19 % por debajo) y el simulador solo,
en una ventana de 2 s, 119,44 fps. El margen es del orden del 0,1 al 0,3 %:
cualquier regresión de dos décimas bloquea. El simulador es Python y comparte el
GIL con el pipeline, así que la cifra definitiva de la fase 0 debe tomarse con
hardware; este PASS es el provisional de ADR-013.

**Autoprueba del arnés (640x64, motor de prueba, 1 s).** 120,5 fps, latencia p95
0,08 ms, arranque 0,009 s, capacidad de disco 1 561 MB/s. La ruta de grabación
salió `unverified` con su nota, que es lo que debe hacer cuando no hay escritor.

### 4. Bloqueos y lo que no se ha podido verificar

- **G3 PASS provisional**: todos los números de ADR-013 se cumplen, con el
  margen estrecho de §3. No hay bloqueo de rendimiento en esta pasada, pero la
  cifra no es definitiva hasta la fase 0 con hardware.
- **Sin verificar**: métricas SHG sobre un barrido real del usuario (no hay SER
  real en la ruta externa de esta máquina), CPU de overhead aislada del
  pipeline, salto del buzón Qt dentro de la latencia del visor, hardware real y
  Windows.
- **Fixtures reales**: el `scan_log.csv` del prototipo sí se validó; los SER del
  usuario no están, así que las métricas del motor SHG siguen sin anclaje real
  en esta pasada.
- **Fallo ajeno**: durante la pasada se vieron rojos en `test_config_store.py`,
  `test_shg_engine.py` y `test_ui_*` mientras sus agentes escribían; al cerrar
  la última ejecución completa observada estaba verde. No son de QE.

---

## English

### 1. What was tested and with what

**Contracts (unit, no hardware).** `tests/unit/test_layers.py` remains the
strict gate of `design/ARCHITECTURE.md` sections 1 and 2. It pins, without
depending on an implementation:

- The Protocol surface: methods of `Frame`, `Camera`, `Mount`, `DeviceManager`,
  `SerWriter`, `CaptureEngine`, `FrameSource`, `RowRecorder`, `ScanEngine`,
  `TiltMeter`, `SunCenteringService` and `PolarAlignmentAssistant`, plus their
  parameter names.
- Value types: frozen dataclasses (ADR-023), except the deliberate `RoiModel`,
  `StepState` and `SessionState`; every `get_type_hints` resolves.
- Units and coordinates: `ROI = (x, y, width, height)`, `capture` in sensor
  pixels and `band` in frame pixels, `output() == capture`, and unit-bearing
  field names (`_us`, `_s`, `_arcsec`, `_deg`, `_hours`). INI and `RoiPreset`
  defaults match the model's two rectangles with no arithmetic that could mix
  spaces.
- Persisted enums: closed set and stable `snake_case` spelling for `Param`,
  `Axis`, `DeviceKind`, `BackendReason`, `RoiIssue`, `Severity`, `ScanMode`,
  `DecCenterMethod`, `PreparePhase`, `ScanState`, `ScanStatus` and
  `StepStatus`; the standard SER colour IDs.
- Reason codes: `reason_code` empty on success, `DeviceError` with
  `code`/`device_id`, and no sentence field in `RoiWarning`.
- Defaults that are contract: `CaptureParams` (512 MB queue, 3 s stall,
  16 bit), `SerHeader`, counters, `ScanConfig` (3 cycles, per-instance empty
  `analysis`), `PrepareResult`, `ScanResult`, `TiltResult`, `CenteringStatus`,
  `CenteringResult`, `PolarSample`, `PolarProgress` and `PolarResult`.
- The config schema: file names, `PROFILE_VERSION = 2`, `SESSION_STEPS` order,
  MVP sections, slit geometry (7 mm at 714 mm is 33.7'), `keys_of` /
  `default_value`, and the ADR-013 numbers with no drift (120 fps, 512 MB, 1 GB
  free, 3480x248).
- The ADR-023 rule: contract modules hold no algorithm. An `ast` pass accepts
  only `...` bodies and the accessor allowlist.
- The functions ARCHITECTURE 2.2 and 2.3 name that now have an implementation:
  `analysis_regions` (reserved `left`/`right`/`limb` keys, regions in frame
  pixels and halves that cover the band), `validate_roi` (`RoiIssue` codes with
  their `Severity`: ERROR blocks, WARNING recommends),
  `preset_to_model`/`model_to_preset` (round trip with no arithmetic) and
  `ScanEngineImpl(mount, frames)`.

**Simulators (functional).** `tests/functional/test_simulators.py` tests the
`devices` boundary against the real `SimCamera` and `SimMount`, discovered in
`tests/support.py`: runtime Protocol `isinstance`, ROI and frame size,
C-contiguous `data`, `stats().mean/std` against numpy, increasing sequences,
non-decreasing timestamps, the `cut_roi` copy (full-width strip and narrow
sub-rectangle) and the mount rate integration. The `video` agent also added
`tests/functional/test_capture_sim.py`, which passes.

**Real fixtures (functional).** `tests/fixtures/catalogue.py` catalogues five
external captures; `tests/functional/test_fixtures.py` validates the catalogue
with no data (unique ids, relative paths that cannot escape) and, when
`SOLARSCRIBE_FIXTURES` is set, the files: the 178-byte SER header, payload size
against `FrameCount`, `session_meta` JSON, and the calibration-bug signature in
the real `scan_log.csv` (`actual_xy > 3`, `calibration_factor < 0.5`,
`fps_used > 100`).

**Performance (perf).** `tests/perf/` measures ADR-013 black box, using only the
`devices` and `capture` contracts: budget constants and pass/FAIL/unverified
logic; the harness (fps, throughput, SDK/queue/sequence drops, frame age, start,
RSS, CPU, queue high-water, writer rate and raw disk capability); the G3 gate on
the reference strip; the simulator-only floor; a harness self-test with a
contract-only engine at 640x64; and `bench_capture.py`, the same bench without
pytest. The bench is opt-in (`SOLARSCRIBE_PERF=1`) so the normal suite stays
fast; its default window is 5 s.

### 2. Results

```
.venv/bin/python -m pytest tests/unit/test_layers.py tests/perf tests/functional -q
78 passed, 20 skipped       # everything QE custodies

.venv/bin/python -m pytest tests -q
460 passed, 20 skipped      # green snapshot as this note closes

SOLARSCRIBE_FIXTURES=/tmp/opencode/solarscribe-fixtures \
.venv/bin/python -m pytest tests/functional -q
18 passed, 3 skipped        # real scan_log.csv and session.cfg plus one valid SER

SOLARSCRIBE_PERF=1 .venv/bin/python -m pytest tests/perf -q
22 passed                   # the whole G3 gate, with its numbers
```

The external fixture directory used for the check held the prototype's real
`scan_log.csv` and `session.cfg`, a minimal `session_meta.json` and a synthetic
SER with a valid 3480x248, 16-bit, one-frame header. `real-scan-ser` was absent
and skipped with its description, which is the intended behaviour. During the
pass, other branches' tests (`config_store`, `shg`, `ui`) went red and green as
their modules landed: failures were seen in `test_config_store.py`,
`test_shg_engine.py` and `test_ui_*`, and disappeared as each module completed.
The QE net stayed green throughout; the last full run observed ended at 460
passed, 20 skipped. The other agents are still working, so that count is a
snapshot, not a promise.

### 3. ADR-013 budget (real capture engine)

Command: `.venv/bin/python -m tests.perf.bench_capture --seconds 10`.
Rig: `SimCamera(3480x248, 16 bit, 120 fps)` + `CaptureEngineImpl` + the real SER
writer on `/tmp`.

| Metric | Budget | Measured | Verdict |
| --- | --- | --- | --- |
| Sustained fps | >= 120 | 120.149 | pass |
| Throughput | ~207 MB/s | 207.386 MB/s | pass |
| Dropped frames | <= 0.1 % | 0.000 % | pass |
| Sequence gaps | 0 | 0 | pass |
| Viewer latency (p95) | <= 150 ms | 2.846 ms | pass |
| Capture start | <= 5 s | 0.018 s | pass |
| Recording queue | <= 512 MB | 1.726 MB | pass |
| Writer vs stream | >= stream | 207.105 >= 203.239 MB/s | pass |
| Sustained disk | >= 250 MB/s | 1,487.507 MB/s | pass |

Trail: 1215 frames over 10.112 s; latency p50/max 2.29/5.00 ms; RSS
35.0 / 51.1 / 51.1 MB (start, peak, end); process CPU 36.2 % of one core, which
**includes the simulator thread** and is not isolated pipeline overhead.

**Margin.** The budget is met, but narrowly: three 5 s repeats gave 120.36 fps
and 207.75 MB/s, and three 10 s repeats gave 120.15 to 120.19 fps and 207.39 to
207.45 MB/s. One 10 s run with the machine loaded by other agents measured
119.77 fps and 206.74 MB/s (0.19 % short), and the simulator alone over a 2 s
window measured 119.44 fps. The margin is on the order of 0.1 to 0.3 %: a
regression of two tenths blocks. The simulator is Python and shares the GIL
with the pipeline, so the definitive phase 0 figure must come from hardware;
this PASS is ADR-013's provisional one.

**Harness self-test (640x64, contract-only engine, 1 s).** 120.5 fps, p95
latency 0.08 ms, start 0.009 s, disk capability 1,561 MB/s. The recording path
came out `unverified` with its note, which is what it must do with no SER
writer.

### 4. Blockers and unverified items

- **G3 PASS provisional**: every ADR-013 number holds, with the narrow margin of
  section 3. There is no performance block in this pass, but the figure is not
  final until phase 0 on hardware.
- **Unverified**: SHG metrics on a real user sweep (no real SER in the external
  path on this machine), isolated pipeline CPU overhead, the Qt mailbox hop
  inside viewer latency, real hardware and Windows.
- **Real fixtures**: the prototype `scan_log.csv` was validated; the user's SER
  files are absent, so the SHG engine metrics still have no real anchor in this
  pass.
- **Foreign failure**: during the pass, reds were seen in `test_config_store.py`,
  `test_shg_engine.py` and `test_ui_*` while their agents were writing; at the
  close, the last full run observed was green. They are not QE's.

---

## Archivos de esta pasada / Files in this pass

- `tests/conftest.py` (markers, fixtures path)
- `tests/unit/test_layers.py` (contract tests)
- `tests/support.py` (device/engine discovery)
- `tests/fixtures/catalogue.py`, `tests/fixtures/README.md`,
  `tests/fixtures/__init__.py`
- `tests/functional/conftest.py`, `tests/functional/test_fixtures.py`,
  `tests/functional/test_simulators.py`
- `tests/perf/budget.py`, `tests/perf/harness.py`, `tests/perf/conftest.py`,
  `tests/perf/test_budget.py`, `tests/perf/test_capture_bench.py`,
  `tests/perf/test_simulator_baseline.py`, `tests/perf/test_harness_selftest.py`,
  `tests/perf/bench_capture.py`
- `design/notes/QE-GATE-REPORT-2026-11-06.md` (this note)
