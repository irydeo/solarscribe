# SolarScribe: contratos entre capas y modelo de datos

Estado: **borrador v0** (a iterar). Fecha: 2026-11-06.
Documento de apoyo de [DESIGN.md](../DESIGN.md) y de los ADRs. Describe **cómo se
construye en paralelo**: los contratos que cada agente implementa o consume, y
los datos que viajan entre capas. La versión inglesa llegará cuando el diseño se
estabilice.

> Regla de oro: **ningún contrato implícito**. Si un agente necesita saber qué es
> un tipo o qué promete un método, está aquí. Si cambia, cambia el ADR
> correspondiente (ADR-012).

---

## 1. Capas y regla de dependencias

```
ui/  cli/            <- presentación y arranque
   \   /
  capture/  shg/      <- motores (lógica sin Qt)
      \    /
     devices/         <- interfaces + drivers (no conoce la aplicación)
        |
      SDK / hardware
```

- `ui` y `cli` dependen de `capture` y `shg`.
- `capture` y `shg` dependen de `devices`.
- `devices` **no** depende de nada de la aplicación.
- `shg` no toca Qt ni un driver: consume `Frame` y `FrameStats`, y pide
  movimiento por el contrato `Mount`.
- Los contratos viven en `devices/abc.py`, `capture/abc.py`, `shg/abc.py` y
  `config/schema.py`. Se expresan como `Protocol`/ABC de Python.

La regla se verifica con un test (`tests/unit/test_layers.py`) que falla si
`devices` importa de `capture`/`shg`/`ui`, o si `shg` importa de Qt.

---

## 2. Contratos

Los nombres son los del proyecto base `simple-astro-cap` (ADR-008) allí donde ya
existen (`Frame`, `Param`, `ROI`, `CameraInfo`, `CameraBase`, `MultiCamera`).

### 2.1 `devices` (cámara y montura)

```python
# ROI: región rectangular en píxeles del sensor (o del frame ya bineado).
ROI = (x: int, y: int, width: int, height: int)

# Frame: fotograma inmutable entregado por el backend. El backend copia y sella;
# el consumidor no lo modifica.
class Frame(Protocol):
    data: memoryview          # uint8 | uint16, C-contiguo
    width: int
    height: int
    dtype: np.dtype           # uint8 | uint16
    roi: ROI                  # ROI de captura del que procede
    sequence: int             # contador del backend, para detectar huecos
    timestamp: float          # segundos, tomado al recibir (no al escribir)
    def stats(self) -> FrameStats: ...
    def cut_roi(self, roi: ROI) -> "Frame": ...   # vista de sub-región

# FrameStats: medidas de un frame o de una sub-región.
class FrameStats(Protocol):
    mean: float
    std: float

# Camera: lo que usan la app y el motor SHG. Ciclo de vida, propiedades, stream.
class Camera(Protocol):
    def open(self) -> None: ...
    def close(self) -> None: ...
    def is_open(self) -> bool: ...
    def get_roi(self) -> ROI: ...
    def set_roi(self, roi: ROI) -> None: ...
    def effective_area(self) -> ROI: ...        # área máxima (sensor/binning)
    def get_param(self, p: Param) -> float: ... # exposure, gain, offset, ...
    def set_param(self, p: Param, value: float) -> None: ...
    def start_stream(self, on_frame: Callable[[Frame], None]) -> None: ...
    def stop_stream(self) -> None: ...
    def info(self) -> CameraInfo: ...           # vendor, model, id, capabilities

# Mount: conexión, posición, movimiento, seguimiento, park. El motor SHG y el
# panel de telescopio de la UI usan el mismo contrato; el backend es ASCOM con
# COM nativo en Windows e INDI contra `indiserver` en Linux (ADR-019).
class Mount(Protocol):
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def is_connected(self) -> bool: ...
    def position(self) -> tuple[float, float]: ...   # (ra_horas, dec_grados)
    def move_axis(self, axis: Axis, rate: float) -> None: ...
    def stop(self) -> None: ...
    def slew(self, ra: float, dec: float) -> None: ...
    def sync(self, ra: float, dec: float) -> None: ...
    def set_tracking(self, on: bool) -> None: ...
    def park(self) -> None: ...
    def unpark(self) -> None: ...
    def abort_slew(self) -> None: ...
    def capabilities(self) -> MountCaps: ...         # tasas, reporta posición...

# DeviceManager: descubre backends y dispositivos; degrada si falta un SDK.
class DeviceManager(Protocol):
    def backends(self) -> list[BackendInfo]: ...     # presente/ausente y motivo
    def cameras(self) -> list[CameraInfo]: ...
    def mounts(self) -> list[MountInfo]: ...
    def open_camera(self, camera_id: str) -> Camera: ...
    def open_mount(self, mount_id: str) -> Mount: ...
```

### 2.2 `capture`

```python
# CaptureEngine: stream, stats y grabación. No conoce Qt.
class CaptureEngine(Protocol):
    def configure(self, camera: Camera, roi: RoiModel,
                  params: CaptureParams) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def on_stats(self, cb: Callable[[FrameStats], None]) -> None: ...
    # El motor publica cada frame a: consumidores inline (baratos) y, si graba,
    # a la cola acotada del SerWriter.
    def start_recording(self, path: Path, header: SerHeader) -> None: ...
    def stop_recording(self) -> WriterCounters: ...

# SerWriter: escritura SER bufferizada, con contabilidad de frames perdidos.
class SerWriter(Protocol):
    def open(self, path: Path, header: SerHeader) -> None: ...
    def write(self, frame: Frame) -> None: ...
    def close(self) -> None: ...
    def counters(self) -> WriterCounters: ...   # escritos, perdidos por cola

class WriterCounters(Protocol):
    frames_written: int
    frames_dropped_queue: int
    queue_high_water_mb: float
```

