# SolarScribe: contratos entre capas y modelo de datos

Estado: **v1.2** (perfiles con nombre y raíl de cinco pasos). Fecha: 2026-11-06.
Documento de apoyo de [DESIGN.md](../DESIGN.md) y de los ADRs. Describe **cómo se
construye en paralelo**: los contratos que cada agente implementa o consume, y
los datos que viajan entre capas. La versión inglesa llegará cuando el diseño se
estabilice.

Desde v1 los contratos **están escritos** en `solarscribe/devices/abc.py`,
`solarscribe/capture/abc.py`, `solarscribe/shg/abc.py` y
`solarscribe/config/schema.py`: ese código es la firma autoritativa, con sus
unidades y sus porqués en los comentarios. Este documento guarda **el inventario
y las razones** (qué tipo existe, dónde vive y por qué), que es lo que no se puede
deducir del código. Cambiar una firma exige cambiar aquí y pasar por el `lead`
(ADR-012, ADR-023).

**v1.1** cierra la deuda que v1 dejó abierta: la ortografía del INI se cotejó
contra el `CONFIG_SCHEMA` real de `nightscribe-scan` y contra su
`docs/nightscribe-scan.cfg.reference`, y las claves heredadas están ya en
`config/schema.py` con su sección y su default (ADR-024). Además, la lectura y la
escritura dejan de ser una promesa: `config/store.py` y `config/paths.py` existen
con el contrato de §3.2. No cambia ningún tipo de §2.

**v1.2** añade dos contratos que el uso real pidió: los perfiles dejan de ser uno
solo y pasan a ser un almacén de nombres con una selección activa (ADR-027), y el
estado de sesión pasa de cuatro a cinco pasos con la entrada de Focus. Los dos
cambios tienen su migración escrita en §2.4 y §3.2.

> Regla de oro: **ningún contrato implícito**. Si un agente necesita saber qué es
> un tipo o qué promete un método, la firma está en los módulos de contrato y su
> razón está aquí. Si cambia, cambian el módulo, este documento y el ADR
> correspondiente (ADR-012, ADR-023).

---

## 1. Capas y regla de dependencias

```
  ui/   cli/               <- presentación y arranque
    |  \ | /  |
    |   capture/  shg/     <- motores (lógica sin Qt)
    |        \    /
    +-->  devices/   config/   <- hojas: contratos y datos
               |
             SDK / hardware
```

- `ui` y `cli` dependen de `capture` y `shg`, y también de `devices` y `config`:
  el panel de telescopio habla con `Mount` (ADR-019) y el diálogo de ajustes lee el
  esquema. Importar **hacia abajo** siempre es seguro; lo prohibido es importar
  hacia arriba.
- `capture` y `shg` dependen de `devices` y de `config`.
- `capture` y `shg` **no se importan entre sí**: son dos motores hermanos bajo el
  mismo techo. Cuando `shg` necesita el stream o la grabación, declara **puertos**
  propios y la UI los conecta (§2.3).
- `devices` **no** depende de nada de la aplicación (numpy sí).
- `config` es una **hoja de soporte**: importa `devices` (solo el alias `ROI`) y
  nada más de la aplicación (y `platformdirs`, que es externo). Guarda tipos de
  valor y el esquema (`config/schema.py`), la lectura y la escritura
  (`config/store.py`) y la resolución de carpetas por plataforma
  (`config/paths.py`). Así cualquier capa puede leer un ajuste o un perfil sin
  arrastrar un motor ni un driver.
- `shg` no toca Qt ni un driver: consume `Frame` y `FrameStats`, y pide movimiento
  por el contrato `Mount`.
- Qt (`PySide6`) solo entra en `ui`; `ctypes`/`cffi` (la vía a los SDK en C,
  ADR-001) solo en `devices`.
- Los contratos viven en `devices/abc.py`, `capture/abc.py`, `shg/abc.py` y
  `config/schema.py`, como `Protocol`/`dataclass`/`Enum` de Python.

La regla se verifica con `tests/unit/test_layers.py`, que **parsea las fuentes con
`ast`** en vez de importarlas: un SDK o un Qt ausentes no pueden enmascarar una
violación (el import fallaría antes, o la línea ofensiva quedaría detrás de un
`try`), y el árbol dice lo que el código pide de verdad en cualquier plataforma y
en cualquier job de CI. Falla si `devices` o `config` importan de la aplicación,
si `capture` o `shg` importan de `ui`/`cli` o entre sí, si Qt o `ctypes` aparecen
fuera de su capa, o si un módulo de contrato pierde un nombre de su superficie.

---

## 2. Contratos

Los nombres son los del proyecto base `simple-astro-cap` (ADR-008) allí donde ya
existen (`Frame`, `Param`, `ROI`, `CameraInfo`).

Dos reglas que valen para los cuatro módulos (ADR-023):

1. **Tipos de valor frente a comportamiento.** Lo que viaja entre capas
   (`dataclass` congelado, `Enum`) es **concreto**: todos deben coincidir en sus
   campos y en sus unidades. Lo que se comporta (`typing.Protocol`) se declara
   **sin cuerpo** y se implementa en los módulos de la capa. Un módulo de contrato
   no contiene nunca un algoritmo: `validate_roi()` vive en `capture/roi.py` y la
   lectura del INI en `config/store.py`, aunque sus tipos vivan en el contrato.
