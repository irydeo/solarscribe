# SolarScribe: el equipo de agentes / The agent team

*Documento de equipo. Bilingüe ES/EN. Acompaña a [AGENTS.md](../AGENTS.md)
(reglas) y a `.opencode/agents/*.md` (definiciones operativas).*

Estado: **borrador v0**. Fecha: 2026-11-06.

---

## Español

### 1. Qué es esto

SolarScribe se construye con **siete agentes** que trabajan en paralelo sobre
capas distintas. Este documento los deja documentados para que la implementación
pueda continuar en **otra máquina**: describe qué hace cada uno, qué posee, qué
custodia, qué recibe, qué entrega y cuándo se le invoca.

Las definiciones que el arnés (OpenCode) carga de verdad viven en
`.opencode/agents/*.md` y **viajan con el repositorio**; este documento es su
versión legible.

### 2. Modelo de trabajo

- **Propiedad**: cada agente es dueño de unos módulos y es el único que los
  toca.
- **Custodia**: cada agente custodia unos ADRs; si una decisión cambia, actualiza
  el ADR o crea uno nuevo que lo referencie (los aceptados no se reescriben).
- **Contratos**: los límites entre capas están en `design/ARCHITECTURE.md`
  (ADR-012). Nadie cambia un contrato sin pasar por el `lead`.
- **Gates** (ver `AGENTS.md`): G1 TDD, G2 funcional, G3 rendimiento, G4
  usabilidad, G5 empaquetado.
- **Hecho**: tests verdes, presupuesto cumplido, ADR actualizado e i18n al día.

#### 2.1 Simuladores: los implementa `video`, los revisa `qe`

ADR-005 hace de la cámara y de la montura simuladas un **backend de primera
clase**, no un apaño de pruebas. Viven en `devices/sim/`, implementan los
protocolos `Camera` y `Mount` y se cargan por el mismo registro que un driver
real. Por eso la propiedad es de `video`: es el único agente que toca `devices/`,
y tener el simulador en otra capa habría obligado a `qe` a escribir producto,
algo que ADR-015 le prohíbe. `qe` conserva la custodia de ADR-005 y ADR-015,
escribe las pruebas que los usan, los revisa y puede bloquear un cambio: la
decisión de que existan y de que no toquen hardware es suya; el código del
simulador es de `video`.

Esta es la desviación consciente respecto a la tabla original, que asignaba los
simuladores a `qe`: se corrigió la tabla para que refleje la realidad y la regla
de dependencias.

### 3. Los siete agentes

#### 3.1 `lead`: arquitectura e integración

- **Misión**: mantener el diseño coherente mientras siete agentes trabajan a la
  vez; guardar la regla de dependencias.
- **Propiedad**: `design/` (diseño, contratos, ADRs) y `config/`; la frontera entre
  capas.
- **Custodia**: ADR-000, 001, 003, 012, 018, 021.
- **Entradas**: propuestas de contrato, conflictos entre agentes, dudas de
  diseño, cambios de esquema de configuración.
- **Salidas**: `design/ARCHITECTURE.md`, ADRs nuevos, índice de ADRs al día.
- **Cuándo invocarlo**: cambio de interfaz, dos agentes que se pisan, decisión de
  diseño nueva, migración de config.
- **Modelo**: `fireworks-ai/accounts/fireworks/models/qwen3p8-max`.
- **Hecho**: contratos sin huecos, índice de ADRs consistente, tests unitarios
  verdes.

#### 3.2 `video`: cámara, montura y captura

- **Misión**: que la app hable con cámara y montura y que el stream no pierda
  frames. Es la ruta crítica del proyecto.
- **Propiedad**: `devices/` (interfaces + drivers: nativos ASI/QHY/Player One/
  Touptek, el simulador de cámara y montura en `devices/sim/`, montura **ASCOM
  COM** en Windows e **INDI** en Linux) y `capture/` (stream, stats, SER). El ROI
  de captura.
- **Custodia**: ADR-002, 008, 010, 013, 019.
- **Entradas**: contratos de `design/ARCHITECTURE.md`, presupuesto de ADR-013,
  vídeos reales como fixtures.
- **Salidas**: drivers y pipeline, banco de rendimiento, informe de validación
  por SDK.