### 2.3 `shg`

```python
# ScanEngine: plan -> preparación (centrado fino + autocalibración) -> barrido.
class ScanEngine(Protocol):
    def plan(self, config: ScanConfig) -> ScanPlan: ...
    def prepare(self, cb: Callable[[PrepareStatus], None]) -> PrepareResult: ...
    def run(self, plan: ScanPlan,
            cb: Callable[[ScanProgress], None]) -> ScanResult: ...
    def abort(self) -> None: ...

# El motor mide por sub-regiones del ROI de análisis (ADR-010):
#   - mitades izquierda/derecha para el centrado en Dec,
#   - columnas del limbo para la detección,
#   - celdas de la rejilla de enfoque.
```

### 2.4 `ui` y estado de sesión

```python
# SessionState: el estado persistente de los cuatro pasos (ADR-011).
class StepStatus(Enum):
    PENDING = "pending"; CURRENT = "current"
    DONE = "done"; SKIPPED = "skipped"

class SessionState:
    steps: dict[str, StepState]     # find_sun, polar, roi, scan
    def save(self, path: Path) -> None: ...
    @classmethod
    def load(cls, path: Path) -> "SessionState": ...
    # Autoguardado silencioso tras cada cambio de estado.
```

La UI **no** contiene lógica de negocio: escucha `CaptureEngine` y `ScanEngine`,
pinta el estado de `SessionState` y delega. La regla de `self.tr()` (ADR-016)
aplica a toda cadena visible.

---

## 3. Modelo de datos

### 3.1 ROI y tilt (ADR-010, ADR-022)

```python
class RoiModel:
    capture: ROI                 # ROI de hardware (manda en el FPS); lo elige el usuario
    band: ROI                    # banda/orden espectral (debe caber en capture)
    analysis: dict[str, ROI]     # sub-regiones con nombre (left, right, limb...)
    constraints: RoiConstraints  # múltiplos, mínimos, binning admitidos
    tilt_deg: float              # tilt medido del espectro/rendija (grados)
    tilt_px: float               # deriva del tilt a lo ancho del ROI (px)
    # output == capture (lo que va al SER)

    def validate(self) -> list[RoiWarning]: ...       # recorte, alineación, altura/tilt, SDK
    def measure_tilt(self, frame: Frame) -> float: ... # ajuste lineal del borde/línea
    def save(self, profile: "Profile") -> None: ...
    def load(self, profile: "Profile") -> None: ...
```

La **medición de tilt** (ADR-022) ajusta una recta a la posición del borde de la
rendija (o de una línea de absorción) a lo largo del ancho del ROI; la pendiente
es el tilt. La validación exige que la banda quepa con la deriva por tilt:
`altura_ROI >= altura_banda + |tilt_px| + márgenes`. El tilt y la orientación de
cámara se guardan en `session_meta.json` para el post-proceso.

### 3.2 Perfil y configuración (ADR-003)

- **INI** heredado de `nightscribe-scan` (mismas claves) + claves nuevas de ROI y
  de sesión, todas con valor por defecto.
- **Perfil JSON v2** con los datos del telescopio y los **presets de ROI** por
  cámara + óptica:

```jsonc
{
  "version": 2,
  "telescope": { "focal_length": 714, "aperture": 80, "...": "..." },
  "camera":    { "model": "...", "pixel_size": 2, "binning": 1 },
  "roi_presets": [
    { "name": "default", "capture": [0, 0, 3480, 248], "band": [0, 40, 3480, 160] }
  ]
}
```

### 3.3 Registros (ADR-018)

`scan_log.csv`, `scan_stats.jsonl` y `session_meta.json` conservan **las mismas
columnas** que `nightscribe-scan`; se **añaden** (nunca se quitan) columnas para
el ROI y el presupuesto de rendimiento. `session_meta.json` incluye el `RoiModel`
efectivo, la versión de la app y los contadores de frames perdidos.

---

## 4. Flujo de datos y modelo de hilos

Heredado de `simple-astro-cap` (§5.1 de DESIGN.md):

```
hilo de captura: get frame (el backend copia y sella), nada más
   +--> consumidores inline (baratos): DisplayBridge (buzón de 1 frame -> Qt),
   |    auto-exposición, stats del motor SHG
   +--> cola de grabación acotada (presupuesto en MB; desbordes contados)
              |
              v  hilo escritor
        grabador SER
```

- **Nunca** se bloquea el hilo de captura.
- El **DisplayBridge** descarta frames de vídeo si la GUI va lenta; no los
  acumula.
- Los **timestamps** se toman al recibir el frame, no al escribir.
- Los **frames perdidos** se cuentan en los tres sitios: dentro del SDK, por
  desborde de la cola y por huecos de `sequence`.

---

## 5. Observabilidad

- Contadores vivos: fps real, frames escritos, perdidos por SDK, perdidos por
  cola, huecos de secuencia, profundidad máxima de la cola, MB/s de disco.
- Un **panel de salud** en la UI muestra esos contadores en lenguaje llano.
- `scan_stats.jsonl` guarda una muestra por barrido; `session_meta.json` el
  resumen. Los contadores son la materia prima del gate G3 (ADR-013).

---

## 6. i18n y documentación

- Toda cadena visible pasa por `self.tr()`; catálogos `.ts` ES/EN (ADR-016).
- La UI se define en `ui/*.ui`; los widgets personalizados entran por placeholder
  + `replaceWidget`.
- La documentación de usuario va en `solarscribe/docs/`; el diseño interno, en
  `design/`. Los ADRs son bilingües.
