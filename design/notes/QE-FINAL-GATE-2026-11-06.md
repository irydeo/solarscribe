# Informe de gate QE final / Final QE gate report: 2026-11-06

Nota interna de trabajo (no se publica). Custodia: agente QE, ADR-005 y ADR-015.
Complementa a `QE-GATE-REPORT-2026-11-06.md` (contratos y banco) con la pasada
final sobre el árbol integrado.

Resultado: **GATE VERDE en captura, centrado, barrido, registros y rendimiento;
una salvedad de integración en el recon de la ventana**. No se ha hecho commit.

---

## Español

### 1. Comandos y resultados

```
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
511 passed, 20 skipped in 64.88s

SOLARSCRIBE_PERF=1 .venv/bin/python -m pytest tests/perf -q
22 passed in 8.52s

QT_QPA_PLATFORM=offscreen .venv/bin/python -m solarscribe gui --self-test
exit 0
```

Los 20 saltos son: 11 fixtures reales que no están en esta máquina
(`SOLARSCRIBE_FIXTURES` sin definir), 8 pruebas del banco opt-in (sin
`SOLARSCRIBE_PERF=1`) y el banco opcional de ROI de referencia. No hay pruebas
marcadas `hardware` en la suite; el hardware sigue sin verificar. El self-test
de la GUI construye la ventana con los motores reales, arranca la captura y sale
con 0; los mensajes `propagateSizeHints()` son ruido normal de la plataforma
`offscreen`.

### 2. Presupuesto ADR-013 (motor real, 10 s)

`.venv/bin/python -m tests.perf.bench_capture --seconds 10`

| Métrica | Presupuesto | Medido | Veredicto |
| --- | --- | --- | --- |
| FPS sostenidos | >= 120 | 120,177 | pass |
| Caudal | ~207 MB/s | 207,435 MB/s | pass |
| Frames perdidos | <= 0,1 % | 0,000 % | pass |
| Huecos de secuencia | 0 | 0 | pass |
| Latencia del visor (p95) | <= 150 ms | 2,636 ms | pass |
| Arranque de captura | <= 5 s | 0,017 s | pass |
| Cola de grabación | <= 512 MB | 1,726 MB | pass |
| Escritor frente al stream | >= caudal | 207,156 >= 203,287 MB/s | pass |
| Disco sostenido | >= 250 MB/s | 1 505,648 MB/s | pass |

1215 frames en 10,110 s; latencia p50/max 2,24/4,75 ms; RSS 36,9 / 53,0 /
53,0 MB; CPU del proceso 35,0 % de un núcleo (incluye el hilo del simulador, no
es overhead aislado). El margen sigue siendo estrecho (del orden del 0,1 al
0,3 %): una regresión de dos décimas bloquea, y la cifra definitiva es la de la
fase 0 con hardware.

### 3. Verificación de la integración en las fronteras

Añadida `tests/functional/test_integration_sim.py`, que recorre el camino que
monta la ventana, sin Qt y solo con los contratos públicos:

1. **descubrimiento**: `DeviceManagerImpl` con un backend `SimCameraBackend`
   disponible; cámaras y monturas aparecen como `sim`;
2. **open**: `open_camera`/`open_mount` devuelven los dispositivos sin abrir, y
   el test llama a `open()`/`connect()`;
3. **configure**: `CaptureEngineImpl.configure` con el `RoiModel` real
   (3480x248, banda 0,40,3480,160) y `CaptureParams`;
4. **centrado**: `SunCenteringImpl` (simetría) lleva un disco 20" fuera de la
   rendija a menos de 1,5" (residuo medido 0,4"), y la montura queda en Dec
   dentro de 1,5";
5. **barrido**: `ScanEngineImpl.plan` + `run` sobre `SimCamera(pattern="solar")`
   enganchada a la montura; el barrido termina `COMPLETED`, una fila, con
   frames escritos y sin código de motivo;
6. **recon**: `shg.recon.quick_recon` sobre los frames reales capturados
   durante el barrido; imagen no vacía, 80 frames usados y contraste 1,0.

El test tarda unos 4 s y va marcado `slow`. Usa `SimCamera(pattern="solar")`,
la misma fixture física que `test_capture_sim.py`, y no toca internos.