- **Cuándo invocarlo**: cámaras, monturas, SDK, hilos, frames perdidos, fps, ROI
  de captura, ASCOM/INDI.
- **Modelo**: `fireworks-ai/accounts/fireworks/models/qwen3p8-max`.
- **Hecho**: unitarias y funcionales verdes; presupuesto de ADR-013 cumplido o
  desviación reportada con números.

#### 3.3 `shg`: motor SHG y ciencia

- **Misión**: que el cálculo sea correcto: limbo, tasa de barrido, centrado,
  mosaico, alineación polar y **tilt**.
- **Propiedad**: `shg/`.
- **Custodia**: ADR-006, 007, 022.
- **Entradas**: `Frame` y `FrameStats`, sesiones reales como fixtures.
- **Salidas**: motor de barrido, modelo de alineación polar, medición de tilt,
  filas de `scan_log.csv`/`scan_stats.jsonl`/`session_meta.json`.
- **Cuándo invocarlo**: limbo, calibración, centrado en Dec, geometría del
  mosaico, matemática de la polar, tilt.
- **Modelo**: `fireworks-ai/accounts/fireworks/models/kimi-k3`.
- **Hecho**: unitarias verdes, cada fórmula anclada a una referencia **externa**.

#### 3.4 `ux`: interfaz y usabilidad

- **Misión**: que escanear sea fácil para cualquiera. Es el crítico más duro del
  equipo.
- **Propiedad**: `ui/` (tema, `.ui`, raíl de pasos, visor, editor de ROI, panel
  de telescopio).
- **Custodia**: ADR-009, 011, 020.
- **Entradas**: contratos, estado de sesión, decisiones de estilo de NightScribe.
- **Salidas**: UI temada, raíl de pasos, editor de ROI, panel de telescopio,
  visualización del barrido, recon rápido y un **guion de tareas** de usabilidad
  por función.
- **Cuándo invocarlo**: cualquier cambio visible, el flujo por pasos, el tema, el
  menú, el editor de ROI, el panel de telescopio, la visualización del barrido.
- **Modelo**: `fireworks-ai/accounts/fireworks/models/qwen3p8-max`.
- **Hecho**: GUI arranca en `offscreen`, unitarias verdes, guion de usabilidad
  superado y cada punto de fricción escrito.

#### 3.5 `qe`: integridad y calidad

- **Misión**: la red de seguridad. No escribe producto: escribe pruebas y **puede
  bloquear**.
- **Propiedad**: `tests/` (unit, funcional, rendimiento) y los fixtures (vídeos
  reales del usuario); consume y revisa los simuladores de `devices/sim/`, que
  implementa `video`.
- **Custodia**: ADR-005, 015.
- **Entradas**: cada cambio de los demás agentes; los simuladores de
  `devices/sim/` como material de prueba; vídeos/SER reales (ruta externa).
- **Salidas**: suites de pruebas, catálogo de fixtures, banco de rendimiento,
  informe de gate por cambio.
- **Cuándo invocarlo**: antes de dar por hecho cualquier cambio; TDD; rendimiento;
  regresiones; catálogo de fixtures.
- **Modelo**: `fireworks-ai/accounts/fireworks/models/qwen3p8-2p4t-a95b`.
- **Hecho**: unitarias y funcionales verdes; presupuesto de ADR-013 cumplido o el
  cambio bloqueado con números.

#### 3.6 `packaging`: empaquetado y release

- **Misión**: Windows y Linux funcionales de serie, desde el MVP.
- **Propiedad**: `installer/`, la matriz de CI, `pyproject.toml`, las notas de
  release.
- **Custodia**: ADR-004, 017.
- **Entradas**: el código estable, las licencias de los SDK, los requisitos de
  plataforma (plataforma ASCOM y .NET en Windows; `indiserver` en Linux).
- **Salidas**: instaladores (`.iss`, `.spec`, `.deb`, `.rpm`), workflow de CI,
  fichero de licencias por SDK, changelog bilingüe.
- **Cuándo invocarlo**: releases, CI, licencias, rutas de plataforma, udev,
  versión.
- **Modelo**: `fireworks-ai/accounts/fireworks/models/glm-5p3`.
- **Hecho**: el paquete instala y arranca en Windows y Linux; smoke test en ambos.

#### 3.7 `docs`: documentación e i18n

