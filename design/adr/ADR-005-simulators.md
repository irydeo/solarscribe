# ADR-005: Simuladores y pruebas sin hardware / Simulators and hardware-free tests

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

## Español

**Contexto**: la lógica SHG y la UI deben probarse sin cámara ni montura, y el
proyecto del que derivamos ya trae un simulador de cámara.

**Decisión**: el **simulador de cámara** es un backend de primera clase (no un
apaño de pruebas); la **montura** tiene su propio simulador. Los tests unitarios
no tocan hardware; los funcionales van marcados aparte. La lógica SHG y las
métricas se prueban con **datos reales como fixtures** (como en
`nightscribe-scan`).

**Alternativas**: depender de hardware para probar. Se descarta: no es
reproducible ni automatizable.

**Consecuencias**: se puede desarrollar y validar casi todo el motor sin
telescopio; solo la validación final de tasa y de SDKs exige hardware.

## English

**Context**: the SHG logic and the UI must be testable without a camera or a
mount, and the project we derive from already ships a camera simulator.

**Decision**: the **camera simulator** is a first-class backend (not a test
hack); the **mount** has its own simulator. Unit tests touch no hardware;
functional tests are marked apart. The SHG logic and the metrics are tested with
**real data as fixtures** (as in `nightscribe-scan`).

**Alternatives**: depend on hardware for testing. Dropped: not reproducible and
not automatable.

**Consequences**: almost the whole engine can be developed and validated without
a telescope; only the final rate and SDK validation needs hardware.