**Salvedad de integración (recon de la ventana).** El camino del motor está
verificado, pero la ventana todavía no llama a `shg.recon.quick_recon`:
`ui/engines.py::EngineHarness._emit_recon` emite una franja de banda
submuestreada y `QuickRecon` la pinta. `shg/recon.py` existe, está probado en
`tests/unit/test_shg_recon.py` y se ejercita en el test anterior, pero no está
cableado en `ui/`. Si la aceptación exige que el recon real se vea en la
ventana, este es el único punto abierto; se reporta, no se corrige en QE.

**Observación menor.** El arnés de la ventana usa `SolarScene` sobre
`SimCamera(pattern="flat")`; la fixture física de las pruebas y del banco es
`SimCamera(pattern="solar")`. Los dos son simuladores acoplados a la montura,
pero no son el mismo objeto. No es un fallo funcional; conviene unificarlo
cuando `ux` y `video` cierren el simulador.

### 4. Paridad con nightscribe-scan

Las 22 filas de `design/notes/NIGHTSCRIBE-SCAN-PARITY.md` §1 tienen módulo y al
menos una prueba. Tabla de comprobación:

| # | Módulo | Prueba que lo cubre |
| --- | --- | --- |
| 1 | `shg/calibration.py` | `test_shg_calibration.py::test_factor_normalises_by_the_measurement_speed` |
| 2 | `shg/ephemeris.py` | `test_shg_ephemeris.py::test_solar_position_matches_jpl_horizons` |
| 3 | `shg/geometry.py` | `test_shg_geometry.py::test_slit_image_scale_is_the_ratio_of_the_two_axes` |
| 4 | `capture/engine.py`, `shg/engine.py` | `test_capture_engine.py::test_watchdog_aborts_a_stalled_stream`, `test_queue_budget_drops_are_counted_and_never_block_capture` |
| 5 | `shg/engine.py` | `test_shg_engine.py::test_consistency_flags_a_scale_or_extent_drift` |
| 6 | `shg/logs.py` | `test_shg_logs.py::test_scan_log_keeps_the_prototype_columns_in_order` |
| 7 | `ui/` | `test_ui_camera.py::test_apply_roi_calls_the_real_capture_engine`, `test_ui_main_window.py::test_the_three_menus_exist_with_their_tools` |
| 8 | `ui/focus_aid.py` | `test_ui_dialogs.py::test_focus_aid_shows_percentages_of_the_range` |
| 9 | `shg/engine.py` | `test_shg_engine.py::test_plan_mosaic_has_the_requested_rows_and_centred_offsets` |
| 10 | `capture/auto_exposure.py` | `test_capture_auto_exposure.py::test_loop_converges_to_the_target_exposure` |
| 11 | `shg/centering.py` | `test_shg_centering.py::test_sun_centering_symmetry_end_to_end_and_progress` |
| 12 | `shg/mosaic.py` | `test_shg_mosaic.py::test_plan_step_and_centring_match_the_prototype` |
| 13 | `shg/engine.py` | `test_shg_engine.py::test_run_adaptive_stop_ends_before_the_planned_duration` |
| 14 | `shg/geometry.py` | `test_shg_geometry.py::test_cos_dec_factor_is_the_spherical_correction` |
| 15 | `shg/limb.py` | `test_shg_limb.py::test_detector_reports_the_trailing_limb_after_two_dark_samples` |
| 16 | `shg/analysis.py` | `test_shg_analysis.py::test_slit_extent_matches_the_prototype_threshold_rule` |
| 17 | `config/store.py` | `test_config_store.py::test_profile_round_trip_keeps_telescope_camera_and_presets` |
| 18 | `capture/roi.py`, `ui/roi_editor.py` | `test_capture_roi.py::test_preset_and_model_round_trip_without_arithmetic`, `test_ui_roi_editor.py::test_default_reference_roi_is_scannable` |
| 19 | `shg/tilt.py` | `test_shg_tilt.py::test_tilted_edge_recovers_the_generating_slope` |
| 20 | `shg/polar.py` | `test_shg_polar.py::test_fit_recovers_a_known_altitude_and_azimuth_error` |
| 21 | `shg/centering.py`, `ui/` | `test_shg_centering.py::test_coarse_hill_climb_stops_inside_the_dead_zone`, `test_ui_telescope_panel.py::test_goto_sun_uses_the_provider` |
| 22 | `capture/engine.py`, `capture/ser.py` | `test_capture_engine.py::test_recording_writes_a_readable_ser_and_counts`, `test_capture_ser.py::test_header_has_the_standard_fields` |

**Cobertura parcial dentro de dos filas, no filas sin prueba:**