- **Misión**: que la documentación y las traducciones sigan el ritmo del código.
- **Propiedad**: `design/` (prosa, contratos, ADRs) y `solarscribe/docs/` (guía de
  usuario), los catálogos
  `.ts` ES/EN y el CHANGELOG.
- **Custodia**: ADR-000, 016.
- **Entradas**: el código y las decisiones del resto.
- **Salidas**: guía de usuario ES/EN, prosa de ADRs, changelog, catálogos `.ts`.
- **Cuándo invocarlo**: tras tocar cadenas visibles, al cerrar un ADR, al
  documentar una función.
- **Modelo**: `fireworks-ai/accounts/fireworks/models/glm-5p3-flash`.
- **Hecho**: ES y EN a 0 sin traducir; índice de ADRs completo.

### 4. Invocación y portabilidad

- Las definiciones operativas son `.opencode/agents/lead.md`, `video.md`,
  `shg.md`, `ux.md`, `qe.md`, `packaging.md` y `docs.md`. El arnés las descubre
  por su `description`.
- **Modelos**: cada definición fija un `model:`. Los IDs pertenecen al proveedor
  `fireworks-ai`. En **otra máquina**, si ese proveedor o esos modelos no están
  disponibles, se cambia el campo `model:` de cada `.md` por uno equivalente; el
  resto de la definición no depende del modelo.
- **Arranque en una máquina nueva**:

```bash
git clone <repo> && cd solarscribe
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit
.venv/bin/python -m solarscribe gui
```

- El fichero `AGENTS.md` de la raíz son las instrucciones del proyecto que el
  arnés carga siempre; `design/adr/` y `design/ARCHITECTURE.md` son la fuente de
  verdad del diseño.

### 5. Flujo por fases

- **Fase 0 (spike)**: `video` construye el experimento mínimo (tasa real sin
  frames perdidos y control de montura) y `qe` monta el banco de rendimiento.
  Es la puerta de decisión.
- **Fase 1 (MVP)**: todos los agentes; `lead` fija contratos primero, `video` y
  `shg` implementan los motores, `ux` la sesión por pasos, `qe` la red, `packaging`
  los instaladores, `docs` la guía.
- **Fases 2 y 3**: más drivers, enfoque, diagnóstico y endurecimiento, repartidos
  entre los mismos agentes.

### 6. Resumen

| Agente | Posee | Custodia | Modelo |
| --- | --- | --- | --- |
| `lead` | `design/`, `config/`, frontera | 000, 001, 003, 012, 018, 021 | qwen3p8-max |
| `video` | `devices/` (con `sim/`), `capture/`, ROI de captura | 002, 008, 010, 013, 019 | qwen3p8-max |
| `shg` | `shg/` | 006, 007, 022 | kimi-k3 |
| `ux` | `ui/` | 009, 011, 020 | qwen3p8-max |
| `qe` | `tests/`, fixtures, banco de rendimiento | 005, 015 | qwen3p8-2p4t-a95b |
| `packaging` | `installer/`, CI, `pyproject.toml` | 004, 017 | glm-5p3 |
| `docs` | `design/`, `solarscribe/docs/`, `.ts`, CHANGELOG | 000, 016 | glm-5p3-flash |

---

## English

### 1. What this is

SolarScribe is built by **seven agents** working in parallel on different layers.
This document records them so the implementation can continue on **another
machine**: it describes what each one does, what it owns, what it custodies, what
it receives, what it delivers and when it is invoked.

The definitions the harness (OpenCode) actually loads live in
`.opencode/agents/*.md` and **travel with the repository**; this document is their
readable version.

### 2. Working model

- **Ownership**: each agent owns some modules and is the only one to touch them.
- **Custody**: each agent custodies some ADRs; if a decision changes, it updates
  the ADR or writes a new one that references it (accepted ones are not
  rewritten).
- **Contracts**: the layer boundaries live in `design/ARCHITECTURE.md` (ADR-012). No
  one changes a contract without going through `lead`.
- **Gates** (see `AGENTS.md`): G1 TDD, G2 functional, G3 performance, G4 usability,
  G5 packaging.
- **Done**: tests green, budget met, ADR updated and i18n current.

#### 2.1 Simulators: `video` implements them, `qe` reviews them

