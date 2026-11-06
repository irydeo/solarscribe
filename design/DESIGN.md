# SolarScribe: documento de diseño marco

Estado: **borrador v0** (a iterar).
Fecha: 2026-11-06.
Proyecto hermano de NightScribe, con sus mismos patrones y reglas de desarrollo.

---

## 1. Visión

SolarScribe es la aplicación de **captura** para espectroheliógrafo (SHG). Abre
la cámara y la montura, mide en vivo y ejecuta el barrido, y deja los SER y los
registros listos para el post-proceso. Incluye una **vista previa ligera** (un
recon rápido) para validar la toma, pero **no hace post-proceso**: el recon
definitivo, el apilado y el mosaico siguen siendo externos (JSol'Ex y las
herramientas de `nightscribe-scan/tools`).

Sustituye a SharpCap en el flujo SHG, con una diferencia de fondo: es
**multiplataforma de verdad** (Linux y Windows) y **solo orientado al SHG**. No
pretende replicar SharpCap.

### Objetivos

- Multiplataforma: Linux y Windows, empaquetado en ambos.
- Solo captura SHG: nada de funciones generales de captura astronómica.
- Capa de dispositivos propia, con wrapper y **drivers enchufables** (nativos,
  ASCOM/Alpaca, INDI, INDIGO).
- Una sola lengua de desarrollo (Python) para alinear con NightScribe.

### No objetivos (por ahora)

- Post-proceso (recon, apilado, mosaico).
- Guiado, autofoco motorizado, ni control de cúpula.
- Compatibilidad con SharpCap (es un reemplazo, no un complemento).

### Configuración de referencia

El equipo con el que se desarrolla y valida el MVP:

- **Cámara**: Touptek G3M678M (mono), ROI de referencia 3480×248 px, 16 bits; sin
  control de temperatura.
- **Montura**: OnStep, vía **ASCOM COM** en Windows.
- **Óptica**: espectroheliógrafo **SHG-700** (focal ~714 mm, píxel 2 µm, rendija
  7 mm).
- **Desarrollo**: Linux; la montura se valida en Windows.

---

## 2. Principios (heredados de NightScribe)

- Python 3.11+ (3.12 recomendado); GUI **PySide6** + CLI.
- Licencia **GPL-3**.
- Código siempre en inglés; documentación en español e inglés.
- Código didáctico: cada decisión explica el porqué, no solo el qué.
- Decisiones en **ADRs** (`design/adr/`).
- Sin telemetría; todo local. La red solo se usa, opcionalmente, para la imagen
  del Sol (SDO); las efemérides se calculan localmente (ADR-021).
- Empaquetado: PyInstaller (Windows) e Inno Setup; `.deb` y `.rpm` (Linux).
- Numpy primero; una dependencia entra cuando aporta y su coste se justifica.
- Trabajo por agentes: siete roles con propiedad de módulos y gates de calidad
  (ver `AGENTS.md`).

---

## 3. Glosario

- **SHG**: espectroheliógrafo. La luz que pasa por una rendija se dispersa; el
  barrido en RA a través del disco reconstruye la imagen.
- **SER**: formato de vídeo astronómico (cabecera + fotogramas crudos).
- **ROI de captura**: región del sensor que la cámara entrega (ROI de hardware);
  manda en la tasa de fotogramas y es lo que se escribe al SER.
- **ROI de análisis**: sub-región del fotograma vivo (software) donde se mide
  (mitades izquierda/derecha, columnas del limbo, celdas de enfoque); no se
  guarda.
- **Banda/orden espectral**: la franja del sensor que contiene el espectro
  dispersado; debe caber dentro del ROI de captura.
- **Driver**: módulo que habla con un dispositivo concreto.
- **Backend**: familia de drivers (nativo, ASCOM/Alpaca, INDI, INDIGO).
- **Barrido**: un recorrido de la rendija sobre el disco, una toma (un SER).
- **Tilt**: inclinación de la línea espectral/rendija respecto al eje del sensor;
  sesga la reconstrucción y agranda la altura necesaria del ROI (ADR-022).
- **Recon rápido**: reconstrucción ligera para validar la toma; no sustituye al
  post-proceso.

---

## 4. Arquitectura por capas

```
solarscribe/                   (repo público, raíz de trabajo)
  design/      diseño, contratos y ADRs
  solarscribe/ devices/ capture/ shg/ ui/ cli/ config/
  tests/       unit (sin hardware) y funcional (mocks, vídeos, hardware)
  docs/        guía de usuario
```