2. **Códigos de motivo.** Ningún contrato devuelve una frase: devuelve un código
   estable en `snake_case` (`DeviceError.code`, `BackendReason`, `RoiIssue`,
   `reason_code`) y los números que lo justifican. La UI compone la frase con
   `self.tr()` (ADR-016) y nunca muestra un código crudo (ADR-014).

Unidades y coordenadas, fijadas una sola vez para los cuatro módulos:

- RA en **horas** (0 a 24), Dec en **grados**, tasas y offsets en **arcosegundos**
  (por segundo cuando es tasa), tiempos en **segundos**, exposición en
  **microsegundos** (la unidad nativa de los cuatro SDK).
- **Píxeles de sensor**: todo ROI que acepta una cámara (`set_roi`,
  `effective_area`, `RoiConstraints`, `RoiModel.capture`, `RoiPreset.capture`),
  contado desde la esquina superior izquierda del sensor y en píxeles ya bineados.
- **Píxeles de frame**: toda sub-región de un frame entregado (`Frame.cut_roi`,
  `RoiModel.band`, las regiones de análisis de `shg`), contada desde la esquina
  superior izquierda del frame. Mezclarlos es el bug clásico del ROI, así que cada
  firma dice cuál de los dos usa.

### 2.1 `devices` (cámara y montura): `solarscribe/devices/abc.py`

**Tipos de valor**: `ROI` (alias de `(x, y, ancho, alto)`; tupla, como en el
proyecto base), `FrameStats`, `Param` (exposure, gain, offset, bit_depth, binning,
readout, temperature, cooler, con sus unidades fijadas en el módulo),
`ParamRange`, `RoiConstraints`, `CameraCaps`, `CameraInfo`, `Axis`, `MountCaps`,
`MountStatus`, `MountInfo`, `DeviceKind`, `BackendReason`, `BackendInfo` y
`DeviceError`.

**Protocolos**: `Frame`, `Camera`, `Mount` y `DeviceManager`, los cuatro
`runtime_checkable` para que los simuladores y los mocks se comprueben con
`isinstance` (ADR-005).

Lo que se añade al boceto v0, y por qué:

| Miembro | Razón |
| --- | --- |
| `Camera.param_range(p)` | La UI necesita el intervalo aceptado para acotar sus campos y para explicar por qué se rechazó un valor. |
| `Camera.dropped_frames()` | El contador del SDK es uno de los tres sitios donde se cuentan las pérdidas (ADR-013); sin él el panel de salud no puede mostrarlo. |
| `Mount.status()` | El panel de telescopio pinta seguimiento, slew y park en vivo (ADR-019). Va aparte de `position()` para que leerlo siga siendo barato. |
| `RoiConstraints` y `CameraCaps` en `devices` | Son hechos del sensor que el SDK declara. Si vivieran en `capture`, `CameraInfo` no podría llevarlos sin que `devices` importe `capture`. |
| `BackendInfo.reason` (`BackendReason`) más `detail` | La app degrada diciendo qué falta (ADR-014): la UI traduce el código y el registro guarda el detalle técnico. |
| `DeviceError` | Un único tipo de fallo para toda la capa: las capas de arriba capturan una excepción y la traducen una vez. |
| `MountInfo` sin capacidades | La mayoría de los backends solo las conocen tras conectar: vienen de `Mount.capabilities()`. |
| `Frame.cut_roi()` siempre C-contiguo | Una franja a ancho completo es una vista sin copia; cualquier otra sub-región se copia. Un `memoryview` con strides rompe `np.frombuffer`. |

`FrameStats` se queda en **dos números** a propósito: se calcula en línea en el
hilo de captura a 120 fps y el presupuesto (ADR-013) solo paga una media y una
desviación. Lo demás que el motor SHG necesite (la fracción de píxeles brillantes
para el centrado grueso, las columnas del limbo, el ajuste del tilt) lo calcula él
mismo sobre `Frame.data`: la ciencia vive en `shg`, no en el driver.

El descubrimiento (`DeviceManager.backends()/cameras()/mounts()`) habla con los
SDK y puede bloquear un segundo o más: la UI lo llama desde un hilo de trabajo,
nunca desde el hilo de GUI. `open_camera()` y `open_mount()` devuelven el
dispositivo **sin abrir**: decide quien llama.

### 2.2 `capture`: `solarscribe/capture/abc.py`

**Tipos de valor**: `CaptureParams`, `SerColorId`, `SerHeader`, `WriterCounters`,
`StreamCounters`, `RoiIssue`, `Severity`, `RoiWarning` y `RoiModel`.
**Protocolos**: `SerWriter` y `CaptureEngine`.

Implementaciones de la capa: `capture/engine.py` (pipeline, consumidores en línea,
contadores), `capture/ser.py` (SER, ADR-018) y `capture/roi.py` (validación del ROI
y conversión de presets).

Lo que se añade al boceto v0, y por qué:

