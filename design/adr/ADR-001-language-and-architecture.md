# ADR-001: Python puro con ctypes / Pure Python with ctypes

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

## Español

**Contexto**: la capa de cámara debe aguantar alta tasa (unos 120 fps en el ROI
típico, del orden de 200 MB/s) y hablar con SDK escritos en C. Se dudó entre un
núcleo nativo (C++) y Python.

**Decisión**: Python puro; el SDK en C se usa a través de `ctypes`/`cffi`. El
trabajo pesado (streaming y buffers) lo hace el propio SDK; Python copia y sella
el fotograma, calcula las estadísticas con numpy y escribe el SER en un hilo
aparte. Si el spike de la fase 0 demuestra un cuello de botella real, se añade un
helper nativo solo en ese punto, sin cambiar la arquitectura.

**Alternativas**: núcleo C++ con wrapper de Python (más rendimiento, pero dos
lenguajes); núcleo Rust (igual). Se descartan por coste y por alinear con
NightScribe.

**Consecuencias**: una sola lengua, mismos patrones que NightScribe y pruebas con
simuladores. El rendimiento depende de no bloquear nunca el hilo de captura.

## English

**Context**: the camera layer must sustain a high rate (~120 fps at the typical
ROI, on the order of 200 MB/s) and talk to C SDKs. A native core (C++) versus
Python was considered.

**Decision**: pure Python; the C SDK is used through `ctypes`/`cffi`. The heavy
lifting (streaming and buffers) is the SDK's; Python copies and stamps the
frame, computes the statistics with numpy and writes the SER on its own thread.
If the phase 0 spike shows a real bottleneck, a native helper is added only
there, without changing the architecture.

**Alternatives**: C++ core with a Python wrapper (more performance, two
languages); Rust core (same). Dropped for cost and for alignment with
NightScribe.

**Consequences**: one language, same patterns as NightScribe and
simulator-based tests. Performance depends on never blocking the capture thread.