Regla de dependencias: `ui` y `cli` dependen de `capture` y `shg`; `capture` y
`shg` dependen de `devices`; `devices` no depende de nada de la aplicación.
`config` es una **hoja de soporte**: solo importa `devices` y la pueden leer todas
las capas; `capture` y `shg` no se importan entre sí (ADR-023). Así
la lógica SHG y la UI se pueden probar sin hardware. Los **contratos entre capas
y el modelo de datos** están en `design/ARCHITECTURE.md` (ADR-012) y escritos en
`devices/abc.py`, `capture/abc.py`, `shg/abc.py` y `config/schema.py` (ADR-023).

---

## 5. Capa de dispositivos

Es el núcleo del diseño y la parte con más riesgo. Se separa en **interfaz
común** (lo que la app usa) y **drivers** (lo que habla con cada dispositivo),
para que añadir un dispositivo sea escribir un módulo que implemente la
interfaz y se registre.

Hay **dos áreas de hardware**: la **cámara** (el riesgo principal: alta tasa,
muchos SDK) y la **montura** (esencial: el barrido es un movimiento suyo). La
cámara se resuelve **derivando del proyecto `simple-astro-cap`** (GPL-3; ver
§19), que ya cubre las cuatro marcas que nos interesan; la montura entra por la
vía estándar de cada plataforma (ASCOM en Windows, INDI en Linux, §5.2).

### 5.1 Cámara

**Cámara de referencia**: **Touptek G3M678M** (mono), ROI de referencia
3480×248 px, 16 bits. El **control de temperatura no se usa** en el MVP.

**Base adoptada**: el modelo de `simple-astro-cap`:

- `CameraBase` (ABC): la interfaz común (`Frame`, `Param`, `ROI`, `CameraInfo`).
- `MultiCamera`: agregador que descubre cámaras de todos los backends y delega
  en el adecuado.
- Un backend por SDK, hablado desde Python con `ctypes`.

**Interfaz `Camera`** (lo que usan la app y el motor SHG):

- Ciclo de vida: `open`, `close`, `is_open`.
- Propiedades: ROI, binning, exposición, ganancia, offset, profundidad de bits,
  temperatura y cooler, velocidad de lectura (USB traffic).
- Stream: `start_stream`, `stop_stream`, y **callback por fotograma**.
- Medidas: media y desviación típica del fotograma y de **sub-regiones**
  (recortes del ROI), que es lo que usa el motor SHG.
- Identificación: fabricante, modelo, identificador y capacidades.

**Backends** (todos tras la misma interfaz):

- `native/asi` (ZWO): `libASICamera2`.
- `native/qhy`: `libqhyccd`.
- `native/playerone`: `libPlayerOneCamera`.
- `native/touptek`: `libtoupcam` (cubre además Altair, Omegon, RisingCam,
  Mallincam y OGMA como OEM).
- `sim`: simulador de cámara (patrones de prueba) para la UI y los tests sin
  hardware.
- `ascom`/`alpaca` (HTTP) e `indi`/`indigo`: backends genéricos de respaldo, que
  además valen para la montura.

Las librerías del SDK se cargan de forma **dinámica**: si no está, el backend no
aparece y la app sigue con los demás (degradación elegante).

**Modelo de hilos** (de `simple-astro-cap`; es lo que hace que Python aguante la
tasa):

```
hilo de captura: get frame (el backend copia y sella el fotograma), nada más
   +--> consumidores inline (baratos): DisplayBridge (buzón de 1 frame -> señal
   |    Qt), auto-exposición, stats del motor SHG
   +--> cola de grabación acotada (presupuesto en MB; desbordes contados)
              |
              v  hilo escritor
        grabador SER
```

- El **hilo escritor** desacopla el disco: una escritura lenta nunca detiene la
  adquisición.
- El **DisplayBridge** es un buzón del último fotograma: una GUI lenta descarta
  fotogramas de vídeo, no los acumula.
- Los **timestamps** se toman al recibir el fotograma, no al escribir.

**Contabilidad de frames perdidos** en los tres sitios: dentro del SDK
(contadores), desborde de la cola de grabación (disco) y huecos de secuencia del
lado del host.

**Requisitos de sistema**: en Linux, reglas `udev` y (QHY) firmware; los SDK se
descargan con un script (`fetch-deps`). En Windows, `.dll` en vez de `.so` y sin
udev. Se documenta en el instalador.

### 5.2 Montura

La montura es esencial: el barrido **es** un movimiento en RA y el centrado y la
alineación polar son pequeños movimientos en Dec. Interfaz `Mount`:

- Conexión y estado.
- Posición: RA y Dec (y Alt/Az si el backend lo ofrece).
- Movimiento: `move_axis(eje, tasa)`, `stop`, slew a coordenadas y `sync`.
- Seguimiento (tracking) y park/unpark.
- Capacidades: tasas admitidas, si reporta posición en movimiento.

**Montura de referencia**: **OnStep**, con su driver ASCOM en Windows.

**Backends por plataforma** (ADR-019):

- **Windows**: **ASCOM con COM nativo** (la vía estándar en Windows; requiere la
  **plataforma ASCOM** instalada y un puente COM de Python, `pywin32`/`pythonnet`).
- **Linux**: **INDI**, cliente del protocolo INDI contra un **`indiserver`** en
  marcha.
- Respaldo directo opcional: `native` (LX200, OnStep) por serie, e `indigo`.

**Control desde la interfaz** (como SharpCap, ADR-019): un **panel de
telescopio** con conectar/desconectar, GOTO por coordenadas (y **al Sol** por
efeméride), botones de movimiento N/S/E/W con selector de tasa, seguimiento,
park/unpark, sync y abortar slew, con lectura viva de RA/Dec y del estado.

---

## 6. Motor de captura

- Stream en vivo y buffer circular.
- Estadísticas por fotograma (media y desviación típica) y por sub-región.
- Escritor **SER**: cabecera, color ID, profundidad de bits y timestamps;
  escritura bufferizada y verificación de fotogramas perdidos.
- **16 bits** por píxel; **binning configurable** (1×1 por defecto).
- **Autoexposición** con objetivo (llena el histograma sin saturar), con ajuste
  manual; **varios ciclos** por sesión (**3** por defecto).
- El **ROI de captura** es un parámetro de primera clase: se selecciona en el paso
  ROI, determina la tasa y es lo que viaja en la cabecera del SER y en
  `session_meta.json`.

### 6.1 Gestión del ROI

El ROI es crítico: el barrido **no usa todo el sensor**, sino una franja
recortada (p. ej. 3480×248) que da la tasa necesaria. Se distinguen cuatro
regiones:

1. **ROI de captura (sensor)**: lo que entrega la cámara; fija el FPS y el
   tamaño del SER. **Lo selecciona el usuario** en el paso ROI (editor en vivo);
   no hay propuesta automática.
2. **ROI de análisis (software)**: sub-regiones del fotograma vivo para medir
   (mitades izquierda/derecha, columnas del limbo, celdas de enfoque y el ajuste
   del tilt). Se calculan, no se guardan.
3. **Banda/orden espectral**: la franja útil del espectro; debe caber dentro del
   ROI de captura (se avisa si se recorta).
4. **ROI de salida**: lo que se escribe al SER y consume el post-proceso
   (= ROI de captura).

Herramientas:

- **Editor en vivo**: overlay sobre el visor con asas arrastrables, campos
  numéricos y *snap* a la banda iluminada.
- **Presets** por cámara + óptica, persistidos en el perfil y restaurados al
  conectar.
- **Medición de tilt** (ADR-022): se ajusta una recta a la posición del borde de
  la rendija/línea espectral a lo ancho del ROI; la pendiente es el tilt, en
  grados y en píxeles de deriva. Sirve para (a) validar la altura del ROI
  (`banda + |deriva| + márgenes`), (b) guiar al usuario a dejarlo recto y
  (c) registrarlo para el post-proceso.
- **Herramienta de alineación de rendija**: ayuda a que la banda caiga recta y
  centrada; muestra el tilt en lenguaje llano.
- **Validación**: recorte del orden, alineación rendija↔espectro, altura según el
  tilt, FPS y caudal de datos estimados, límites del SDK (múltiplos, binning) y
  coherencia al cambiar de binning.
- Todo el ROI y el tilt quedan en `session_meta.json` y `scan_log.csv` para
  reproducir la toma.

### 6.2 Presupuesto de rendimiento y observabilidad

El proyecto se juega su utilidad en la tasa. El presupuesto provisional (ADR-013)
para el ROI de referencia (3480×248 px, mono) es:

| Métrica | Objetivo |
| --- | --- |
| FPS sostenidos | ≥ 120 |
| Caudal | ~207 MB/s a 16 bit |
| Frames perdidos por barrido | ≤ 0,1% |
| Huecos de secuencia (nominal) | 0 |
| Latencia del visor | ≤ 150 ms |
| CPU del host | overhead < 20% de un núcleo a 120 fps |
| Memoria | cola de grabación 512 MB, RSS estable |
| Disco sostenido | ≥ 250 MB/s; aviso si < 1 GB libre |
| Arranque de captura | ≤ 5 s |
| Stall | abortar si > 3 s sin frames |