| Miembro | Razón |
| --- | --- |
| `CaptureEngine.on_frame(cb)` | El DisplayBridge y el motor SHG consumen **frames**, no solo stats (§4). Sin este gancho cada agente habría inventado el suyo. |
| `CaptureEngine.counters()` (`StreamCounters`) | El panel de salud y la barra de estado (fps, pérdidas por SDK, huecos de secuencia, MB/s) son la materia del gate G3 (ADR-013). |
| `CaptureEngine.is_running()` e `is_recording()` | La UI habilita y deshabilita acciones según el estado; preguntar no debe costar una excepción. |
| `configure()` se puede llamar en marcha | Es lo que hace posible el editor de ROI en vivo (ADR-010): reinicia el stream con el ROI nuevo y, si estaba grabando, cierra la grabación limpiamente antes (ADR-014). |
| `WriterCounters` y `StreamCounters` como `dataclass` | Son valores que cruzan la capa: la UI, los registros y los tests leen los mismos campos. |

**El hogar del `RoiModel`** (decisión de ADR-023): vive en `capture/abc.py`.

- `devices` debe quedarse sin conceptos de la aplicación, y una banda espectral o
  un tilt son conceptos del SHG.
- `shg` es hermano de `capture`: ponerlo allí obligaría a `capture` a importar
  `shg`.
- `config` solo persiste los dos rectángulos que el usuario edita, como
  `RoiPreset`, sin límites del SDK ni tilt.

`capture` es además el dueño del ROI de captura (AGENTS.md), así que el modelo y su
validación caen del mismo lado. Consecuencias prácticas:

- `RoiModel` es un `dataclass` **de datos**: `capture`, `band`, `constraints`,
  `binning`, `tilt_deg` y `tilt_px`, más `output()` (que devuelve `capture`, la
  región 4 de ADR-010) y `set_tilt(tilt_deg, tilt_px)`.
- La validación es `capture/roi.py: validate_roi(model, *, fps=None) ->
  list[RoiWarning]`, con los chequeos de ADR-010 mapeados a códigos `RoiIssue`:
  `BAND_CLIPPED`, `TILT_HEIGHT`, `SDK_MULTIPLE`, `SDK_BOUNDS`,
  `BINNING_MISMATCH`, `LOW_RATE` y `SLIT_OFF_CENTRE`. `Severity.ERROR` significa
  que el ROI no se puede barrer; `WARNING` e `INFO` son recomendaciones, nunca
  puertas (ADR-011).
- La conversión con el perfil es `capture/roi.py: preset_to_model(preset,
  constraints)` y `model_to_preset(model, name)`: `capture` sí puede importar
  `config`, y `config` no puede importar `capture`.
- Las sub-regiones de análisis **no** están en el modelo: se calculan, no se
  guardan (ADR-010), y las calcula `shg` desde `capture` y `band`, porque es quien
  conoce su propia geometría de medida.

**Pendiente de `video`**: cómo viajan los timestamps por frame dentro del SER.
`SerHeader` fija los campos estándar (ancho, alto, profundidad de bits, color ID,
endianess) y lleva el `roi` como metadato que el escritor registra en
`session_meta.json`, porque el formato SER no tiene campo de ROI. Los campos
estándar no cambian de forma (ADR-018).

### 2.3 `shg`: `solarscribe/shg/abc.py`

**Tipos de valor**: `ScanMode`, `DecCenterMethod`, `PreparePhase`, `ScanState`,
`ScanStatus`, `ScanRow`, `ScanConfig`, `ScanPlan`, `PrepareStatus`,
`PrepareResult`, `ScanProgress`, `ScanResult` y `TiltResult`. **Protocolos**:
`FrameSource`, `RowRecorder`, `ScanEngine` y `TiltMeter`.

**Puertos (inversión de dependencias).** `shg` no importa `capture`, así que
declara lo que necesita y la UI lo conecta:

- `FrameSource.on_frame(cb)`: de dónde salen los frames vivos. `CaptureEngine` lo
  cumple **estructuralmente**, porque ambos declaran el mismo método.
- `RowRecorder.start_row(path)` y `stop_row() -> RowCounters`: dónde se graba cada
  fila del mosaico y con qué contabilidad. `RowCounters` es el tipo de valor propio
  de `shg` (escritos, perdidos por cola, perdidos por SDK, huecos de secuencia y
  profundidad máxima de la cola), para que `shg` pueda escribir los tres registros
  de ADR-018 sin importar `capture`. La UI pasa un adaptador de unas líneas sobre
  `start_recording()`, `stop_recording()` y `counters()`. Las rutas las da
  `config/store.py` (§3.2), no la interfaz.

**Construcción** (forma parte del contrato): `shg/engine.py` expone
`ScanEngineImpl(mount: Mount, frames: FrameSource)`, que la UI construye una vez
por sesión.

Lo que se añade o se fija respecto al boceto v0:

| Miembro | Razón |
| --- | --- |
| `run(plan, cb, recorder=None)` | Un mosaico escribe **un SER por fila**; sin el puerto la UI tendría que interleavar grabaciones con el barrido en marcha. `None` es el modo seco (DESIGN.md §14). |
| `pause()` y `resume()` | Si el Sol se sale de la rendija el barrido **se pausa y avisa**, y se puede recentrar antes de continuar (DESIGN.md §7). |
| `run()` ejecuta **un ciclo** | Los `config.cycles` (3 por defecto) los repite la UI, que puede recentrar entre ciclo y ciclo. |
| `ScanConfig` lleva `capture`, `band`, `analysis` y el tilt como datos sueltos | `shg` no puede importar `RoiModel`: la UI copia los rectángulos al construir la configuración. |
| Claves reservadas de `analysis`: `"left"`, `"right"`, `"limb"` | `"left"` y `"right"` son las mitades del centrado en Dec (ADR-006) y `"limb"` la franja donde se detecta el limbo. `shg` subdivide `"limb"` en columnas internamente: las columnas no son contrato. |
| `TiltMeter` y `TiltResult` en `shg` | La medición del tilt es ciencia de `shg` (ADR-022). El paso ROI la llama y escribe los números en el `RoiModel` de `capture`, así que la matemática y el modelo se quedan cada uno en su capa. |
| `ScanRow` con `ra_start_hours` y `ra_end_hours` | El barrido se mueve por **tasa** (`move_axis`), no por slew: los límites de AR son la geometría prevista para el overlay y el registro, y el final lo decide la parada adaptativa. |

