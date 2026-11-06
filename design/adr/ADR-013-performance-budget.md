# ADR-013: Presupuesto de rendimiento y observabilidad / Performance budget and observability

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-001 (rendimiento), ADR-008 (pipeline), ADR-010 (ROI),
ADR-015 (pruebas).

## Español

**Contexto**: el proyecto se juega su utilidad en la tasa. Un barrido a ~120 fps
en una franja recortada genera del orden de 200 MB/s; un solo frame perdido de
más arruina la reconstrucción. Sin un presupuesto con números, ni el agente de
vídeo ni el QE pueden decir "esto no cumple".

**Decisión**: se fija un **presupuesto de rendimiento provisional** (a validar y
cerrar en la fase 0) y una **observabilidad** que lo mida en vivo.

Presupuesto, para el ROI de referencia (3480×248 px, mono):

| Métrica | Objetivo |
| --- | --- |
| FPS sostenidos | ≥ 120 |
| Caudal | ~207 MB/s a 16 bit (1,73 MB/frame × 120) |
| Frames perdidos por barrido | ≤ 0,1% |
| Huecos de secuencia (nominal) | 0 |
| Latencia del visor | ≤ 150 ms (el DisplayBridge descarta, no acumula) |
| CPU del host | overhead del pipeline < 20% de un núcleo a 120 fps |
| Memoria | cola de grabación acotada (512 MB por defecto), RSS estable |
| Disco sostenido | ≥ 250 MB/s; aviso si < 1 GB libre |
| Arranque de captura | ≤ 5 s de start a primer frame |
| Stall | abortar si > 3 s sin frames |

Observabilidad: contadores de fps real, frames escritos, perdidos por SDK, por
cola y por huecos de secuencia, profundidad máxima de la cola y MB/s de disco;
un **panel de salud** en la UI y una muestra por barrido en `scan_stats.jsonl`.

**Alternativas**: fijar los números solo tras la fase 0 (se pierde el criterio
para desarrollarla); no fijarlos nunca (el rendimiento se degrada sin que nadie
lo note). Se elige provisional ahora y se cierra tras medir.

**Consecuencias**: el gate G3 es medible; una regresión de rendimiento bloquea;
los números se revisan y se confirman (o se corrigen) en la fase 0.

## English

**Context**: the project's usefulness hinges on the rate. A scan at ~120 fps on a
cropped strip produces on the order of 200 MB/s; a single extra dropped frame
ruins the reconstruction. Without a budget with numbers, neither the video agent
nor QE can say "this does not meet it".

**Decision**: a **provisional performance budget** is fixed (to validate and close
in phase 0) plus **observability** that measures it live.

Budget, for the reference ROI (3480×248 px, mono):

| Metric | Target |
| --- | --- |
| Sustained FPS | ≥ 120 |
| Throughput | ~207 MB/s at 16 bit (1.73 MB/frame × 120) |
| Dropped frames per scan | ≤ 0.1% |
| Sequence gaps (nominal) | 0 |
| Viewer latency | ≤ 150 ms (the DisplayBridge drops, does not queue) |
| Host CPU | pipeline overhead < 20% of one core at 120 fps |
| Memory | bounded recording queue (512 MB default), stable RSS |
| Sustained disk | ≥ 250 MB/s; warn if < 1 GB free |
| Capture start | ≤ 5 s from start to first frame |
| Stall | abort if > 3 s without frames |

Observability: counters for real fps, frames written, dropped by SDK, by queue and
by sequence gaps, queue high-water mark and disk MB/s; a **health panel** in the
UI and one sample per scan in `scan_stats.jsonl`.

**Alternatives**: fix the numbers only after phase 0 (loses the criterion to build
against); never fix them (performance degrades unnoticed). Chosen: provisional
now, closed after measuring.

**Consequences**: gate G3 is measurable; a performance regression blocks; the
numbers are reviewed and confirmed (or corrected) in phase 0.