ADR-005 makes the simulated camera and mount a **first-class backend**, not a
test hack. They live in `devices/sim/`, implement the `Camera` and `Mount`
protocols and are loaded through the same registry as a real driver. Ownership
therefore belongs to `video`: it is the only agent that touches `devices/`, and
putting the simulator in another layer would have forced `qe` to write product,
which ADR-015 forbids. `qe` keeps the custody of ADR-005 and ADR-015, writes the
tests that use them, reviews them and can block a change: the decision that they
exist and touch no hardware is theirs; the simulator code is `video`'s.

This is the conscious deviation from the original table, which assigned the
simulators to `qe`: the table was corrected so it reflects the reality and the
dependency rule.

### 3. The seven agents

#### 3.1 `lead`: architecture and integration

- **Mission**: keep the design coherent while seven agents work at once; guard the
  dependency rule.
- **Ownership**: `design/` (design, contracts, ADRs) and `config/`; the layer
  boundary.
- **Custody**: ADR-000, 001, 003, 012, 018, 021.
- **Inputs**: contract proposals, conflicts between agents, design questions,
  config schema changes.
- **Outputs**: `design/ARCHITECTURE.md`, new ADRs, a current ADR index.
- **When to invoke**: interface change, two agents colliding, a new design
  decision, a config migration.
- **Model**: `fireworks-ai/accounts/fireworks/models/qwen3p8-max`.
- **Done**: contracts with no gaps, consistent ADR index, green unit tests.

#### 3.2 `video`: camera, mount and capture

- **Mission**: that the app talks to camera and mount and the stream loses no
  frames. It is the project's critical path.
- **Ownership**: `devices/` (interfaces + drivers: native ASI/QHY/Player One/
  Touptek, the camera and mount simulator in `devices/sim/`, mount **ASCOM COM**
  on Windows and **INDI** on Linux) and `capture/` (stream, stats, SER). The
  capture ROI.
- **Custody**: ADR-002, 008, 010, 013, 019.
- **Inputs**: contracts from `design/ARCHITECTURE.md`, the ADR-013 budget, real
  videos as fixtures.
- **Outputs**: drivers and pipeline, the performance bench, a validation report per
  SDK.
- **When to invoke**: cameras, mounts, SDKs, threads, dropped frames, fps, capture
  ROI, ASCOM/INDI.
- **Model**: `fireworks-ai/accounts/fireworks/models/qwen3p8-max`.
- **Done**: unit and functional tests green; the ADR-013 budget holds or the
  deviation is reported with numbers.

#### 3.3 `shg`: SHG engine and science

- **Mission**: that the maths is correct: limb, scan rate, centring, mosaic, polar
  alignment and **tilt**.
- **Ownership**: `shg/`.
- **Custody**: ADR-006, 007, 022.
- **Inputs**: `Frame` and `FrameStats`, real sessions as fixtures.
- **Outputs**: scan engine, polar alignment model, tilt measurement, rows of
  `scan_log.csv`/`scan_stats.jsonl`/`session_meta.json`.
- **When to invoke**: limb, calibration, Dec centring, mosaic geometry, polar
  maths, tilt.
- **Model**: `fireworks-ai/accounts/fireworks/models/kimi-k3`.
- **Done**: unit tests green, each formula anchored to an **external** reference.

#### 3.4 `ux`: interface and usability

- **Mission**: that scanning is easy for anybody. It is the team's harshest
  critic.
- **Ownership**: `ui/` (theme, `.ui`, step rail, viewer, ROI editor, telescope
  panel).
- **Custody**: ADR-009, 011, 020.
- **Inputs**: contracts, session state, NightScribe's style decisions.
- **Outputs**: themed UI, step rail, ROI editor, telescope panel, scan
  visualisation, quick recon and a **task script** for usability per feature.
- **When to invoke**: any visible change, the step flow, the theme, the menu, the
  ROI editor, the telescope panel, the scan visualisation.
- **Model**: `fireworks-ai/accounts/fireworks/models/qwen3p8-max`.
- **Done**: GUI starts offscreen, unit tests green, usability script passed and
  every friction point written down.

#### 3.5 `qe`: integrity and quality

- **Mission**: the safety net. It does not write product: it writes tests and **can
  block**.