**Códigos de motivo del MVP**: `no_limb`, `sun_lost`, `calibration_failed`,
`mount_no_rate`, `disk_full`, `device_lost`, `stalled`, `aborted`, `no_edge`,
`low_contrast`.

**Contratos que `shg` debe formalizar en `shg/abc.py` antes de que `ux` implemente
los pasos 1 y 2** (la forma es obligatoria, la ciencia es suya):

1. `analysis_regions(capture: ROI, band: ROI) -> dict[str, ROI]`, que devuelve las
   regiones con las claves reservadas. La llama la UI para dibujarlas y para
   construir `ScanConfig`.
2. El servicio de **centrado del Sol** del paso *Buscar el Sol* (grueso por
   histograma y extensión, fino por simetría o cuerda, ADR-006): un `Protocol` con
   progreso por callback y un resultado con `dec_offset_arcsec`, el método usado y
   `reason_code`.
3. El **asistente de alineación polar** (ADR-007): muestreo, ajuste de la recta de
   deriva y error de azimut y altitud, con su progreso por callback y su segunda
   medida de confirmación.

Reglas de forma para los tres: `Protocol` más `dataclass`, sin Qt, sin drivers, las
unidades de §2 y códigos de motivo en vez de frases.

### 2.4 Estado de sesión: `solarscribe/config/schema.py`

El estado de los cinco pasos **no vive en `ui`** (decisión de ADR-023): vive en
`config/schema.py`, junto al esquema.

- Es **persistencia**: `SessionState` se guarda y se carga de un fichero, y eso es
  territorio de `config` (ADR-003).
- `config` es una hoja, así que lo pueden leer `ui`, `cli`, `capture` y `shg`. Si
  el estado viviera en `ui`, la CLI no podría reabrir una sesión sin importar la
  GUI.
- La UI **pinta** el estado y delega; no lo define.

**Tipos**: `StepStatus` (`PENDING`, `CURRENT`, `DONE`, `SKIPPED`), `SESSION_STEPS`
(`find_sun`, `polar`, `focus`, `roi`, `scan`, en el orden del raíl), `StepState`
(`status`, `updated_at`, `metrics`) y `SessionState` (`steps`, `session_dir`,
`created_at`, `updated_at`).

- El fichero es `session_state.json` **dentro de la carpeta de la sesión**, y no es
  `session_meta.json`: ese es el contrato con el post-proceso (ADR-018) y sus
  columnas no cambian de forma.
- `StepState.metrics` guarda **solo números**, con claves estables (`tilt_deg`,
  `rate_arcsec_s`, `dec_error_arcsec`...). La frase la compone la UI con
  `self.tr()` alrededor de esos números (ADR-016): una frase guardada en un fichero
  no se puede traducir después, y un número sin su etiqueta no le dice nada al
  observador.
- `save_session_state(state, path)` y `load_session_state(path)` se implementan en
  `config/store.py`, con el autoguardado silencioso tras cada cambio de estado
  (ADR-011).

**Migración a cinco pasos (Focus).** ADR-011 describía cuatro pasos; el raíl actual
tiene cinco porque el enfoque (los tres focusers y la alineación rendija-Dec,
DESIGN.md §9.2) se separó del ROI; el cambio lo concreta ADR-028. Los nombres son
estables y este es el orden:
`find_sun`, `polar`, `focus`, `roi`, `scan`. Consecuencias, ya implementadas:

- `load_session_state()` parte de `new_steps()`, es decir, de los cinco pasos. Un
  `session_state.json` guardado con cuatro pasos carga con `focus` en `PENDING`;
  los otros cuatro conservan su estado y sus métricas.
- `save_session_state()` escribe los cinco en el orden del raíl y descarta
  cualquier paso que no esté en `SESSION_STEPS`, así que el fichero tiene una sola
  forma canónica.
- La UI pinta el raíl recorriendo `SESSION_STEPS`, no una lista propia: añadir un
  paso es cambiar esa tupla y la migración de arriba, no dos sitios.

La UI **no** contiene lógica de negocio: escucha `CaptureEngine` y `ScanEngine`,
pinta el estado de `SessionState` y delega. La regla de `self.tr()` (ADR-016) aplica
a toda cadena visible.

---

## 3. Modelo de datos

### 3.1 ROI y tilt (ADR-010, ADR-022)

Las cuatro regiones de ADR-010 se reparten así:

| Región | Dónde vive | Coordenadas |
| --- | --- | --- |
| ROI de captura (sensor) | `RoiModel.capture`, `RoiPreset.capture`, claves `[roi] capture_*` | píxeles de sensor, bineados |
| Banda/orden espectral | `RoiModel.band`, `RoiPreset.band`, claves `[roi] band_*` | píxeles de frame |
| ROI de análisis (software) | las calcula `shg` y viajan en `ScanConfig.analysis` | píxeles de frame |
| ROI de salida (SER) | `RoiModel.output()`, que devuelve `capture` | píxeles de sensor |

El modelo (solo datos, en `capture/abc.py`):

```python
@dataclass
class RoiModel:
    capture: ROI                 # lo elige el usuario; fija el FPS y el SER
    band: ROI                    # debe caber en capture o se recorta el orden
    constraints: RoiConstraints  # límites del sensor y del SDK (viven en devices)
    binning: int = 1             # a qué binning se refieren los rectángulos
    tilt_deg: float = 0.0        # tilt medido por shg (ADR-022)
    tilt_px: float = 0.0         # su deriva a lo ancho del ROI, en píxeles
```

La **medición de tilt** (ADR-022) la hace `shg`
(`TiltMeter.measure(frame, band) -> TiltResult`): ajusta una recta a la posición del
borde de la rendija (o de una línea de absorción) a lo largo del ancho del ROI; la
pendiente es el tilt, en grados y en píxeles de deriva. `TiltResult.edge_std_px` es
la rectitud del borde (el `edge_flat` del prototipo): si es grande, el borde no es
una recta y la cifra de tilt no es de fiar, así que la UI lo dice en vez de mostrar
un número.

El paso ROI llama a `shg` y guarda los números con `RoiModel.set_tilt()`. La
validación exige que la banda quepa con la deriva por tilt:
`altura_ROI >= altura_banda + |tilt_px| + márgenes`. El tilt y la orientación de
cámara se guardan en `session_meta.json` para el post-proceso, y el último valor
medido queda en el INI como pista para la sesión siguiente.

### 3.2 Perfil y configuración (ADR-003, ADR-024): `solarscribe/config/`

Tres módulos y una frontera clara:

- `config/schema.py`: la **tabla** de claves (`SCHEMA`, una tupla de `Key`) y los
  **tipos de valor** (`Profile`, `TelescopeData`, `CameraData`, `RoiPreset`,
  `SessionState`, `StepState`, `StepStatus`, `SESSION_STEPS`) más los nombres de
  fichero (`CONFIG_FILE`, `PROFILE_FILE`, `PROFILES_FILE`, `SESSION_STATE_FILE`,
  `SCAN_LOG_FILE`, `SCAN_STATS_FILE`, `SESSION_META_FILE`) y las versiones de
  formato (`PROFILE_VERSION`, `PROFILES_VERSION`).
- `config/store.py`: la **lectura y la escritura** (`Settings`, `ProfileStore`,
  `Profile`, `SessionState`) y el **nombre de cada sesión y de cada barrido**. Es
  un algoritmo y por eso no vive en el módulo de contrato (ADR-023).
- `config/paths.py`: las **carpetas por plataforma** con `platformdirs`.

Ninguna capa de arriba decide una ruta: pide `paths.settings_path()`,
`paths.profile_path()`, `paths.default_session_base()` o las funciones de
`store.py`. Y este módulo fija **nombres de fichero, nunca carpetas**: dónde
viven es cosa de la aplicación y del empaquetado (ADR-004, ADR-017).

**INI heredado.** Las secciones `[optics]`, `[scan]`, `[fps]`, `[limb]`, `[dec]`,
`[mosaic]`, `[exposure]`, `[calibration]` y `[logging]` son las de
`nightscribe-scan`, con su **ortografía, sección y default exactos**: 66 claves.
El contenido de un `nightscribe-scan.cfg` existente se reconoce sin cambios; se
copia al `config.ini` de SolarScribe, porque la ubicación del fichero es la de la
plataforma, no la del script. La reconciliación contra el prototipo la resolvió
ADR-024, con una sola excepción de default: `scan.num_cycles` vale 3 porque
DESIGN.md §6 y §7 piden tres ciclos por sesión, y el ADR lo deja escrito. Las
claves nuevas de SolarScribe (ROI, montura, sesión, polar, límites de captura,
observatorio, cámara y espectro) se **añaden** con `origin="new"`; nunca se
renombra una heredada.

`[spectrum]` es el contrato de la identificación nativa de líneas
(`shg/spectrum.py`): la línea objetivo a la que está sintonizada la red, la
dispersión en angstroms por píxel, el sentido de la dispersión, la tolerancia de
emparejamiento, la confianza mínima y la ventana de refinado del ancla. Con
`dispersion_angstrom_px = 0` la identificación se desactiva: sin escala, una
distancia en píxeles no es una longitud de onda.

**Una verdad por comportamiento (ADR-024).** Antes de la reconciliación el
esquema tenía claves propias que repetían una heredada. Se conservan como
**alias heredados** en `LEGACY_KEYS`, con el nombre heredado como canónico:

| Nombre SolarScribe | Nombre canónico heredado |
| --- | --- |
| `scan.cycles` | `scan.num_cycles` |
| `scan.padding_s` | `scan.padded_duration` |
| `scan.preload_s` | `scan.scan_preload_seconds` |
| `scan.adaptive_stop` | `scan.trailing_limb_stop` |
| `capture.stall_timeout_s` | `fps.capture_stall_seconds` |
| `capture.min_free_disk_gb` | `fps.capture_min_free_gb` |
| `camera.auto_exposure` | `scan.enable_auto_exp` |

