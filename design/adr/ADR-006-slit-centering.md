# ADR-006: Centrado del Sol en la rejilla / Sun centering on the slit

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

## Español

**Contexto**: hay que centrar el Sol en Dec sobre la rendija partiendo de un
preapuntado básico. La extensión iluminada del espectro es máxima en el centro,
pero su derivada es nula ahí (la cuerda cumple `L = 2·√(R² − q²)`), así que hay
una **zona muerta** alrededor del centro.

**Decisión**: centrado en dos pasos.

1. **Grueso, por histograma y extensión**: un *hill-climb* en Dec que maximiza
   la fracción de píxeles brillantes (percentil alto del histograma, equivalente
   a la extensión iluminada). Rápido, sobre el frame vivo, sin barrido.
2. **Fino**: simetría izquierda/derecha si el disco cabe a lo largo de la
   rendija; si no, el método de la cuerda (barrido).

La interfaz **dice explícitamente** que el paso grueso no elimina la zona muerta
y que el fino es necesario.

**Alternativas**: solo histograma (no resuelve el centro); solo cuerda (más
lento). Se combinan.

**Consecuencias**: puesta en estación rápida y honesta sobre sus límites; el
motor SHG reutiliza el limbo y la cuerda que ya tiene.

## English

**Context**: the Sun must be centred in Dec on the slit starting from a basic
pre-pointing. The illuminated extent of the spectrum is maximal at the centre,
but its derivative is zero there (the chord is `L = 2·√(R² − q²)`), so there is a
**dead zone** around the centre.

**Decision**: two-step centring.

1. **Coarse, by histogram and extent**: a Dec *hill-climb* that maximises the
   fraction of bright pixels (high histogram percentile, equivalent to the
   illuminated extent). Fast, on the live frame, no scan.
2. **Fine**: left/right symmetry when the disk fits along the slit; otherwise
   the chord method (a scan).

The UI **states explicitly** that the coarse step does not remove the dead zone
and that the fine step is required.

**Alternatives**: histogram only (does not resolve the centre); chord only
(slower). They are combined.

**Consequences**: a fast, honest setup that is upfront about its limits; the SHG
engine reuses the limb and chord it already has.
