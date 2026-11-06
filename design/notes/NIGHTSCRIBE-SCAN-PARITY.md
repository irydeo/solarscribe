# Paridad funcional con nightscribe-scan

Nota de trabajo interna (no se publica). Fecha: 2026-11-06.
Fuente: `https://github.com/irydeo/nightscribe-scan` (clon de referencia en
`/tmp/opencode/nightscribe-scan` durante el desarrollo). Cubre el README, la guía
de usuario, la referencia de configuración y el mapa de funciones del script.

Objetivo: **toda funcionalidad de `nightscribe-scan` ha de estar cubierta** por
SolarScribe, salvo el post-proceso (SolarScribe solo captura) y el motor de
captura de SharpCap (SolarScribe trae el suyo). Esta tabla es la lista de
comprobación que cada agente usa para no dejar nada fuera.

## 1. Funcionalidades

| # | Funcionalidad (nightscribe-scan) | Referencia | Dueño en SolarScribe | Dónde vive |
| --- | --- | --- | --- | --- |
| 1 | Autocalibración de la tasa de barrido por el tiempo de cruce del limbo | `calibrate_scan_rate`, README | shg | `shg/calibration.py` |
| 2 | Diámetro solar por efeméride (local, sin red) y UTC de cada barrido | `ephemeris_solar_diameter`, ADR-021 | shg | `shg/ephemeris.py` |
| 3 | Escala del eje de la rendija medida en vivo, paso del mosaico | `measure_slit_scale` | shg | `shg/geometry.py` |
| 4 | Vigilancia del barrido: espera abortable, detección de stall, guarda de disco, contabilidad de frames, un reintento | `check_abort`, `_sleep_abortable`, `scan_with_retry` | video + shg | `capture/engine.py`, `shg/engine.py` |
| 5 | Comprobaciones de consistencia entre barridos (tasa y extensión de rendija) | `_check_consistency` | shg | `shg/engine.py` |
| 6 | Registros `scan_log.csv`, `scan_stats.jsonl`, `session_meta.json` | `write_scan_log`, `write_scan_stats`, `write_session_meta` | shg | `shg/logs.py` |
| 7 | Panel de control con perfiles, configuración y start/stop | `run_ui_server`, `_load_profiles` | ux | `ui/` |
| 8 | Ayuda al enfoque (`nightscribe-focus.py`) | guía §10 | ux | `ui/` |
| 9 | Barrido simple y mosaico multífila con centrado en Dec por cuerdas | `run_sequence`, `run_mosaic` | shg | `shg/engine.py` |
| 10 | Bucle de autoexposición | `auto_exposure` | video | `capture/auto_exposure.py` |
| 11 | Centrado en Dec: bucle izquierda/derecha y método de la cuerda | `center_dec`, `center_dec_chord`, ADR-006 | shg | `shg/centering.py` |
| 12 | Geometría del mosaico: longitud de rendija, magnificación, solape, margen, barridos por fila, backlash | `compute_mosaic_plan` | shg | `shg/mosaic.py` |
| 13 | Precarga de AR (backlash), parada adaptativa del limbo de salida, padding | `rewind_before_disk`, `trailing_limb_stop` | shg | `shg/engine.py` |
| 14 | Corrección de la tasa de AR por 1/cos(Dec) | `cos_dec_correction` | shg | `shg/geometry.py` |
| 15 | Detección del limbo por desviación típica | `find_solar_limb` | shg | `shg/limb.py` |
| 16 | Medida de extensión de rendija y de medias izquierda/derecha | `measure_slit_extent_px`, `measure_left_right_means` | shg | `shg/analysis.py` |
| 17 | Perfiles (persistencia de ajustes y presets) | `_load_profiles`, `PROFILES` | lead | `config/store.py` |
| 18 | ROI de captura | (lo fija el usuario en SharpCap) | video | `capture/roi.py`, editor en `ui/` |
| 19 | Medición de tilt (nuevo en SolarScribe) | ADR-022 | shg | `shg/tilt.py` |
| 20 | Alineación polar solar (nuevo en SolarScribe) | ADR-007 | shg | `shg/polar.py` |
| 21 | Buscar el Sol: GOTO por efeméride y centrado grueso por histograma | `measure_percentile_pixel`, ADR-006 | shg + ux | `shg/centering.py`, `ui/` |
| 22 | Motor de captura y grabador SER | (SharpCap) | video | `capture/engine.py`, `capture/ser.py` |