Reglas, para que no haya dos verdades en un fichero:

- `load_settings()` lee el alias **solo** cuando el canónico no está en el
  fichero, y después refleja el valor resuelto en los dos nombres, así que un
  consumidor antiguo sigue leyendo la verdad.
- `save_settings()` escribe **solo** el nombre canónico: tras guardar, el
  fichero no contiene dos claves que signifiquen lo mismo.
- `keys_of(section)` oculta los alias por defecto; el diálogo de ajustes muestra
  un control por comportamiento. `keys_of(section, include_legacy=True)` los
  devuelve para una herramienta de migración.

Se **retiraron** tres claves que duplicaban un control sin poder ser alias
porque su tipo o su significado no coincidía: `general.dry_run` (es
`scan.enable_capture = false`), `scan.mode` (es `scan.enable_mosaic`) y
`camera.auto_exposure_target` (el bloque heredado `[exposure]` manda el
percentil, no la media). No había código consumiéndolas.

**Lectura tolerante (ADR-003).**

- Falta el fichero, falta una clave o el número no se puede leer: **default del
  esquema**. La app siempre arranca.
- Codificación: UTF-8 y, si falla, Latin-1, como el prototipo; un acento perdido
  en un comentario no invalida el fichero.
- Comentarios `#` y `;`; separador `=` o `:`; secciones y claves sin distinguir
  mayúsculas.
- Booleanos con vocabulario **fijo**: `1`, `true`, `yes`, `on` y sus negativos.
  Cualquier otra palabra deja el default; no se adivina.
- Una clave que no está en el esquema no rompe nada, pero se devuelve en
  `Settings.unknown`, para que el diálogo de ajustes avise de la errata en vez de
  ignorarla en silencio.
- `Settings` es un `dataclass` **completo** (una entrada por clave) que devuelve
  `load_settings()`; `Settings.get(section, name)` lanza `KeyError` ante una
  clave fuera del esquema, igual que `default_value()`, para que una errata no se
  lea como un cero.

**INI frente a perfil: quién manda.** El **INI es la verdad de la sesión**; cada
perfil del almacén es una **instantánea con nombre** del instrumento y sus presets
de ROI. Seleccionar un perfil en Ajustes escribe sus datos en el INI; no hay una
fusión automática ni dos fuentes que puedan discrepar. Es lo que hacía el panel
del prototipo: elegir un perfil copiaba su configuración al formulario. Por eso
los datos físicos (`optics.focal_length`, `optics.pixel_size`,
`mosaic.mosaic_slit_length_mm`) y los del perfil (`TelescopeData`,
`CameraData`) tienen los mismos defaults: mientras no se aplique un perfil, el
INI manda y no cambia nada.

**Perfil JSON v2**: cada perfil del almacén tiene los datos del telescopio y los
**presets de ROI** por cámara + óptica, como `dataclass` (`Profile`,
`TelescopeData`, `CameraData`, `RoiPreset`):

```jsonc
{
  "version": 2,
  "telescope": { "focal_length_mm": 714, "aperture_mm": 80, "slit_length_mm": 7 },
  "camera":    { "model": "...", "pixel_size_um": 2, "binning": 1 },
  "roi_presets": [
    { "name": "default", "capture": [0, 0, 3480, 248], "band": [0, 40, 3480, 160] }
  ]
}
```