- Fila 4: el reintento único (`SCAN_RETRIES = 1` en `shg/engine.py`) no tiene
  una prueba dedicada; aborto, stall, guarda de disco y contabilidad sí.
- Fila 13: la precarga de AR (`preload_s > 0`) no se ejercita en ninguna prueba
  de `run`; la parada adaptativa y el padding sí.
- Fila 14: `cos_dec_correction` es un alias de `cos_dec_factor`, y la prueba
  cubre el factor; el alias no se llama por su nombre.

Ninguna fila queda sin módulo ni sin prueba. Los tres puntos anteriores son
huecos de cobertura de detalle, no de paridad funcional.

### 5. Verificado y no verificado

**Verificado en esta máquina (Linux, simulador):**

- Contratos de las cuatro capas y frontera de dependencias.
- Captura, stats, SER, ROI, tilt, limbo, centrado, barrido simple y mosaico,
  registros ADR-018, alineación polar, recon ligero, UI offscreen.
- Camino completo descubrimiento -> open -> configure -> centrado -> barrido ->
  recon con los motores reales y `SimCamera(pattern="solar")`.
- ADR-013 completo en la franja de referencia, con margen estrecho.
- Arranque de la GUI y `--self-test` con los motores reales.

**No verificado:**

- Hardware real: Touptek G3M678M, SDK nativo, USB, ASCOM/INDI.
- Windows: instalación, `.dll`, rutas, self-test.
- SER reales del usuario: no están en `SOLARSCRIBE_FIXTURES` en esta máquina;
  el `scan_log.csv` real del prototipo sí se validó.
- Coste de CPU aislado del pipeline (la cifra incluye el simulador).
- Salto del buzón Qt dentro de la latencia del visor.

### 6. Bloqueos y salvedades

- **Sin bloqueo numérico**: suite completa 511 passed / 20 skipped, rendimiento
  22 passed, GUI self-test 0.
- **Salvedad de integración**: el recon de la ventana sigue siendo el
  placeholder de banda submuestreada; `shg.recon.quick_recon` está probado y se
  usa en el test de integración, pero `ui/engines.py` no lo llama. Se reporta a
  `ux`/`shg`; no se corrige desde QE.
- **Observación**: `SolarScene` sobre `SimCamera(pattern="flat")` en la ventana
  frente a `SimCamera(pattern="solar")` en pruebas y banco.
- **Cobertura parcial**: reintento de fila y precarga de AR, ver §4.
- No se ha hecho commit.

---

## English

### 1. Commands and results

```
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q
511 passed, 20 skipped in 64.88s

SOLARSCRIBE_PERF=1 .venv/bin/python -m pytest tests/perf -q
22 passed in 8.52s

QT_QPA_PLATFORM=offscreen .venv/bin/python -m solarscribe gui --self-test
exit 0
```

The 20 skips are: 11 real fixtures absent on this machine
(`SOLARSCRIBE_FIXTURES` unset), 8 opt-in bench tests (no
`SOLARSCRIBE_PERF=1`) and the optional reference-ROI bench. There are no
`hardware`-marked tests in the suite; hardware remains unverified. The GUI
self-test builds the window with the real engines, starts capture and exits 0;
the `propagateSizeHints()` lines are normal offscreen-platform noise.

### 2. ADR-013 budget (real engine, 10 s)

`.venv/bin/python -m tests.perf.bench_capture --seconds 10`

| Metric | Budget | Measured | Verdict |
| --- | --- | --- | --- |
| Sustained fps | >= 120 | 120.177 | pass |
| Throughput | ~207 MB/s | 207.435 MB/s | pass |
| Dropped frames | <= 0.1 % | 0.000 % | pass |
| Sequence gaps | 0 | 0 | pass |
| Viewer latency (p95) | <= 150 ms | 2.636 ms | pass |
| Capture start | <= 5 s | 0.017 s | pass |
| Recording queue | <= 512 MB | 1.726 MB | pass |
| Writer vs stream | >= stream | 207.156 >= 203.287 MB/s | pass |
| Sustained disk | >= 250 MB/s | 1,505.648 MB/s | pass |

1215 frames over 10.110 s; latency p50/max 2.24/4.75 ms; RSS 36.9 / 53.0 /
53.0 MB; process CPU 35.0 % of one core (includes the simulator thread, not
isolated pipeline overhead). The margin is still narrow (on the order of 0.1 to
0.3 %): a two-tenths regression blocks, and the definitive figure belongs to the
phase 0 hardware run.

### 3. Integration verification at the boundaries

