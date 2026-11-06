# ADR-003: Configuración y perfiles / Configuration and profiles

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

## Español

**Contexto**: `nightscribe-scan` ya define un esquema de configuración y unos
formatos de log que el usuario conoce y que usa el post-proceso.

**Decisión**: SolarScribe hereda el esquema **INI** de `nightscribe-scan`
(mismas claves) y los perfiles **JSON** con datos del telescopio. Los ficheros de
log (`scan_log.csv`, `scan_stats.jsonl`, `session_meta.json`) mantienen las
mismas columnas.

**Alternativas**: un esquema nuevo (JSON/TOML). Se descarta: rompería el
post-proceso y los hábitos del usuario sin ganar nada.

**Consecuencias**: continuidad total con el prototipo; el post-proceso existente
sigue valiendo tal cual.

## English

**Context**: `nightscribe-scan` already defines a configuration schema and log
formats the user knows and the post-processing consumes.

**Decision**: SolarScribe inherits the **INI** schema of `nightscribe-scan`
(same keys) and the **JSON** profiles with telescope data. The log files
(`scan_log.csv`, `scan_stats.jsonl`, `session_meta.json`) keep the same columns.

**Alternatives**: a new schema (JSON/TOML). Dropped: it would break
post-processing and user habits with nothing gained.

**Consequences**: full continuity with the prototype; the existing
post-processing keeps working as is.