La cifra de la rendija es su **longitud**, y la geometría dice por qué es esa: 7 mm
a 714 mm de focal subtienden `7/714 rad = 33.7'`, justo por encima del diámetro solar
(unos 32'), así que una sola fila del barrido puede cubrir todo el disco. El
**ancho** de la rendija (la resolución espectral) no se guarda: la captura no lo
necesita e inventar una cifra sería peor que omitirla.

`load_profile()` (un solo fichero, legado o exportado) es **tolerante** y migra lo
que encuentra:

- v2 escrito a mano: números como texto, una sección ausente, una clave
  desconocida o un preset en forma de mapa nombre -> rectángulos se aceptan; lo
  que no se puede leer cae a su default.
- v1 de `nightscribe-scan` (`{version: 1, profiles: {...}}` con `meta` y
  `config`, o un `config` plano): se traducen `FOCAL_LENGTH`, `PIXEL_SIZE`,
  `MOSAIC_SLIT_LENGTH_MM` y `meta.camera`/`meta.aperture_mm`, que son los datos
  del instrumento. El resto de claves v1 pertenece al INI y allí sigue.
- JSON truncado o un fichero ausente: defaults, para que el siguiente guardado
  lo reescriba.
- Al guardar se pierden las claves que esta versión no conoce: un fichero de una
  versión futura lo debe guardar la versión futura.

**Perfiles con nombre (ADR-027).** El perfil único se queda corto en cuanto el
observador tiene dos montajes o dos presets de ROI: tiene que elegir uno al
arrancar y verlo por su nombre. El almacén es **un solo `profiles.json`** con
todos los nombres y la selección activa, en la carpeta de configuración
(`paths.profiles_path()`):

```jsonc
{
  "version": 2,
  "active": "SHG-700",
  "profiles": {
    "SHG-700": {
      "version": 2,
      "telescope": { "focal_length_mm": 714, "aperture_mm": 80, "slit_length_mm": 7 },
      "camera":    { "model": "...", "pixel_size_um": 2, "binning": 1 },
      "roi_presets": [
        { "name": "default", "capture": [0, 0, 3480, 248], "band": [0, 40, 3480, 160] }
      ]
    },
    "SHG-700 wide": { "version": 2, "telescope": { "...": "..." } }
  }
}
```

Por qué **un fichero y no uno por perfil**: el arranque necesita la lista y la
selección activa en una sola lectura; con un fichero por perfil harían falta un
barrido de carpeta y un marcador aparte para el activo, y renombrar o borrar
serían dos escrituras que un cierre a medias puede dejar a medias. Con un solo
fichero, cada operación es un `os.replace` atómico. Es además la forma de
`nightscribe-scan`, así que un `nightscribe-profiles.json` se migra tal cual. El
coste aceptado: dos instancias de la app escribiendo a la vez se pisan; es una
aplicación de escritorio de un solo usuario, igual que el prototipo.

Cada bloque de perfil es un documento `Profile` v2 completo, así que se puede
exportar a un `profile.json` suelto sin conversión. La API es explícita y pura: las
operaciones devuelven un `ProfileStore` nuevo y solo `save_profiles()` toca el
disco.

```python
load_profiles(path, *, legacy_path=None) -> ProfileStore
save_profiles(store, path) -> None
profile_names(store) -> tuple[str, ...]          # en el orden del fichero
active_profile(store) -> Profile | None          # None si el activo no existe
set_active_profile(store, name) -> ProfileStore  # KeyError si no existe
save_named_profile(store, name, profile, *, make_active=False) -> ProfileStore
rename_profile(store, old, new) -> ProfileStore  # KeyError / ValueError
delete_profile(store, name) -> ProfileStore      # KeyError si no existe
```

Reglas de lectura y migración:

- **Sin `profiles.json`**: se migra el antiguo `profile.json` de la misma
  carpeta (o el que diga `legacy_path`) como perfil `"default"`, activo, y se
  devuelve. La lectura no escribe: el primer `save_profiles()` lo persiste y el
  fichero antiguo no se toca.
- **Con `profiles.json`**: es la verdad; el `profile.json` antiguo se ignora.
- **`nightscribe-profiles.json` v1**: se aceptan todos los nombres y el `active`;
  cada bloque v1 se traduce con las mismas reglas de `load_profile()`.
- **Fichero truncado**: se intenta el `profile.json` antiguo y, si no hay, el
  perfil por defecto; nunca se arranca sin perfil.
- **Instalación nueva**: un perfil `"default"` activo, para que la UI siempre
  tenga algo visible que cargar.
- **`active` desconocido** (errata a mano): el nombre se conserva y
  `active_profile()` devuelve `None`; no se activa otro instrumento en silencio.
  La UI avisa y pide elegir.
- **Borrar el activo**: deja `active=""`; no se elige otro perfil por su cuenta.
  Borrar el último deja un almacén vacío, y un fichero explícitamente vacío no
  resucita el perfil por defecto (solo la ausencia de fichero lo hace).

`save_settings()`, `save_profile()`, `save_profiles()` y `save_session_state()`
escriben a un temporal en la misma carpeta y lo mueven sobre el destino
(`os.replace`), de modo que un cierre a mitad de escritura deja el fichero bueno
anterior, no medio fichero.

**Carpetas y nombres de sesión (DESIGN.md §10).** `config/paths.py` resuelve:

- `config_dir()`: `%LOCALAPPDATA%\SolarScribe` en Windows;
  `$XDG_CONFIG_HOME/SolarScribe` (o `~/.config/SolarScribe`) en Linux; ahí viven
  `config.ini`, `profiles.json` y el antiguo `profile.json`.
- `profiles_path()`: `config_dir()/profiles.json`, el almacén que se carga al
  arrancar (ADR-027); `profile_path()` sigue apuntando al perfil único, legado o
  exportado.
- `data_dir()`: `%LOCALAPPDATA%\SolarScribe` en Windows;
  `$XDG_DATA_HOME/SolarScribe` (o `~/.local/share/SolarScribe`) en Linux.
- `log_dir()`: la carpeta de logs de la plataforma (XDG state en Linux,
  `%LOCALAPPDATA%\SolarScribe\Logs` en Windows); el visor de logs la lee
  (DESIGN.md §11).
- `default_session_base()`: `data_dir()/sessions`, el valor que se usa cuando
  `[session] session_dir` está vacío.
- Las funciones solo **resuelven** rutas; no crean carpetas. `store.py` crea la
  carpeta padre cuando de verdad escribe, y solo la carpeta de sesión cuando
  empieza la sesión.
- Nada se escribe junto al ejecutable: en Windows `Program Files` es de solo
  lectura y en Linux `/usr` también (ADR-004).

`config/store.py` es el **único dueño** de los nombres de sesión, para que
ninguna capa los invente (DESIGN.md §10):

- `session_folder(base_dir, when) -> Path`: crea y devuelve la carpeta de la
  sesión, nombrada `YYYYMMDD_HHMM` con la hora local. Dos sesiones en el mismo
  minuto no comparten carpeta: la segunda recibe `_2`, `_3`...
- `scan_ser_path(session_dir, base_name, when, scan) -> Path`: el fichero
  `sun_YYYYMMDD_HHMM_scanNN.ser` de un barrido concreto. `NN` va a dos dígitos
  para que los ficheros ordenen; `scan` empieza en 1 y un 0 lanza `ValueError`.
- `scan_log_path(session_dir, configured)`, `scan_stats_path(...)` y
  `session_meta_path(...)`: los tres registros de ADR-018. `configured` es el
  valor de su clave `[logging]`; vacío significa la carpeta de la sesión, y una
  ruta relativa se resuelve contra ella (no contra el directorio de trabajo, que
  cambia según cómo se arranque la app).
- `session_state_path(session_dir)`: el `session_state.json`, siempre en la
  carpeta de la sesión; no se configura.

Los tres registros de ADR-018 son **uno por sesión**, como en el prototipo; el
SER es **uno por barrido**, como pide el mosaico. Las claves heredadas
`[logging]` pueden sustituir la ruta de los registros; vacías significan la
carpeta de la sesión, que es donde el post-proceso los busca.

La UI llama a estas funciones al abrir la sesión y el adaptador de `RowRecorder`
usa `scan_ser_path()` para la ruta de cada fila: nombrar ficheros es persistencia,
no lógica de negocio de la interfaz.

### 3.3 Registros (ADR-018)

`scan_log.csv`, `scan_stats.jsonl` y `session_meta.json` conservan **las mismas
columnas** que `nightscribe-scan`; se **añaden** (nunca se quitan) columnas para
el ROI y el presupuesto de rendimiento. `session_meta.json` incluye el `RoiModel`
efectivo, la versión de la app y los contadores de frames perdidos.

Son **tres ficheros por sesión**, como en el prototipo, no uno por barrido: el
SER es el que se repite por fila del mosaico (`scanNN`). La ruta la decide
`config/store.py` (§3.2): la carpeta de la sesión, salvo que las claves heredadas
`[logging]` digan otra cosa. Una ruta configurada absoluta se usa tal cual; una
relativa se resuelve contra la carpeta de la sesión.

La materia prima de esos registros son los tipos de valor ya fijados:
`WriterCounters` y `StreamCounters` (captura) y `ScanResult` (shg).

**Los tres ficheros los escribe `shg`**, que es de donde los porta el prototipo
(DESIGN.md §7), y con lo que ya recibe por contrato, sin importar `capture`:

- el ROI, la banda y el tilt, por `ScanConfig`;
- la contabilidad de cada fila (escritos, perdidos por cola y por SDK, huecos de
  secuencia y profundidad máxima de la cola), por `RowRecorder.stop_row()`, que
  devuelve el `RowCounters` que `shg` declara y el adaptador de la UI rellena desde
  `WriterCounters` y `StreamCounters`;
- el plan, la tasa y el resultado, por `ScanPlan` y `ScanResult`;
- la versión de la app, del paquete raíz (`solarscribe.__version__`, que no es una
  capa).

Así los tres registros los escribe una sola capa y con datos que ya le llegan por
contrato: la interfaz no escribe ficheros de registro ni inventa columnas. Las
columnas nuevas se anuncian en el CHANGELOG y en ADR-018.

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
- Los consumidores en línea se registran con `CaptureEngine.on_frame(cb)` y
  `on_stats(cb)`: se les llama **en el hilo de captura** y su presupuesto es el
  intervalo de frame (8,3 ms a 120 fps, ADR-013). Lo que no quepa ahí va a un hilo
  propio.
- El **DisplayBridge** vive en `ui` (toca Qt) y es un buzón del último fotograma:
  una GUI lenta descarta fotogramas de vídeo, no los acumula. Recibe los frames por
  `on_frame`.
- El motor `shg` recibe los frames por su **puerto** `FrameSource`, que
  `CaptureEngine` cumple estructuralmente (§2.3): los dos motores no se importan.
- Los **timestamps** se toman al recibir el frame, no al escribir.
- Los **frames perdidos** se cuentan en los tres sitios: dentro del SDK
  (`Camera.dropped_frames()`), por desborde de la cola
  (`WriterCounters.frames_dropped_queue`) y por huecos de `sequence`
  (`StreamCounters.sequence_gaps`).

---

## 5. Observabilidad

- Contadores vivos: fps real, frames escritos, perdidos por SDK, perdidos por
  cola, huecos de secuencia, profundidad máxima de la cola, MB/s de disco.
- Salen de dos tipos y de ninguno más: `CaptureEngine.counters() ->
  StreamCounters` (fps, pérdidas del SDK, huecos, MB/s) y
  `CaptureEngine.stop_recording() -> WriterCounters` (escritos, pérdidas por cola,
  profundidad máxima). El panel de salud y la barra de estado los leen de ahí.
- Un **panel de salud** en la UI muestra esos contadores en lenguaje llano: cada
  cifra dice qué significa y contra qué presupuesto se compara (ADR-013).
- `scan_stats.jsonl` guarda una muestra por barrido; `session_meta.json` el
  resumen. Los contadores son la materia prima del gate G3 (ADR-013).

---

## 6. i18n y documentación

- Toda cadena visible pasa por `self.tr()`; catálogos `.ts` ES/EN (ADR-016).
- La UI se define en `ui/*.ui`; los widgets personalizados entran por placeholder
  + `replaceWidget`.
- La documentación de usuario va en `solarscribe/docs/`; el diseño interno, en
  `design/`. Los ADRs son bilingües.