**Fuera de alcance (por diseño)**: los dos post-procesos
(`tools/align_stack_recon.py`, `tools/mosaic_from_recon.py`) y el apilado/stitch.
SolarScribe deja SER + registros y el post-proceso es externo (ADR-018). El
contrato de logs debe seguir alimentando esas herramientas: mismas columnas,
nunca menos.

## 2. Reconciliación de configuración (ADR-003, ADR-024)

Estado: **reconciliada** el 2026-11-06 contra el clon real de referencia
(`CONFIG_SCHEMA` y `CONFIG_DEFAULTS` de `nightscribe-scan.py`, y
`docs/nightscribe-scan.cfg.reference`). Resultado: **66 claves heredadas** en
`config/schema.py`, con la sección, la ortografía y el default del prototipo. La
tabla exacta y su prueba están en `tests/unit/test_config_store.py` (constante
`INHERITED`); la decisión y sus alternativas, en ADR-024.

El prototipo lee sus claves como `constante.lower()` dentro de su sección: la
sección solo organiza, el nombre es el de la constante en minúsculas. SolarScribe
hace lo mismo, así que una clave heredada se coteja por pareja
`(sección, nombre)`.

### 2.1 Heredadas que coinciden (66)

| Sección | Claves | Defaults que importan |
| --- | --- | --- |
| `[optics]` | 6 | `focal_length=714`, `pixel_size=2`, `sidereal=15.04`, `solar_diameter=1920` |
| `[scan]` | 10 | `enable_capture=true`, `padded_arcsec=100`, `scan_preload_seconds=0.3`, `trailing_limb_stop=true` |
| `[fps]` | 9 | `capture_fps=0` (medir), `capture_stall_seconds=3`, `capture_min_free_gb=1` |
| `[limb]` | 6 | `limb_stddev_min=500`, `on_disk_stddev=2000`, `limb_dark_mult=5` |
| `[dec]` | 7 | `enable_dec_centering=true`, `dec_center_tolerance=0.03` |
| `[mosaic]` | 13 | `enable_mosaic=false`, `mosaic_slit_length_mm=7`, `mosaic_overlap=0.15` |
| `[exposure]` | 4 | `exp_percentile=0.995`, `exp_target_level=0.88` |
| `[calibration]` | 8 | `calibrate_scan_rate=true`, `scan_retries=1`, `cos_dec_correction=true` |
| `[logging]` | 3 | rutas vacías: la carpeta de la sesión |

**Única desviación de default**: `scan.num_cycles` vale **3**, no 1, porque
DESIGN.md §6 y §7 piden tres ciclos por sesión. Ortografía y sección son las del
prototipo; ADR-024 deja la excepción escrita, que es lo que ADR-003 permite.

### 2.2 Renombradas: de SolarScribe al nombre heredado

El esquema v1 tenía claves propias que repetían una heredada. Se conservan como
**alias heredados** (`LEGACY_KEYS`), con el nombre heredado como canónico, para
que ningún agente que ya usara el nombre viejo se rompa:

| Nombre v1 de SolarScribe | Nombre canónico heredado |
| --- | --- |
| `scan.cycles` | `scan.num_cycles` |
| `scan.padding_s` | `scan.padded_duration` |
| `scan.preload_s` | `scan.scan_preload_seconds` |
| `scan.adaptive_stop` | `scan.trailing_limb_stop` |
| `capture.stall_timeout_s` | `fps.capture_stall_seconds` |
| `capture.min_free_disk_gb` | `fps.capture_min_free_gb` |
| `camera.auto_exposure` | `scan.enable_auto_exp` |

Reglas (ADR-024): la clave canónica manda; el alias solo se lee si el canónico no
está en el fichero; `save_settings()` escribe solo el nombre canónico; y
`keys_of(seccion)` oculta los alias para que el diálogo muestre un control por
comportamiento. Los defaults del alias y del canónico son iguales, así que un
fichero mudo da el mismo resultado por los dos nombres.

