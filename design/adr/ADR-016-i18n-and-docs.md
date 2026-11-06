# ADR-016: i18n y documentación / i18n and documentation

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-000 (ADRs), ADR-009 (UI).

## Español

**Contexto**: SolarScribe es hermano de NightScribe, que ya tiene la interfaz y la
documentación bilingües ES/EN. El observador y el público son hispanohablantes e
ingleses; añadir i18n después es caro.

**Decisión**:

- **i18n desde el día 1**: toda cadena visible pasa por `self.tr()`; catálogos
  `.ts` ES/EN (Qt Linguist) mantenidos con `lupdate`/`lrelease`. Al tocar cadenas,
  se regeneran los catálogos y se exige **0 sin traducir** en ambos idiomas.
- **Documentación bilingüe**: la guía de usuario en `solarscribe/docs/`, en
  español e inglés; el diseño interno en `design/`. Los ADRs son bilingües y el
  índice `design/adr/README.md` se mantiene al día.
- **CHANGELOG bilingüe** (`CHANGELOG.md` / `CHANGELOG.es.md`).
- **Lenguaje llano**: la interfaz nunca muestra una cifra sin explicar qué
  significa y por qué importa.
- **Lenguaje natural**: nunca el guion largo; ":", "," y ";". El guion medio,
  solo para rangos numéricos.

**Alternativas**: i18n al final (más caro y con cadenas olvidadas); solo inglés
(excluye al público natural del proyecto). Se descartan.

**Consecuencias**: el esfuerzo de traducción se reparte; el agente `docs` reporta
el estado de traducción; un test vigila que no queden cadenas sin traducir.

## English

**Context**: SolarScribe is NightScribe's sibling, which already has a bilingual
ES/EN interface and documentation. The observer and the audience are Spanish and
English speakers; adding i18n later is expensive.

**Decision**:

- **i18n from day one**: every visible string goes through `self.tr()`; ES/EN
  `.ts` catalogues (Qt Linguist) maintained with `lupdate`/`lrelease`. When strings
  change, the catalogues are regenerated and **0 untranslated** is required in both
  languages.
- **Bilingual documentation**: the user guide in `solarscribe/docs/`, in Spanish
  and English; the internal design in `design/`. ADRs are bilingual and the
  `design/adr/README.md` index is kept current.
- **Bilingual CHANGELOG** (`CHANGELOG.md` / `CHANGELOG.es.md`).
- **Plain language**: the interface never shows a figure without explaining what it
  means and why it matters.
- **Natural language**: never the em dash; ":", "," and ";". The en dash only for
  numeric ranges.

**Alternatives**: i18n at the end (more expensive and with forgotten strings);
English only (excludes the project's natural audience). Dropped.

**Consequences**: the translation effort is spread out; the `docs` agent reports
the translation status; a test guards against untranslated strings.