Se mide en vivo (contadores de fps, frames perdidos por SDK, por cola y por
huecos, profundidad de la cola y MB/s de disco), se muestra en un **panel de
salud** y se registra por barrido en `scan_stats.jsonl`. Los números se cierran en
la fase 0.

---

## 7. Motor SHG

Se **porta de `nightscribe-scan`**, que ya es Python:

- Detección del limbo por desviación típica.
- Autocalibración de la velocidad de barrido.
- Barrido simple y mosaico multífila.
- Centrado en Dec: bucle izquierda/derecha y método de la cuerda.
- Padding, precarga de AR, parada adaptativa y duración por cuerda.
- **Varios ciclos** por sesión (3 por defecto); si el Sol se sale de la rendija,
  el barrido **se pausa y avisa**, y se puede recentrar antes de continuar.
- Registros: `scan_log.csv`, `scan_stats.jsonl` y `session_meta.json`.

El centrado fino (simetría o cuerda) y la autocalibración de la tasa son la
**preparación del escaneado**: viven dentro del paso *Escaneado* del flujo de
sesión (§9), no en un paso aparte.

---

## 8. Puesta en estación y alineación polar

La puesta en estación es el conjunto de pasos que deja el Sol centrado en la
rendija y el monte alineado con el polo. Es una funcionalidad propia de
SolarScribe: en un observatorio solar no se ve Polaris de día, así que la
referencia es el propio Sol sobre la rendija.

En el flujo de sesión (§9) son los dos primeros pasos: **Buscar el Sol** (§8.1 y
el centrado grueso de §8.2) y **Alineación polar** (§8.3).

### 8.1 Preapuntado

**GOTO automático al Sol** por efeméride (RA/Dec para la hora y la ubicación del
observatorio) desde una posición de partida básica; luego la app afina. Solo
tiene que colocar el Sol en el campo y sobre la rendija; el resto lo refinan los
pasos siguientes.

### 8.2 Centrado del Sol en la rejilla

El centrado lo hace la app **automáticamente** (con el panel de telescopio como
control manual de respaldo):

- **Grueso (histograma y extensión)**: un *hill-climb* en Dec que maximiza la
  fracción de píxeles brillantes (percentil alto del histograma, equivalente a
  la extensión iluminada del espectro). Es rápido y trabaja sobre el frame vivo,
  sin barrido.
- **Fino**: simetría izquierda/derecha si el disco cabe a lo largo de la
  rendija; si no, el método de la cuerda (barrido).
- **Límite honesto**: la extensión iluminada es plana cerca del centro (la
  cuerda cumple `L = 2·√(R² − q²)`, de derivada nula en `q = 0`), así que el
  histograma **no elimina la zona muerta**; sirve para el centrado grueso y se
  encadena con el fino. La interfaz debe decirlo.

### 8.3 Asistente de alineación polar solar