### 2.3 Retiradas: duplicaban un control y no podían ser alias

| Clave retirada | Qué la sustituye | Por qué |
| --- | --- | --- |
| `general.dry_run` | `scan.enable_capture = false` | Es el modo seco del prototipo; dos interruptores para lo mismo se contradicen |
| `scan.mode` | `scan.enable_mosaic` | El tipo no coincide (`"simple"`/`"mosaic"` frente a booleano) y la decisión es una sola |
| `camera.auto_exposure_target` | bloque `[exposure]` | El prototipo dirige un percentil (`exp_percentile`, `exp_target_level`), no la media; la media recorta las cúpulas |

No había código consumiéndolas (solo `config/schema.py`), así que la migración es
nula. Una herramienta que aún las escriba las verá en `Settings.unknown` y el
diálogo de ajustes podrá avisar.

### 2.4 Claves nuevas de SolarScribe (38, `origin="new"`)

Se **añaden**, nunca se renombra una heredada:

- `[general]`: idioma.
- `[observatory]`: latitud, longitud y altitud (el prototipo las tomaba de
  SharpCap; la efeméride local las necesita, ADR-021).
- `[camera]`: id, exposición, ganancia, offset, binning, bits, readout.
- `[roi]`: preset, rectángulos de captura y banda, y tilt (ADR-010, ADR-022).
- `[mount]`: backend, id, seguimiento, tasa manual (ADR-019).
- `[scan]`: método de centrado fino, tasa forzada, filas y paso de mosaico.
- `[capture]`: presupuesto de la cola y FPS objetivo (ADR-013).
- `[session]`: carpeta base, prefijo y autoguardado (DESIGN.md §10).
- `[polar]`: intervalo y duración del asistente (ADR-007).

### 2.5 Compatibilidad práctica

- El **contenido** de un `nightscribe-scan.cfg` se puede copiar tal cual al
  `config.ini` de SolarScribe: todas sus claves se reconocen. El prototipo busca
  su fichero junto al script o en `$NIGHTSCRIBE_CONFIG`; SolarScribe usa la
  carpeta de configuración de la plataforma, así que no lo descubre solo. La
  importación es una copia (o un "Importar…" en Ajustes, cuando exista).
- Las claves desconocidas no rompen el arranque: se devuelven en
  `Settings.unknown` para que el diálogo las señale.
- El parser tolera comentarios `#` y `;`, separador `=` o `:`, mayúsculas y el
  vocabulario fijo de booleanos (`1/true/yes/on` y sus negativos); un valor que
  no se puede leer deja el default (ADR-003).

## 3. Perfiles

`nightscribe-scan` guarda un `profiles.json` v1 y lo edita desde su panel HTML.
SolarScribe usa el **perfil JSON v2** de `config/schema.py` (`Profile`: datos del
telescopio, datos de cámara y presets de ROI) y lo edita desde Ajustes y el paso
ROI.

Implementado en `config/store.py` (ADR-024):

- `load_profile()` es tolerante: un fichero v2 escrito a mano, con números como
  texto, secciones ausentes o claves desconocidas, arranca la app con defaults en
  lo que no se puede leer.
- Migra un v1 si el usuario lo aporta: `FOCAL_LENGTH`, `PIXEL_SIZE`,
  `MOSAIC_SLIT_LENGTH_MM` y `meta.camera`/`meta.aperture_mm` se convierten en
  `TelescopeData` y `CameraData`. El resto de claves v1 es del INI y allí sigue.
- Un JSON truncado devuelve los defaults y el siguiente guardado lo reescribe.
- El **INI manda en la sesión**; el perfil es una instantánea con nombre que se
  aplica explícitamente desde Ajustes. No hay fusión automática de dos fuentes
  (ADR-024).

## 4. Criterios de aceptación

- Cada fila de la tabla §1 tiene módulo y prueba.
- Ninguna columna de los tres registros se pierde respecto a `nightscribe-scan`
  (solo se añaden).
- Un perfil v2 escrito a mano arranca la app sin errores (todos los defaults).
- El usuario puede reproducir un barrido de `nightscribe-scan` con SolarScribe y
  obtener el mismo resultado en el post-proceso.
