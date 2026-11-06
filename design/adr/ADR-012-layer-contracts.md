# ADR-012: Contratos entre capas y modelo de datos / Layer contracts and data model

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-001 (arquitectura), ADR-008 (base de cámara), ADR-010 (ROI),
ADR-011 (sesión).

## Español

**Contexto**: siete agentes van a trabajar en paralelo sobre capas distintas
(`devices`, `capture`, `shg`, `ui`, `cli`). Si los límites entre capas quedan
implícitos, cada agente inventará su propia idea de `Frame`, `ROI` o `ScanEngine`
y la integración será un campo de minas.

**Decisión**: los contratos entre capas se escriben **explícitamente** en
`design/ARCHITECTURE.md` como `Protocol`/ABC de Python, y se custodian aquí. El
documento fija:

- Las interfaces `Camera`, `Mount`, `Frame`, `FrameStats`, `ROI`, `DeviceManager`
  (capa `devices`).
- `CaptureEngine`, `SerWriter`, `WriterCounters` (capa `capture`).
- `ScanEngine` y sus estructuras de progreso y resultado (capa `shg`).
- `SessionState` y el estado de los pasos (capa `ui`).
- El modelo de datos: `RoiModel`, perfil JSON v2, esquema INI y registros.

La regla de dependencias (`ui`/`cli` -> `capture`/`shg` -> `devices`) se verifica
con un test que falla si se rompe.

**Alternativas**: dejar los contratos al buen juicio de cada agente (rápido al
principio, caro después); un único módulo monolítico (imposible de paralelizar).
Se descartan.

**Consecuencias**: los agentes trabajan a la vez contra una frontera estable; un
cambio de contrato exige actualizar `design/ARCHITECTURE.md` y, si es una decisión,
un ADR nuevo. Se añade un test de capas al QE.

## English

**Context**: seven agents will work in parallel on different layers (`devices`,
`capture`, `shg`, `ui`, `cli`). If the boundaries stay implicit, each agent will
invent its own idea of `Frame`, `ROI` or `ScanEngine` and integration becomes a
minefield.

**Decision**: the layer contracts are written **explicitly** in
`design/ARCHITECTURE.md` as Python `Protocol`/ABCs, custodied here. The document
fixes:

- The `Camera`, `Mount`, `Frame`, `FrameStats`, `ROI`, `DeviceManager` interfaces
  (`devices` layer).
- `CaptureEngine`, `SerWriter`, `WriterCounters` (`capture` layer).
- `ScanEngine` and its progress and result structures (`shg` layer).
- `SessionState` and the step state (`ui` layer).
- The data model: `RoiModel`, JSON v2 profile, INI schema and logs.

The dependency rule (`ui`/`cli` -> `capture`/`shg` -> `devices`) is enforced by a
test that fails if it is broken.

**Alternatives**: leave the contracts to each agent's judgement (fast at first,
expensive later); a single monolithic module (impossible to parallelise). Dropped.

**Consequences**: agents work at the same time against a stable boundary; a
contract change requires updating `design/ARCHITECTURE.md` and, if it is a decision,
a new ADR. A layer test is added to QE.