- Con el Sol en la rendija y el monte siguiendo, muestrea la posición en Dec del
  Sol cada pocos minutos (por el limbo o por la cuerda) y **resta el movimiento
  propio del Sol** (efeméride, hasta ~0.4"/min).
- Ajusta la recta de deriva y deduce el error de **azimut** y **altitud**.
- Guía al usuario (cuánto girar cada tornillo) y pide una **segunda medida de
  confirmación**.
- Recomienda **cuándo** medir: cerca del meridiano para el azimut, y hacia el
  Este/Oeste para la altitud (ADR-025 corrige la guía de ADR-007); de día el
  Sol barre de Este a Oeste, así que conviene repartir la medida.
- Es **preciso y sin prisa**: la medida se reparte en 20–40 min para separar bien
  los errores de azimut y altitud.

### 8.4 Encaje en la arquitectura

Reutiliza el motor SHG (limbo y cuerda) para medir Dec y la capa de dispositivos
para mover la montura (automáticamente, con el panel de telescopio como control
manual). Los indicadores se muestran en el visor y en el panel de sesión.

---

## 9. Interfaz de usuario (PySide6)

Sigue el **mismo estilo y los mismos patrones que NightScribe** (ADR-009):

- **Tema**: `theme.py` como fuente única de la identidad visual; **solo tema
  oscuro**, con **icono, logo y acento propios** de SolarScribe (sol). Ficheros
  `.ui` + `ui_loader.py`; i18n `.ts` ES/EN.
- **Idioma**: el del sistema por defecto, con una opción para cambiarlo.
- **Menú**: `QMenuBar` con **File / Tools / Help**. En **Tools** viven las
  utilidades: Settings…, **Sky calendar…**, **ROI manager…**, Focus aid…,
  Device diagnostics… y **Logs** (visor de logs dentro de la app). No hay barra
  de navegación superior.
- **Tools → Sky calendar… → Sun**: las utilidades de observación solar se
  integran aquí, en la pestaña **Sun** (copia propia adaptada del calendario de
  NightScribe): imagen real del Sol (SDO), regiones activas (NOAA), datos del Sol
  de hoy y utilidades del SHG (diámetro y ángulo solar, rotación, coordenadas
  heliográficas).

### 9.1 Disposición

- **Raíl de pasos arriba** (horizontal), con el estado de cada paso.
- **Panel lateral** con las opciones del paso activo.
- **Vídeo** en el área principal, con **histograma, stretch, zoom, rejilla y
  cruz** de la rendija, y una **vista ampliada de la franja del espectro**.
- **Barra de estado** abajo: fps, frames perdidos, estado de cámara y montura, y
  espacio en disco.
- **Ventana principal + diálogos** (calendario, ajustes, visor de logs).

### 9.2 Sesión por pasos

La vista principal es una **sesión por pasos**, con el mismo lenguaje que los
pasos de proyecto de NightScribe: un **raíl** con el estado de cada paso
(pendiente / en curso / hecho), **navegación libre**, **recomendaciones** (nunca
puertas que bloqueen), **autoguardado silencioso** y **«reabrir paso»**. **Todos
los controles están visibles siempre**: el raíl guía, no esconde (no hay un modo
experto aparte).

Los pasos son cuatro:

1. **Buscar el Sol**: GOTO automático al Sol por efeméride y centrado grueso
   sobre la rendija (§8.1–8.2), con el panel de telescopio.
2. **Alineación polar**: asistente de alineación solar (§8.3).
3. **ROI**: el usuario selecciona el ROI de captura (editor en vivo), se mide el
   **tilt** (§6.1, ADR-022), se alinea la rendija y se estiman FPS y caudal.
4. **Escaneado**: preparación (centrado fino y autocalibración, §7) y barrido
   simple o mosaico, con progreso, frames perdidos y stats.

Cada paso muestra, en **lenguaje llano**, qué hace y por qué, un indicador en
vivo y **una sola acción principal** destacada. El visor en vivo permanece
visible.

### 9.3 Visualización del barrido y resultado

- **Barrido en vivo**: sobre una imagen del Sol se dibuja la **franja ya
  capturada**, la **línea de la rendija** y el **porcentaje** completado. El
  fondo es un **disco esquemático** (funciona sin red) y, si hay conexión, la
  **imagen real del Sol** del día (ADR-021).
- **Recon rápido**: al terminar, una reconstrucción **ligera y no autoritativa**
  del disco para saber si el barrido salió bien; se ve en pantalla (no se
  exporta) y **no sustituye al post-proceso**.
- **Resumen de la sesión**: frames, perdidos, duración y ruta, con un botón para
  **abrir la carpeta** de la sesión.

### 9.4 Resto de la interfaz

- **Panel de telescopio** (como SharpCap): conectar/desconectar, GOTO por
  coordenadas y al Sol, movimiento N/S/E/W con selector de tasa, seguimiento,
  park/unpark, sync y abortar slew, con lectura viva de RA/Dec. Presente en el
  paso *Buscar el Sol* y accesible siempre.
- Panel de sesión (modo, ciclos, padding, parámetros con ajuste).
- Configuración y perfiles (con datos del telescopio).
- Ayuda al enfoque (los indicadores de `nightscribe-focus`).
- Estado, consola y avisos.

---

## 10. Configuración y perfiles

Esquema INI igual que `nightscribe-scan` (mismas claves) más las claves de ROI,
tilt y sesión, editable a mano y desde la UI. Un **solo perfil** con los datos
del telescopio (focal, píxel, rendija) y el preset de ROI. La herencia es
deliberada: el post-proceso existente y los hábitos del usuario no cambian.

**Sesiones**: una **carpeta por sesión** (con fecha y hora) dentro de una carpeta
base configurable; los ficheros se nombran `sun_AAAAMMDD_HHMM_scanNN.ser` (con su
`.csv` y `.jsonl`).

---

## 11. Logs y trazabilidad

Mismos ficheros y columnas que `nightscribe-scan`, para no romper el
post-proceso ni las herramientas ya escritas. `session_meta.json` añade el **ROI
efectivo**, el **tilt**, la **orientación de cámara**, los contadores de frames
perdidos y la versión de la app (ADR-018, ADR-022). La app incluye un **visor de
logs** en Herramientas.

---

## 12. Empaquetado y despliegue

Windows y Linux son **de serie desde el MVP** (ADR-004), no una fase posterior:

- **Windows 10/11 x64**: PyInstaller + Inno Setup.
- **Linux**: `.deb` (Debian/Ubuntu) y `.rpm` (Fedora/RHEL).
- Los binarios de los SDK viajan dentro; en Linux se incluyen las reglas `udev`
  y (QHY) el firmware.
- **Integración continua matricial** que construye y prueba ambos SO.
- Se reutiliza el `installer/` de NightScribe (`.iss`, `.spec`, `.deb`, `.rpm`),
  salvando las diferencias de plataforma (`.dll` vs `.so`, `%APPDATA%` vs XDG,
  udev vs nada).
- **Distribución**: instaladores publicados en **GitHub Releases**. El instalador
  de Windows **no va firmado** (puede aparecer el aviso de SmartScreen).
- La app **degrada con elegancia** si falta un driver o un SDK: dice qué falta y
  sigue con lo demás.

---

## 13. Pruebas

Tres capas, custodiadas por el agente QE (ADR-015):

- **Unitaria (TDD estricto)**: sin hardware, con simuladores de cámara y montura.
  Ningún cambio de producto sin prueba escrita antes.
- **Funcional**: con mocks y con **vídeos/SER reales** como fixtures (guardados
  en una **ruta externa** al repositorio, configurable); el hardware real va
  marcado aparte. La calidad se evalúa contra esos ejemplos cuando se requiere.
- **Rendimiento**: un banco mide el presupuesto de §6.2 (fps, frames perdidos,
  caudal, latencia, memoria); una regresión bloquea.

La lógica SHG y las métricas se prueban con **datos reales como fixtures** (igual
que el log de la sesión que destapó el bug de calibración). Cada fixture real se
cataloga.

---

## 14. Lista de funcionalidades

**MVP (fase 1)**
- Un driver de cámara nativo (Touptek G3M678M) con SER y stats.
- Monturas por plataforma: **ASCOM COM en Windows** e **INDI en Linux**, con
  panel de control en la UI (ADR-019).
- Motor SHG completo (simple y mosaico), con centrado fino, autocalibración y
  varios ciclos.
- Puesta en estación: **GOTO automático** al Sol, centrado automático y asistente
  de alineación polar solar guiado.
- **Gestión del ROI completa**: editor en vivo, presets, validación y **medición
  de tilt** (§6.1, ADR-022); sin propuesta automática.
- **UI con paridad NightScribe**: tema oscuro, menú File/Tools/Help, sesión por
  pasos, **visualización del barrido**, **recon rápido**, **visor de logs**,
  i18n `.ts` ES/EN y **Tools → Sky calendar… → Sun**.
- Autoexposición con objetivo, binning configurable, 16 bits y 3 ciclos.
- Asistente de bienvenida, perfil único, sesiones en carpetas y modo seco.
- **Empaquetado Windows 10/11 x64 y Linux (.deb/.rpm)** con CI matricial y
  **GitHub Releases**.

**Fase 2**
- Más drivers de cámara (ASCOM/Alpaca, INDI, INDIGO).
- Ayuda al enfoque.
- CLI de diagnóstico de dispositivos.

**Fase 3**
- Más monturas: respaldo nativo (LX200, OnStep) e INDIGO.
- Guiado paso a paso de la puesta en estación y validación de la medida.
- Endurecimiento: recuperación, avisos, límites.

---

## 15. Roadmap

- **Fase 0, spike de evaluación**: un experimento mínimo que valide la tasa de
  captura (~120 fps en el ROI típico, sin fotogramas perdidos) y el control de
  montura. Es la puerta de decisión del proyecto.
- **Fase 1 (MVP)**: incluye la gestión del ROI completa, la UI con menú y sesión
  por pasos, **Sky calendar → Sun** y el **empaquetado Windows + Linux**.
- **Fase 2 y 3**: más drivers, enfoque, diagnóstico y endurecimiento.

---

## 16. Riesgos

- **Tasa de captura y estabilidad del stream**: es el riesgo principal.
- **Empaquetado de SDKs propietarios**: licencias y tamaño.
- **Backends genéricos (INDI/ASCOM) para cámara**: latencia para vídeo de alta
  tasa (la montura no tiene ese problema).
- **Dependencia de ASCOM/INDI para la montura**: son los caminos por plataforma y
  sin ellos no hay barrido; se mitiga con el simulador de montura y con el
  respaldo nativo (LX200, OnStep).
- **Estadísticas por fotograma** a alta tasa en Python.
- **Alineación polar solar**: depende del tiempo de medida y de la geometría del
  Sol (su hora angular limita qué error se puede separar en cada momento).
- **Alineación de la rendija dentro del ROI**: un ROI mal ceñido recorta el
  orden o la rendija; hay que validarlo y guiar al usuario.
- **Tilt del espectro/rendija**: una inclinación grande sesga la reconstrucción y
  no cabe en el ROI; hay que medirla (ADR-022), guiar para minimizarla y
  registrarla para el post-proceso.
- **Distribución de SDKs en los dos SO**: además de licencias y tamaño, hay que
  mantener la carga dinámica y las reglas de sistema en Windows y Linux.

---

## 17. Decisiones de arquitectura (ADRs)

Las decisiones viven en `design/adr/` (bilingües ES/EN; ver `design/adr/README.md`).
Estado inicial:

- ADR-000: usar ADRs (proceso).
- ADR-001: lenguaje y arquitectura. **Python puro con `ctypes`/`cffi`** para el
  camino de dispositivos; helper nativo solo si el spike lo exige.
- ADR-002: backends de cámara del MVP (los cuatro de `simple-astro-cap`; se
  prueban primero Touptek y ZWO). El backend de montura se decide en ADR-019
  (ASCOM en Windows, INDI en Linux).
- ADR-003: configuración y perfiles (herencia de `nightscribe-scan`).
- ADR-004: empaquetado multiplataforma (Windows y Linux de serie desde el MVP).
- ADR-005: simuladores y pruebas sin hardware.
- ADR-006: centrado del Sol en la rejilla (grueso por histograma, fino por
  simetría o cuerda).
- ADR-007: alineación polar solar (modelo de deriva, corrección de efeméride y
  guiado al usuario).
- ADR-008: base de cámara, pipeline y grabación: derivar de `simple-astro-cap`
  (GPL-3) con atribución; SDK nativo como camino principal y ASCOM/Alpaca e INDI
  como respaldo.
- ADR-009: interfaz, tema y menú (paridad con NightScribe; Tools → Sky calendar →
  Sun).
- ADR-010: gestión del ROI (cuatro regiones, editor en vivo, presets, medición de
  tilt y validación; sin propuesta automática).
- ADR-011: flujo de sesión por pasos (raíl de cuatro pasos, navegación libre,
  recomendaciones, autoguardado y reabrir paso).
- ADR-012: contratos entre capas y modelo de datos (`design/ARCHITECTURE.md`).
- ADR-013: presupuesto de rendimiento y observabilidad.
- ADR-014: errores y degradación (SDK ausente, desconexión, disco, stall).
- ADR-015: estrategia de pruebas y fixtures (unitaria, funcional, rendimiento).
- ADR-016: i18n y documentación (ES/EN desde el día 1).
- ADR-017: empaquetado, CI, versionado y licencias.
- ADR-018: contrato con el post-proceso (SER + registros).
- ADR-019: control de montura por plataforma (ASCOM COM en Windows, INDI en
  Linux) y panel de telescopio en la UI.
- ADR-020: resultado de la sesión, visualización del barrido y recon rápido.
- ADR-021: política de red y efemérides locales.
- ADR-022: medición de tilt del espectro/rendija (medir, guiar y registrar).
- ADR-023: módulos de contrato y hogar del modelo de ROI (los contratos escritos en
  código, `config` como hoja de soporte, los puertos de `shg` y el estado de sesión
  en `config`).
- ADR-024: reconciliación del INI con `nightscribe-scan` y contrato de
  `config/store.py` (claves heredadas con su ortografía y defaults, alias de los
  nombres antiguos, perfil v2 con migración v1 y carpetas por plataforma con el id
  `SolarScribe`).

---

## 18. Relación con los proyectos existentes

- **NightScribe**: hermano. Mismos patrones y reglas. SolarScribe **no** es un
  módulo suyo: es un proyecto aparte.
- **nightscribe-scan**: el prototipo actual sobre SharpCap. De ahí se porta el
  motor SHG, el esquema de configuración y los formatos de log. SolarScribe lo
  sustituye en Linux y Windows.
- **simple-astro-cap**: base de la capa de cámara, el pipeline y el grabador
  SER (GPL-3). Ver §19.

---

## 19. Antecedentes y base

Esta sección deja por escrito cómo acceden otras aplicaciones de captura al
hardware y sobre qué proyecto nos apoyamos. Es la justificación de las
decisiones de §5.

### 19.1 Cómo acceden otras apps a las cámaras

| Software | Lenguaje | Acceso a cámara | Plataformas |
| --- | --- | --- | --- |
| **SharpCap** | (cerrado) | Tres vías: **SDK nativo por marca** (ZWO, QHY, Altair, Atik, Basler, Player One, TIS, Moravian, SVBony, Point Grey, StarlightXpress...), **DirectShow/WDM** (webcams) y **ASCOM/Alpaca** | Windows |
| **FireCapture** | Java + JNI | **SDK nativo por marca** (ZWO ASI, QHY, Player One, SVBony, Toupcam/Omegon, FLIR FlyCapture/Spinnaker, Basler Pylon, TIS, IDS); **INDI** para la montura en Mac/Linux | Windows, macOS, Linux |
| **oacapture** | C++/Qt + libs C | **SDK nativo por marca** (ZWO, QHY, Touptek, Altair, Mallincam, Risingcam, TIS, Point Grey, Atik, SX), **IIDC/DCAM** y **V4L2/UVC**; carga dinámica si la librería está | Linux, macOS |
| **Planetary Imager** | C++/Qt | V4L2, ZWO, QHY | Linux |
| **Laminar** | (nativo) | **SDK nativo** (ZWO, Player One, QHY, Touptek, SVBONY) | macOS |
| **INDI** | C++ (libindi) | Interfaz genérica (`INDI::CCD`) con un driver por dispositivo; streaming (`CCD_VIDEO_STREAM`) y grabador **SER** | Linux, macOS, Windows |
| **ASCOM/Alpaca** | .NET / REST | **Alpaca** (HTTP/JSON) es la versión multiplataforma de ASCOM | Windows (y Alpaca en cualquier SO) |

**Patrón común**: los programas con mejor control y rendimiento hablan
**directamente con el SDK del fabricante** y dejan ASCOM/DirectShow/INDI como
respaldo genérico. SharpCap lo dice explícito: prefiere el soporte directo
porque da el control más detallado y más velocidad.

Conclusión para nosotros: el camino principal es **SDK nativo por marca** (por
`ctypes`), y ASCOM/Alpaca e INDI entran como **backends de respaldo** y para la
montura.

### 19.2 Base: simple-astro-cap

**Qué es**: aplicación de captura (Python + PySide6) para cámaras astronómicas
usadas en fotografía infrarroja terrestre. Soporta **QHY, ZWO ASI, Player One y
Touptek** por **SDK nativo con `ctypes`**. Repositorio:
<https://github.com/sweisman/simple-astro-cap>. Licencia **GPL-3**.

**Por qué nos sirve**: resuelve, ya hecho y probado, justo la parte más cara del
proyecto (la capa de cámara), y con la misma pila que NightScribe.

**Qué reutilizamos**:

- `camera/`: `abc.py` (`CameraBase`, `Frame`, `Param`, `ROI`, `CameraInfo`),
  `multi.py` (`MultiCamera`), los cuatro backends (`asi`, `qhy`, `playerone`,
  `touptek`) con sus SDK (`sdk.py`) y el simulador (`sim`).
- `pipeline/`: `simple.py` (harness de hilos y cola) y `auto_exposure.py`.
- `recording/`: `abc.py` y `ser_recorder.py` (SER con timestamps y metadatos
  Bayer).
- `util/units.py`, `settings.py` (adaptados) y el patrón de `tests/`.
- `scripts/fetch-deps.sh` y `scripts/install-udev-rules.sh` (descarga de SDK y
  reglas de Linux).

**Qué escribimos nosotros**: el motor SHG, la capa de montura, la UI de captura
SHG y la configuración/perfiles.

**Modo de reutilización**: adoptar los módulos de cámara, pipeline y grabación
como base de `devices/` y `capture/`, con **atribución** en las cabeceras y
manteniendo GPL-3 (ver ADR-0008). Al ser la misma licencia, la convivencia es
directa.

**Pendiente de verificar**: los backends de Player One y Touptek están escritos
pero sin probar en hardware (según el propio README); y el proyecto es
Linux-only, con notas de portabilidad a Windows (`.dll` vs `.so`, sin udev,
`%APPDATA%`) que seguiremos.