- **Ownership**: `tests/` (unit, functional, performance) and the fixtures (the
  user's real videos); it consumes and reviews the simulators in `devices/sim/`,
  which `video` implements.
- **Custody**: ADR-005, 015.
- **Inputs**: every change by the other agents; the simulators in `devices/sim/`
  as test material; real videos/SER (external path).
- **Outputs**: test suites, fixture catalogue, performance bench, gate report per
  change.
- **When to invoke**: before declaring any change done; TDD; performance;
  regressions; fixture catalogue.
- **Model**: `fireworks-ai/accounts/fireworks/models/qwen3p8-2p4t-a95b`.
- **Done**: unit and functional tests green; the ADR-013 budget holds or the change
  is blocked with numbers.

#### 3.6 `packaging`: packaging and release

- **Mission**: Windows and Linux functional out of the box, from the MVP.
- **Ownership**: `installer/`, the CI matrix, `pyproject.toml`, the release notes.
- **Custody**: ADR-004, 017.
- **Inputs**: stable code, the SDK licences, the platform requirements (ASCOM
  Platform and .NET on Windows; `indiserver` on Linux).
- **Outputs**: installers (`.iss`, `.spec`, `.deb`, `.rpm`), CI workflow, licence
  file per SDK, bilingual changelog.
- **When to invoke**: releases, CI, licences, platform paths, udev, versioning.
- **Model**: `fireworks-ai/accounts/fireworks/models/glm-5p3`.
- **Done**: the package installs and starts on Windows and Linux; smoke test on
  both.

#### 3.7 `docs`: documentation and i18n

- **Mission**: that the documentation and the translations keep pace with the code.
- **Ownership**: `design/` (prose, contracts, ADRs) and `solarscribe/docs/` (user
  guide), the ES/EN `.ts`
  catalogues and the CHANGELOG.
- **Custody**: ADR-000, 016.
- **Inputs**: the code and the decisions of the rest.
- **Outputs**: ES/EN user guide, ADR prose, changelog, `.ts` catalogues.
- **When to invoke**: after touching visible strings, when closing an ADR, when
  documenting a feature.
- **Model**: `fireworks-ai/accounts/fireworks/models/glm-5p3-flash`.
- **Done**: ES and EN at 0 untranslated; complete ADR index.

### 4. Invocation and portability

- The operational definitions are `.opencode/agents/lead.md`, `video.md`, `shg.md`,
  `ux.md`, `qe.md`, `packaging.md` and `docs.md`. The harness discovers them by
  their `description`.
- **Models**: each definition sets a `model:`. The IDs belong to the `fireworks-ai`
  provider. On **another machine**, if that provider or those models are not
  available, change the `model:` field of each `.md` for an equivalent one; the
  rest of the definition does not depend on the model.
- **Starting on a new machine**:

```bash
git clone <repo> && cd solarscribe
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit
.venv/bin/python -m solarscribe gui
```

- The root `AGENTS.md` is the project instructions the harness always loads;
  `design/adr/` and `design/ARCHITECTURE.md` are the source of truth for the design.

### 5. Flow by phase

- **Phase 0 (spike)**: `video` builds the minimal experiment (real rate with no
  dropped frames and mount control) and `qe` sets up the performance bench. It is
  the decision gate.
- **Phase 1 (MVP)**: all agents; `lead` fixes contracts first, `video` and `shg`
  implement the engines, `ux` the step session, `qe` the net, `packaging` the
  installers, `docs` the guide.
- **Phases 2 and 3**: more drivers, focus, diagnostics and hardening, shared by
  the same agents.

### 6. Summary

| Agent | Owns | Custody | Model |
| --- | --- | --- | --- |
| `lead` | `design/`, `config/`, boundary | 000, 001, 003, 012, 018, 021 | qwen3p8-max |
| `video` | `devices/` (with `sim/`), `capture/`, capture ROI | 002, 008, 010, 013, 019 | qwen3p8-max |
| `shg` | `shg/` | 006, 007, 022 | kimi-k3 |
| `ux` | `ui/` | 009, 011, 020 | qwen3p8-max |
| `qe` | `tests/`, fixtures, performance bench | 005, 015 | qwen3p8-2p4t-a95b |
| `packaging` | `installer/`, CI, `pyproject.toml` | 004, 017 | glm-5p3 |
| `docs` | `design/`, `solarscribe/docs/`, `.ts`, CHANGELOG | 000, 016 | glm-5p3-flash |
