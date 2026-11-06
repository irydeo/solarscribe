# ADR-000: Usar ADRs / Use ADRs

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

## Español

**Contexto**: SolarScribe debe ser mantenible por personas y otras IAs; las
decisiones de diseño se olvidan si no se escriben.

**Decisión**: cada decisión de arquitectura o diseño se documenta como un ADR
numerado en `design/adr/`, bilingüe (ES/EN), con el formato Contexto, Decisión,
Alternativas y Consecuencias. Los ADRs aceptados no se reescriben; se sustituyen
por uno nuevo que los referencia.

**Consecuencias**: cualquiera puede entender el porqué del código en minutos;
cambiar una decisión exige actualizar o crear el ADR correspondiente.

## English

**Context**: SolarScribe must be maintainable by humans and other AIs; design
decisions are forgotten unless written down.

**Decision**: every architecture or design decision is documented as a numbered
ADR in `design/adr/`, bilingual (ES/EN), with the format Context, Decision,
Alternatives and Consequences. Accepted ADRs are not rewritten; a new
superseding ADR references them.

**Consequences**: anyone can understand the why of the code in minutes;
changing a decision requires updating or creating the matching ADR.
