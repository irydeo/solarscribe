# ADR-015: Estrategia de pruebas y fixtures / Test strategy and fixtures

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-005 (simuladores), ADR-013 (presupuesto), ADR-012 (contratos).

## Español

**Contexto**: ADR-005 fijó los simuladores y las pruebas con datos reales como
fixtures. Con siete agentes y tres tipos de calidad exigidos (unitaria,
funcional y de rendimiento), hace falta el detalle de cómo se prueba cada arista.

**Decisión**: tres capas de prueba, custodiadas por el agente QE.

1. **Unitaria (TDD estricto)**: sin hardware, con simuladores de cámara y montura.
   Ningún cambio de producto sin una prueba escrita antes que falle sin él. Se
   prueba en las fronteras de `design/ARCHITECTURE.md`, no en los internos.
2. **Funcional**: con mocks y con **vídeos/SER reales** que aporta el usuario como
   fixtures, guardados en una **ruta externa** al repositorio (configurable, no
   versionada). La calidad se evalúa contra esos ejemplos cuando se requiere
   (p. ej. métricas del motor SHG sobre un barrido real). El hardware real va
   marcado aparte.
3. **Rendimiento**: un banco mide el presupuesto de ADR-013 (fps, frames perdidos,
   caudal, latencia, memoria). Una regresión bloquea.

Reglas: cada fixture real se cataloga (de dónde salió, qué contiene, qué prueba);
cada fórmula científica se ancla a una referencia externa (ADR-006, ADR-007); los
gates G1–G3 de `AGENTS.md` son la puerta de entrada.

**Alternativas**: solo unitarias (no detectan la física ni la tasa); solo
funcionales (lentas y frágiles). Se combinan.

**Consecuencias**: se puede desarrollar casi todo sin telescopio; la validación
final de tasa y de SDK exige hardware. El catálogo de fixtures crece con cada
vídeo que aporta el usuario.

## English

**Context**: ADR-005 fixed the simulators and the real-data fixtures. With seven
agents and three demanded quality kinds (unit, functional and performance), the
detail of how each edge is tested is needed.

**Decision**: three test layers, custodied by the QE agent.

1. **Unit (strict TDD)**: no hardware, with camera and mount simulators. No
   product change without a test written first that fails without it. Tested at
   the boundaries of `design/ARCHITECTURE.md`, not on internals.
2. **Functional**: with mocks and with **real videos/SER** the user provides as
   fixtures, stored in a **path external** to the repository (configurable, not
   versioned). Quality is evaluated against those examples when required (e.g. SHG
   engine metrics over a real scan). Real hardware is marked apart.
3. **Performance**: a bench measures the ADR-013 budget (fps, dropped frames,
   throughput, latency, memory). A regression blocks.

Rules: every real fixture is catalogued (where it came from, what it holds, what it
tests); every scientific formula is anchored to an external reference (ADR-006,
ADR-007); gates G1–G3 of `AGENTS.md` are the entry door.

**Alternatives**: unit only (misses the physics and the rate); functional only
(slow and brittle). They are combined.

**Consequences**: almost everything can be developed without a telescope; the final
rate and SDK validation needs hardware. The fixture catalogue grows with every
video the user provides.
