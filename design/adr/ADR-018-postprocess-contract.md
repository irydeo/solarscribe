# ADR-018: Contrato con el post-proceso / Contract with post-processing

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-003 (config y perfiles), ADR-008 (base de cámara), ADR-010
(ROI).

## Español

**Contexto**: SolarScribe **no hace post-proceso**: el recon, el apilado y el
mosaico siguen siendo externos (JSol'Ex y las herramientas de
`nightscribe-scan/tools`). La frontera entre captura y post-proceso es, por tanto,
un contrato de datos que no se puede romper.

**Decisión**: la frontera es **el SER más los registros**:

- Los ficheros `scan_log.csv`, `scan_stats.jsonl` y `session_meta.json` conservan
  **las mismas columnas** que `nightscribe-scan`.
- Las columnas nuevas (ROI, presupuesto de rendimiento, versión) se **añaden**;
  nunca se quitan ni se renombran.
- La cabecera del SER registra ROI, profundidad de bits, color ID y timestamps,
  de forma que el post-proceso sepa con qué se capturó.
- Cualquier cambio en esta frontera se documenta y se anuncia; si rompe el
  post-proceso existente, exige un ADR que lo sustituya.

**Alternativas**: un formato nuevo y propio (rompe el post-proceso y los hábitos
del usuario); dejar la frontera sin documentar (se rompe sola). Se descartan.

**Consecuencias**: el post-proceso existente sigue valiendo tal cual; SolarScribe
sustituye a SharpCap en la captura sin tocar la cadena de reducción.

## English

**Context**: SolarScribe **does not post-process**: recon, stacking and mosaic
remain external (JSol'Ex and the `nightscribe-scan/tools` utilities). The boundary
between capture and post-processing is therefore a data contract that must not
break.

**Decision**: the boundary is **the SER plus the logs**:

- The files `scan_log.csv`, `scan_stats.jsonl` and `session_meta.json` keep **the
  same columns** as `nightscribe-scan`.
- New columns (ROI, performance budget, version) are **added**; none are removed or
  renamed.
- The SER header records ROI, bit depth, colour ID and timestamps, so
  post-processing knows what was captured.
- Any change to this boundary is documented and announced; if it breaks existing
  post-processing, it requires an ADR that supersedes it.

**Alternatives**: a new, own format (breaks post-processing and user habits);
leaving the boundary undocumented (it breaks on its own). Dropped.

**Consequences**: the existing post-processing keeps working as is; SolarScribe
replaces SharpCap in capture without touching the reduction chain.