Added `tests/functional/test_integration_sim.py`, which walks the path the
window wires, without Qt and only through the public contracts:

1. **discovery**: `DeviceManagerImpl` with an available `SimCameraBackend`;
   cameras and mounts show up as `sim`;
2. **open**: `open_camera`/`open_mount` return unopened devices, and the test
   calls `open()`/`connect()`;
3. **configure**: `CaptureEngineImpl.configure` with the real `RoiModel`
   (3480x248, band 0,40,3480,160) and `CaptureParams`;
4. **centring**: `SunCenteringImpl` (symmetry) brings a disk 20" off the slit
   inside 1.5" (measured residual 0.4"), and the mount ends within 1.5" in Dec;
5. **scan**: `ScanEngineImpl.plan` + `run` on `SimCamera(pattern="solar")`
   bound to the mount; the sweep ends `COMPLETED`, one row, with frames written
   and no reason code;
6. **recon**: `shg.recon.quick_recon` over the real frames captured during the
   sweep; non-empty image, 80 frames used, contrast 1.0.

The test takes about 4 s and is marked `slow`. It uses
`SimCamera(pattern="solar")`, the same physical fixture as
`test_capture_sim.py`, and never pokes internals.

**Integration caveat (window recon).** The engine path is verified, but the
window still does not call `shg.recon.quick_recon`:
`ui/engines.py::EngineHarness._emit_recon` emits a downsampled band slice and
`QuickRecon` paints it. `shg/recon.py` exists, is tested in
`tests/unit/test_shg_recon.py` and is exercised in the test above, but it is
not wired into `ui/`. If the acceptance requires the real recon on screen, this
is the only open item; it is reported, not fixed by QE.

**Minor observation.** The window harness uses `SolarScene` over
`SimCamera(pattern="flat")`; the physical fixture of the tests and the bench is
`SimCamera(pattern="solar")`. Both are mount-coupled simulators, but they are
not the same object. It is not a functional failure; it should be unified when
`ux` and `video` close the simulator.

### 4. nightscribe-scan parity

All 22 rows of `design/notes/NIGHTSCRIBE-SCAN-PARITY.md` §1 have a module and at
least one test. The check table is in the Spanish section (same rows); the
summary is:

- Every row has a module under `solarscribe/` and a named test in `tests/`.
- Partial coverage **inside** two rows, not rows without a test: the single row
  retry (`SCAN_RETRIES = 1`) has no dedicated test; the RA preload
  (`preload_s > 0`) is not exercised by any `run` test. `cos_dec_correction` is
  covered through its `cos_dec_factor` alias.
- No parity row is missing a module or a test.

### 5. Verified and unverified

**Verified on this machine (Linux, simulator):**

- The four layer contracts and the dependency boundary.
- Capture, stats, SER, ROI, tilt, limb, centring, simple and mosaic scans,
  ADR-018 logs, polar alignment, light recon, offscreen UI.
- The full discovery -> open -> configure -> centring -> scan -> recon path
  with the real engines and `SimCamera(pattern="solar")`.
- The whole ADR-013 budget at the reference strip, with a narrow margin.
- GUI start and `--self-test` with the real engines.

**Unverified:**

- Real hardware: Touptek G3M678M, native SDK, USB, ASCOM/INDI.
- Windows: install, `.dll`, paths, self-test.
- The user's real SER files: not present under `SOLARSCRIBE_FIXTURES` on this
  machine; the prototype's real `scan_log.csv` was validated.
- Isolated pipeline CPU cost (the figure includes the simulator).
- The Qt mailbox hop inside viewer latency.

### 6. Blockers and caveats

- **No numeric blocker**: full suite 511 passed / 20 skipped, performance
  22 passed, GUI self-test 0.
- **Integration caveat**: the window recon is still the downsampled-band
  placeholder; `shg.recon.quick_recon` is tested and used by the integration
  test, but `ui/engines.py` does not call it. Reported to `ux`/`shg`; not fixed
  from QE.
- **Observation**: `SolarScene` over `SimCamera(pattern="flat")` in the window
  versus `SimCamera(pattern="solar")` in tests and bench.
- **Partial coverage**: row retry and RA preload, see §4.
- No commit.

---

## Archivos de esta pasada / Files in this pass

- `tests/functional/test_integration_sim.py` (new end-to-end functional test)
- `design/notes/QE-FINAL-GATE-2026-11-06.md` (this note)
- `design/notes/QE-GATE-REPORT-2026-11-06.md` (earlier contract and bench
  report; unchanged except the pointer)
