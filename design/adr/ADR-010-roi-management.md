# ADR-010: Gestión del ROI / ROI management

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-001 (rendimiento), ADR-002 (cámaras), ADR-006 (centrado),
ADR-008 (base de cámara), ADR-011 (flujo de sesión), ADR-022 (tilt).

## Español

**Contexto**: el barrido SHG **no usa todo el sensor**: se captura una franja
recortada (p. ej. 3480×248) que reduce el caudal de datos y da la tasa necesaria
(~120 fps). El ROI, por tanto, no es un ajuste menor: decide si el barrido es
posible. Además, las medidas del motor SHG (limbo, centrado en Dec, enfoque) se
hacen sobre **sub-regiones** del fotograma, que no coinciden con el ROI de
captura.

**Decisión**: el ROI es un **subsistema de primera clase** con cuatro regiones
diferenciadas:

1. **ROI de captura (sensor)**: lo que entrega la cámara; fija el FPS y el tamaño
   del SER. **Lo selecciona el usuario** en el paso ROI; no hay propuesta
   automática.
2. **ROI de análisis (software)**: sub-regiones del fotograma vivo para medir
   (mitades izquierda/derecha, columnas del limbo, celdas de enfoque y el ajuste
   del tilt). Se calculan, no se guardan.
3. **Banda/orden espectral**: la franja útil del espectro; debe caber dentro del
   ROI de captura (se avisa si se recorta).
4. **ROI de salida**: lo que se escribe al SER y consume el post-proceso
   (= ROI de captura).

Herramientas, **todas en el MVP**:

- **Editor en vivo**: overlay sobre el visor con asas arrastrables, campos
  numéricos y *snap* a la banda iluminada. **Lo selecciona el usuario**; no hay
  propuesta automática.
- **Presets** por cámara + óptica, persistidos en el perfil y restaurados al
  conectar.
- **Medición de tilt** (ADR-022): se ajusta una recta al borde de la rendija/línea
  espectral a lo ancho del ROI; la pendiente es el tilt, en grados y en píxeles de
  deriva. Valida la altura del ROI, guía al usuario y se registra.
- **Validación**: recorte del orden, alineación rendija↔espectro, altura según el
  tilt, FPS y caudal estimados, límites del SDK (múltiplos, binning) y coherencia
  al cambiar de binning.
- El ROI y el tilt quedan registrados en `session_meta.json` y `scan_log.csv`
  para reproducir la toma.

El **ROI de captura lo elige el usuario en el paso *ROI*** del flujo de sesión
(§9, ADR-011), que lo valida (tamaño, tilt, FPS) y bloquea el preset antes de
barrer.

**Alternativas**: un único ROI implícito (no cubre las sub-regiones de medida ni
la validación); dejar el ROI a la herramienta de la cámara (rompe la promesa
multiplataforma y la reproducibilidad). Se descartan.

**Consecuencias**: la tasa se controla de forma explícita y reproducible; el
usuario ve y ajusta la franja que de verdad se usa; un ROI mal ceñido se detecta
antes de barrer, no en el post-proceso.

## English

**Context**: the SHG scan **does not use the whole sensor**: a cropped strip is
captured (e.g. 3480×248) to cut the data rate and reach the needed rate
(~120 fps). The ROI is therefore no minor setting: it decides whether the scan is
possible. On top of that, the SHG engine's measurements (limb, Dec centring,
focus) are taken on **sub-regions** of the frame, which do not match the capture
ROI.

**Decision**: the ROI is a **first-class subsystem** with four distinct regions:

1. **Capture ROI (sensor)**: what the camera delivers; it sets the FPS and the
   SER size. **The user selects it** in the ROI step; there is no automatic
   proposal.
2. **Analysis ROI (software)**: sub-regions of the live frame for measuring
   (left/right halves, limb columns, focus cells and the tilt fit). Computed, not
   stored.
3. **Spectral band/order**: the useful strip of the spectrum; it must fit inside
   the capture ROI (a warning is shown if it is clipped).
4. **Output ROI**: what is written to the SER and consumed by post-processing
   (= capture ROI).

Tools, **all in the MVP**:

- **Live editor**: overlay on the viewer with draggable handles, numeric fields
  and *snap* to the illuminated band. **The user selects it**; there is no
  automatic proposal.
- **Presets** per camera + optic, persisted in the profile and restored on
  connect.
- **Tilt measurement** (ADR-022): a line is fitted to the slit/spectral-line edge
  across the ROI width; the slope is the tilt, in degrees and in drift pixels. It
  validates the ROI height, guides the user and is recorded.
- **Validation**: order clipping, slit↔spectrum alignment, height from the tilt,
  estimated FPS and data rate, SDK limits (multiples, binning) and coherence when
  the binning changes.
- The ROI and the tilt are recorded in `session_meta.json` and `scan_log.csv` to
  reproduce the take.

The **capture ROI is chosen by the user in the *ROI* step** of the session flow
(§9, ADR-011), which validates it (size, tilt, FPS) and locks the preset before
scanning.

**Alternatives**: a single implicit ROI (does not cover the measurement
sub-regions nor validation); leaving the ROI to the camera's own tool (breaks the
cross-platform promise and reproducibility). Dropped.

**Consequences**: the rate is controlled explicitly and reproducibly; the user
sees and adjusts the strip that is actually used; a badly fitted ROI is caught
before scanning, not in post-processing.
