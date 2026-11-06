# Guía de usuario de SolarScribe

**Español** · [English → USER_GUIDE.md](USER_GUIDE.md)

Una guía de SolarScribe: qué hace, por qué importa cada función y cómo está
pensada una sesión. Está escrita desde el diseño y los contratos, así que se
puede leer antes de que exista el código. Las secciones marcadas como **Previsto**
describen el comportamiento acordado, no algo que puedas ejecutar hoy.

> **Estado de esta guía (2026-11-06)**: los motores reales de captura, centrado y
> barrido están conectados a la interfaz y corren contra un simulador de espectro
> solar; la captura con cámara y montura reales todavía no está validada. La guía
> se escribe junto a los contratos, para fijar el comportamiento antes de probar
> cada rincón del hardware.

---

## 1. Qué es SolarScribe

SolarScribe es la aplicación de **captura** para un espectroheliógrafo solar
(SHG). Abre la cámara y la montura, mide sobre el flujo en vivo, ejecuta el
barrido y deja los ficheros SER y los registros listos para el post-proceso. **No
hace post-proceso**: el recon, el apilado y el mosaico siguen en JSol'Ex y en las
herramientas de `nightscribe-scan/tools`.

Un espectroheliógrafo funciona de una manera que explica casi todas las funciones
de esta guía. La luz que entra por una rendija estrecha se dispersa en un
espectro. La montura mueve el disco solar a través de esa rendija fija, y cada
fotograma capturado se convierte en una columna de la imagen final. La
reconstrucción es correcta solo si el cielo se mueve exactamente un píxel por
fotograma; por eso importan tanto la tasa de barrido, la tasa real de fotogramas y
el ROI.

SolarScribe es hermano de NightScribe y conserva sus patrones: Python 3.11+,
PySide6, tema oscuro, sesión por pasos, bilingüe ES/EN y GPL-3. Sustituye a
SharpCap en el flujo SHG, con una diferencia de fondo: es **multiplataforma de
verdad** (Linux y Windows) y **solo hace SHG**.

**Fuera de alcance, por diseño**: post-proceso, guiado, autofoco motorizado y
control de cúpula. Existe un **recon rápido** ligero para validar una toma, pero
se muestra solo en pantalla y nunca sustituye a la cadena de reducción real.

---

## 2. Estado y qué funciona hoy

Este repositorio es joven, y fingir lo contrario te haría perder el tiempo.

| Área | Estado hoy |
| --- | --- |
| Esqueleto del paquete y layout de capas | **Disponible** |
| Módulos de contrato (`devices`, `capture`, `shg`, `config`) | **Disponible** |
| Esquema de configuración, perfil y estado de sesión | **Disponible**: lectura y escritura con valores por defecto, escritura atómica y migración de perfil v1 a v2 |
| Test de la regla de dependencias (`tests/unit/test_layers.py`) | **Disponible** |
| Interfaz, panel de cámara y simulador | **Disponible**: la ventana arranca, el descubrimiento encuentra el simulador y la cámara se abre y envía |
| Motores reales conectados a la ventana | **Conectado (simulador)**: centrado, ROI, preparación, barrido y vista previa corren contra el simulador |
| Captura con cámara y montura reales | **Previsto (MVP)**: los drivers y motores existen, todavía sin validar en hardware |
| Instaladores para Windows y Linux | **Todavía no disponible** |
| Catálogos ES/EN y esta guía | **Disponible**; todo lo extraíble está traducido, 0 sin traducir |

Lo que sí puedes hacer desde un clon:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit
.venv/bin/python -m solarscribe --version
.venv/bin/python -m solarscribe --diagnostics
```

`python -m solarscribe --version` imprime la versión del paquete instalado; un
clon de desarrollo muestra algo como `0.0.1.dev3+g...`, y un árbol de fuentes que
nunca se instaló vuelve a `0.0.0`. `python -m solarscribe` abre la ventana
principal; sin cámara ni montura arranca con el simulador. `python -m
solarscribe --diagnostics` imprime un informe de las rutas, la óptica, los
presets de ROI y la capa de dispositivos, y `python -m solarscribe --dry-run`
comprueba la geometría sin abrir la cámara ni mover la montura. Los dos son lo
primero que conviene adjuntar a un informe de fallo.

### Palabras de estado que usa esta guía

| Palabra | Significado |
| --- | --- |
| **Disponible** | Funciona en el árbol de fuentes actual. |
| **Conectado (simulador)** | El motor real está conectado a la interfaz y corre contra el simulador; la vía de hardware sigue siendo Previsto (MVP). |
| **Previsto (MVP)** | Acordado en el diseño y los contratos; forma parte de la primera versión utilizable. |
| **Previsto (fase 2)** | Acordado, pero después del MVP (más backends de cámara, ayuda al enfoque, diagnóstico de dispositivos). |
| **Previsto (fase 3)** | Endurecimiento y backends de montura adicionales. |
| **Solo diseño** | La decisión existe; la forma aún puede cambiar. |

---

## 3. Inicio rápido

### 3.1 Equipo de referencia

El MVP se desarrolla y se valida con esta configuración, y las cifras por defecto
de la configuración salen de ella:

| Elemento | Referencia |
| --- | --- |
| Cámara | Touptek G3M678M, mono, 16 bits, sin control de temperatura |
| ROI de referencia | 3480×248 px |
| Montura | OnStep, por ASCOM COM en Windows e INDI en Linux |
| Óptica | Espectroheliógrafo SHG-700, focal de unos 714 mm, píxeles de 2 µm, rendija de 7 mm |
| Desarrollo | Linux; la montura se valida en Windows |

La rendija de 7 mm no es una cifra arbitraria: a 714 mm de focal subtiende
`7 / 714 rad = 33.7'`, justo por encima del diámetro solar de unos 32', así que
una sola fila del barrido puede cubrir todo el disco.

### 3.2 Instalación

Consulta la [guía de instalación](../install/INSTALACION.md). Hasta la primera
versión, el único camino es instalar desde el código fuente; los instaladores en
GitHub Releases están previstos.

### 3.3 Primer arranque (disponible en el simulador)

1. La aplicación comprueba el idioma (el del sistema por defecto; se admiten
   español e inglés) y muestra un asistente de bienvenida en línea la primera vez.
2. El asistente pide la **ubicación del observatorio**: latitud y longitud. Son
   necesarias para calcular dónde está el Sol; una ubicación equivocada desapunta
   el telescopio grados enteros.
3. Pide el **perfil**: focal del telescopio, apertura y longitud de la rendija,
   más el modelo de cámara y el tamaño de píxel. El perfil de referencia es 714
   mm, 80 mm de apertura, rendija de 7 mm, píxeles de 2 µm.
4. La cámara y la montura se descubren en segundo plano. El descubrimiento puede
   tardar un segundo o más porque habla con los SDK, así que nunca se ejecuta en
   el hilo de la interfaz.
5. Si falta un dispositivo, la aplicación dice qué falta y sigue con lo demás. Un
   simulador de cámara y otro de montura permiten explorar sin hardware.

### 3.4 Una sesión en una página (disponible en el simulador)

```
encender cámara + montura
        |
        v
bienvenida / ajustes: ubicación, perfil, idioma
        |
        v
panel de cámara: buscar una cámara, abrirla, restaurar el preset de ROI del perfil
        |
        v
1. Buscar el Sol: GOTO por efeméride, centrado grueso y fino sobre la rendija
        |
        v
2. Alineación polar: muestras de deriva en Dec, indicaciones de azimut y altitud
        |
        v
3. ROI: franja de captura, banda espectral, tilt, validación, FPS y caudal estimados
        |
        v
4. Escaneado: preparación (centrado fino + calibración de la tasa), barrido simple o
   mosaico, tres ciclos por defecto, progreso y contadores de frames perdidos
        |
        v
SER + scan_log.csv + scan_stats.jsonl + session_meta.json
        |
        v
recon rápido en pantalla + resumen de la sesión + abrir la carpeta
```

---

## 4. Flujo de sesión

### 4.1 El raíl, no un asistente modal

La vista principal es una **sesión por pasos**. Un raíl horizontal muestra el
estado de cada paso (pendiente, en curso, hecho, saltado). La navegación es
libre: el raíl guía, no bloquea. Todos los controles siguen visibles; no hay un
modo experto aparte. El estado se guarda en silencio tras cada cambio y un paso
completado se puede reabrir.

Esto importa porque una sesión es una secuencia de decisiones de puesta a punto, y
un formulario con todos los controles a la vez no le dice a quien empieza por
dónde ir. También importa porque un observador experto debe poder saltar directo
al ROI cuando el Sol ya está sobre la rendija.

**Estado**: Conectado (simulador). El raíl, la navegación libre y el autoguardado
silencioso corren en la ventana; los pasos mueven los motores reales con el
simulador.

### 4.2 Los cuatro pasos

| Paso | Qué hace | Por qué importa |
| --- | --- | --- |
| **Buscar el Sol** | GOTO al Sol por efeméride local y centrado grueso y fino sobre la rendija | El barrido necesita el disco sobre la rendija antes que nada |
| **Alineación polar** | Muestrea la Dec del Sol con el tiempo y separa el error de azimut del de altitud | Un mal seguimiento de día emborrona el disco y sesga la tasa de barrido |
| **ROI** | El usuario elige la franja de captura y la banda espectral; se mide el tilt y se valida el ROI | El ROI fija la tasa de fotogramas, el tamaño del SER y el caudal |
| **Escaneado** | Centrado fino, autocalibración de la tasa y barrido simple o mosaico | Aquí es donde se escriben los datos |

El centrado fino y la calibración de la tasa son **preparación dentro del paso
Escaneado**, no un quinto paso. El prototipo dejó esa lección: las dos
operaciones van juntas y ambas dependen de la exposición final.

**Estado**: Conectado (simulador). El raíl, la navegación libre y el autoguardado
silencioso corren en la ventana; los pasos mueven los motores reales con el
simulador.

---

## 5. Funciones

Cada función dice qué hace, por qué importa y cómo está pensado usarla. Toda
cifra de la interfaz debe venir con su significado; la guía sigue la misma regla.

La mayoría de las funciones están ahora **Conectado (simulador)**: el motor real
corre en la ventana contra el simulador. Su vía de hardware sigue siendo
**Previsto (MVP)**, y la validación en hardware sigue siendo la puerta antes de
darlas por hechas.

### 5.1 Descubrimiento y apertura de la cámara

**Estado**: Conectado (simulador). El panel de cámara abre hoy el simulador; una
cámara real sigue el mismo camino cuando su SDK está presente.

- **Qué hace**: el panel de cámara busca cámaras en todos los backends, lista lo
  que encuentra y abre la que eliges. El simulador siempre se encuentra y se
  etiqueta como tal, así que nunca se confunde con hardware.
- **Al abrir**: la aplicación restaura el preset de ROI de ese sensor desde el
  perfil, ajusta el rectángulo al sensor si el preset no cabe, y arranca el flujo.
  El panel muestra el modelo, el tamaño del sensor, el rectángulo que la cámara
  entrega de verdad y la tasa de fotogramas medida.
- **Por qué importa**: el ROI es una petición al hardware; de él salen la tasa de
  fotogramas y el tamaño del SER. Abrir una cámara es lo que convierte la interfaz
  de una vista previa en una sesión de captura, y restaurar el preset pone una
  franja buena conocida a un clic.
- **Descubrimiento**: habla con los SDK y corre en un hilo de trabajo, así que un
  backend lento nunca congela la ventana. Un SDK ausente aparece como un mensaje
  con el nombre del backend, y el diagnóstico de dispositivos lista a qué llega
  la compilación.
- **Cerrar**: para el flujo y cierra la cámara sin tocar la sesión ni el
  telescopio.

La tasa medida es la del motor, no la pedida al SDK: un driver puede aceptar una
petición que no puede sostener, y la tasa de barrido se calcula con lo que llega
de verdad.

### 5.2 Buscar el Sol y centrarlo en la rendija

**Estado**: Conectado (simulador).

- **Qué hace**: calcula la AR/Dec del Sol localmente a partir de la fecha y la
  ubicación del observatorio, apunta allí la montura y luego centra el disco
  sobre la rendija en dos etapas.
- **Dónde corre**: con una cámara abierta (ver §5.1) y la montura conectada. El
  botón **Apuntar al Sol y centrar** del panel de telescopio lo arranca; las
  etapas gruesa y fina informan del progreso y del error en Dec en arcosegundos.
- **Centrado grueso**: un *hill-climb* en Dec que maximiza la fracción de píxeles
  brillantes del fotograma vivo, un equivalente de la extensión iluminada del
  espectro. Es rápido y no necesita barrido.
- **Centrado fino**: simetría izquierda/derecha si el disco cabe a lo largo de la
  rendija; si no, el método de la cuerda, que necesita un barrido corto. La
  interfaz dice qué método se ejecutó.
- **Por qué importa**: la extensión iluminada es máxima en el centro pero su
  derivada es nula ahí (la cuerda cumple `L = 2·√(R² − q²)`), así que el
  histograma solo no puede resolver el centro. Es la **zona muerta**, un límite
  geométrico, no un problema de ajuste. La interfaz lo dice y encadena el paso
  fino.
- **Respaldo manual**: el panel de telescopio está siempre disponible para mover
  N/S/E/O, hacer GOTO por coordenadas, sync, seguimiento y park.

La efeméride local hace que el GOTO funcione sin red. Una ubicación equivocada es
la causa más común de un primer GOTO malo: revisa latitud y longitud antes de
culpar a la montura.

### 5.3 Alineación polar solar

**Estado**: Conectado (simulador). El asistente es un objeto de sesión real
(`shg.polar`); en el simulador sus muestras son sintéticas, así que las cifras
demuestran el cableado y la guía, no el cielo.

- **Qué hace**: con el Sol sobre la rendija y la montura siguiendo, muestrea la
  declinación del Sol cada pocos minutos, resta el movimiento propio del Sol
  (hasta unos 0.4"/min según la efeméride), ajusta la recta de deriva y deduce el
  error de **azimut** y **altitud**.
- **Guía**: indica cuánto girar cada tornillo, con la dirección, y pide una
  **segunda medida de confirmación** antes de dar la alineación por buena. La
  confirmación debe dejar los dos tornillos dentro de la tolerancia; si las
  muestras estaban demasiado cerca en ángulo horario, lo dice en vez de forzar un
  número.
- **Cuándo medir**: cerca del meridiano para la altitud, hacia el Este o el Oeste
  para el azimut. El Sol barre de Este a Oeste durante el día, así que repartir
  las muestras es lo que separa los dos errores.
- **Por qué importa**: Polaris no se ve de día, pero el SHG sigue necesitando un
  buen seguimiento. Este es el sustituto honesto: el propio Sol es la referencia.
- **Tiempo**: la medida es deliberadamente sin prisa; 20–40 minutos es el rango
  útil. Una medida más corta no separa azimut de altitud con confianza.

**Límite**: la geometría del Sol en una hora concreta limita cuánto de cada error
se puede separar. El asistente dice cuándo una medida es débil en vez de mostrar
una cifra segura que no lo es.

### 5.4 El ROI: la franja que hace posible el barrido

**Estado**: Conectado (simulador). Los rectángulos se envían al motor de captura
real y el preset se restaura del perfil al abrir la cámara; el simulador responde
al mismo contrato.

El SHG no usa todo el sensor. Una franja recortada, 3480×248 px en la
configuración de referencia, reduce el caudal y alcanza unos 120 fps. El ROI, por
tanto, decide si el barrido es posible, y SolarScribe lo trata como un
subsistema, no como un ajuste escondido.

Se distinguen cuatro regiones:

| Región | Qué es | Dónde vive |
| --- | --- | --- |
| ROI de captura | Lo que entrega la cámara; fija los FPS y el tamaño del SER | Píxeles de sensor, lo elige el usuario |
| ROI de análisis | Sub-regiones para medir (mitades izquierda/derecha, columnas del limbo, celdas de enfoque, ajuste del tilt) | Se calculan, nunca se guardan |
| Banda espectral | La franja útil del espectro; debe caber en el ROI de captura | Píxeles de frame |
| ROI de salida | Lo que se escribe al SER y lee el post-proceso | Igual que el ROI de captura |

Herramientas:

- **Editor en vivo**: overlay sobre el visor con asas arrastrables, campos
  numéricos y ajuste automático a la banda iluminada. **No hay propuesta
  automática**; decide el observador.
- **Presets** por cámara y óptica, guardados en el perfil y restaurados al abrir
  la cámara. Si un preset no cabe en el sensor, la aplicación lo ajusta y lo dice.
- **Aplicado, no solo guardado**: **Aplicar este ROI** envía el rectángulo de
  captura al motor de captura, que reinicia el flujo con él. El SER recibe
  exactamente ese rectángulo; el preset del perfil se reescribe para que la
  siguiente sesión empiece con la misma franja.
- **Validación** en lenguaje llano: recorte del orden, alineación
  rendija-espectro, altura del ROI frente al tilt medido, FPS y caudal estimados,
  límites del SDK (múltiplos, binning) y coherencia al cambiar el binning.
- **Registro**: el ROI efectivo y el tilt van a `session_meta.json` y
  `scan_log.csv`, para poder reproducir la toma.

**Por qué importa la altura**: el ROI debe contener la banda espectral más la
deriva por tilt más un margen. Una franja demasiado justa recorta el orden; la
validación lo dice antes del barrido en vez de dejar el descubrimiento al
post-proceso.

**Qué puede mostrar el editor y qué no**: el fotograma en pantalla ya es el ROI
de captura, así que el editor dibuja la banda espectral encima. Un rectángulo de
captura mayor que el fotograma sería ficción; el rectángulo entregado se cambia
en el panel de cámara.

### 5.5 Medición del tilt

**Estado**: Conectado (simulador), con una excepción honesta: el simulador no
tiene línea de rendija inclinada, así que el tilt lee unos 0,0°. El ajuste lo
ejercitan las pruebas unitarias; un fotograma real es lo que lo demuestra.

- **Qué hace**: ajusta una recta a la posición del borde de la rendija (o de una
  línea de absorción) a lo ancho del ROI. La pendiente es el tilt, expresado en
  **grados** y en **píxeles de deriva** a lo ancho del ROI.
- **Rectitud**: el ajuste también informa de lo recto que es el borde. Un borde
  ondulado significa que la cifra de tilt no es de fiar, y la interfaz lo dice en
  vez de mostrar un número.
- **Para qué se usa**: dimensionar la altura del ROI, guiarte para dejar la línea
  recta (idealmente cerca de 0°) y registrar el valor para el post-proceso.
- **Qué no hace**: la captura no endereza los fotogramas. Corregir el tilt es
  tarea del post-proceso, que lo hace mejor y no debe encontrar datos crudos ya
  modificados.
- **Cuándo se recalcula**: si cambia la óptica, el ROI o la orientación de la
  cámara.

### 5.6 Preparación del escaneado: centrado fino y calibración de la tasa

**Estado**: Conectado (simulador). La preparación real corre en un hilo de
trabajo, informa de su fase y deja el plan que usará el barrido.

Antes del primer fotograma de un barrido, el motor calcula un **plan** y ejecuta
tres pasos:

1. **Plan**: filas, tasa de barrido, fotogramas y duración prevista, mostrados
   antes de que nada se mueva. Un plan de mosaico se valida para cobertura.
2. **Centrado fino en Dec**: simetría cuando el disco cabe a lo largo de la
   rendija, cuerda en caso contrario. La interfaz dice qué método se ejecutó,
   porque uno necesita un barrido corto y el otro no.
3. **Autocalibración de la tasa de barrido**: cruza el disco, mide el tiempo de
   cruce contra el diámetro de la efeméride y escala la tasa de la montura para
   que el cielo se mueva exactamente un píxel por fotograma. Así se elimina la
   dependencia de que la focal configurada y la tasa de fotogramas reportada sean
   exactas.

El resultado se registra por barrido como `actual_xy`, cerca de 1.000 cuando el
muestreo es correcto. Una guarda rechaza una calibración que dejaría la tasa del
cielo más de 2× fuera del objetivo, para que una medida mala no arruine la
sesión.

**Por qué importa**: una reconstrucción estirada o comprimida es el fallo más
común del SHG, y es invisible hasta que se procesa la imagen. Calibrar antes del
barrido es lo que hace fiable el resultado.

**Honestidad en el simulador**: usa una tasa de barrido fija para que una demo
termine en segundos, y el resumen del plan lo dice. Solo la cámara real puede
demostrar la tasa.

### 5.7 Barrido simple y mosaico multífila

**Estado**: Conectado (simulador). El motor de barrido real calcula el plan, barre
y escribe la contabilidad; el simulador recorre el mismo camino con la grabación
desactivada.

- **Barrido simple**: un recorrido por el disco, un SER.
- **Mosaico**: varias filas en Dec, cada una con su SER, porque una altura de
  rendija puede no cubrir todo el disco. El paso entre filas sale de la geometría
  de la rendija, con un solape y un margen; el plan avisa si las filas exteriores
  no llegan al limbo.
- **Ciclos**: tres barridos por sesión por defecto. Tres bastan para descartar una
  toma mala sin doblar el tiempo de sesión.
- **Ciclos y recentrado**: cada ciclo es un barrido distinto. Antes del siguiente,
  la montura rebobina a la AR de inicio, lo cual es obligatorio, y, si está activo
  **Recentrar entre ciclos**, el Sol se centra otra vez primero. El rebobinado es
  lo que evita que los ciclos posteriores barran cielo vacío.
- **Pausa**: **Pausa** para la montura y retiene el barrido; **Reanudar** continúa
  donde se quedó, y los fotogramas ya escritos se conservan. El diseño también
  pausa automáticamente cuando el Sol se sale de la rendija; esa guarda automática
  sigue prevista (MVP).
- **Bordes**: una precarga corta en AR absorbe el juego antes de empezar a grabar;
  una parada adaptativa termina el barrido cuando el limbo de salida deja la
  rendija; cada fila del mosaico se dimensiona con la cuerda en su declinación, no
  con el diámetro completo.
- **Reintento**: el diseño mantiene un reintento para un barrido fallido con el
  intento fallido preservado; el motor actual se detiene en el primer fallo y
  comunica su código de motivo. El reintento está previsto (MVP).

**Estado de los cuatro detalles de borde**: conectado (simulador), como el resto
del barrido.

**En el simulador**: la grabación SER está desactivada a propósito, así que una
tanda es un modo seco. La ventana lo dice al terminar el barrido; ningún fichero
finge ser una captura.

### 5.8 Exposición, binning y profundidad de bits

**Estado**: Conectado (simulador). El motor de captura aplica los ajustes a la
cámara; un valor rechazado vuelve como mensaje, no como un cambio silencioso.

- **Autoexposición**: lleva la media a una fracción del rango completo, un cuarto
  por defecto. Un cuarto llena el histograma y deja margen para las estructuras
  brillantes de la cromosfera, que no deben saturar.
- **Ajuste manual**: exposición en microsegundos, ganancia y offset como índices
  del propio SDK. La ganancia se escala distinto en cada marca, así que viaja con
  el modelo de cámara en el perfil.
- **Binning**: 1×1 por defecto. El SHG necesita la resolución espacial completa a
  lo largo de la rendija; cambiar el binning revalida el ROI.
- **Profundidad de bits**: 16 bits por píxel. Es el contrato con el post-proceso,
  no una preferencia.
- **Ajustes rechazados**: si la cámara rechaza la exposición, la ganancia o el
  binning, la sesión dice cuál y conserva el valor anterior. El detalle técnico va
  al registro.

### 5.9 Visualización del barrido, recon rápido y resumen

**Estado**: Conectado (simulador). La visualización sigue el progreso real del
barrido y el resumen sale del resultado del barrido.

- **Durante el barrido**: el visor muestra la franja ya capturada, la línea de la
  rendija y el porcentaje completado, sobre un **disco esquemático** que funciona
  sin red. Si hay conexión, la imagen real del Sol del día (SDO) puede sustituir
  al disco esquemático. El porcentaje se refiere al barrido previsto, así que 100%
  significa que el plan terminó, no que la imagen esté procesada.
- **A medida que avanza el barrido**: un **recon rápido**, calculado por la capa
  SHG con `shg.quick_recon`. Colapsa la banda espectral de cada fotograma en un
  perfil y apila los perfiles en el tiempo formando un disco; la ventana pinta el
  resultado en pantalla mientras corre el barrido. La leyenda dice cuántos
  fotogramas y filas entraron.
- **Qué no es el recon rápido**: calibrado, alineado, corregido de flat ni
  fotométrico. No se exporta, no relee el SER y no sustituye al post-proceso.
- **Cuando no se puede construir**: la ventana dice por qué en lenguaje llano,
  con un motivo estable detrás: demasiado poco contraste para mostrar un disco,
  todavía no hay fotogramas, la banda espectral no tiene píxeles, o los
  fotogramas no permiten construir la vista previa. El motivo nombra el paso que
  hay que revisar.
- **Resumen**: fotogramas capturados, fotogramas perdidos, duración y ruta de la
  sesión, con un botón para abrir la carpeta de la sesión.

**Honestidad**: el recon rápido no es autoritativo. Si se ve bien, los datos
probablemente sirven; si se ve mal, el motivo suele estar en los registros, y el
resumen apunta allí. La leyenda "vista previa ligera, no para medir" forma parte
del widget a propósito.

### 5.10 Panel de salud y contadores de rendimiento

**Estado**: Conectado (simulador). Los contadores salen del motor de captura
real; con el simulador demuestran el cableado, no la tasa sostenida.

Un barrido a 120 fps sobre la franja de referencia mueve unos 207 MB/s, así que
la salud del flujo no es un detalle. El panel muestra, en lenguaje llano:

| Cifra | Qué significa | Presupuesto |
| --- | --- | --- |
| FPS reales | Fotogramas por segundo recibidos de verdad | ≥ 120 en el ROI de referencia |
| Perdidos por el SDK | Fotogramas que el driver de la cámara dice haber perdido | ≤ 0,1% por barrido |
| Perdidos por la cola | Fotogramas perdidos porque el disco no daba abasto | Parte del mismo 0,1% |
| Huecos de secuencia | Saltos en la numeración de fotogramas que ve el host | 0 en condiciones nominales |
| Pico de la cola | Cuánto se acercó la cola de grabación a su techo de 512 MB | Estable, sin quedarse en el techo |
| Caudal de disco | Megabytes por segundo escritos mientras se graba | ≥ 250 MB/s sostenidos |
| Latencia del visor | Retardo entre la captura y la pantalla | ≤ 150 ms |

Cada cifra es un hecho con su comparación. Un contador de pérdidas sin su
presupuesto es ruido para el observador, así que el panel nunca muestra uno solo.
La latencia del visor forma parte del presupuesto, pero la mide el banco de
rendimiento, no un contador en vivo del panel.

**En el simulador** la cifra demuestra que el pipeline está conectado; solo una
cámara real puede demostrar 120 fps y 207 MB/s. El panel dice cuál de las dos
cosas está mirando.

### 5.11 Calendario del cielo, pestaña Sol

**Estado**: Disponible. Las cifras se calculan localmente a partir de la posición
del observatorio; la imagen SDO opcional necesita red.

En **Herramientas → Calendario del cielo… → Sol** viven juntas las utilidades
solares:

- El diámetro aparente y el tamaño angular del Sol para la fecha. Alimentan la
  geometría del barrido, así que un valor calculado para hoy es mejor que uno
  fijo.
- El **ángulo de posición del polo norte solar P**, en grados. Dice cuánto se
  inclina el polo norte hacia el este o el oeste en el cielo, y el post-proceso lo
  usa para orientar la imagen reconstruida.
- La **latitud heliográfica B0 y la longitud de Carrington L0** del centro del
  disco. Dicen qué parte del Sol cruza la rendija.
- El número de **rotación de Carrington**, para comparar imágenes de la misma
  región entre rotaciones.
- Regiones activas (NOAA).
- Una imagen real del Sol (SDO) opcional para el calendario y la visualización
  del barrido.

**Sin red** la pestaña sigue funcionando: la efeméride y las cifras P, B0 y L0 son
locales, y la visualización recurre al disco esquemático. Si falta el módulo de
efemérides, las cifras se ocultan en vez de inventarse.

### 5.12 Perfiles, ajustes e idioma

**Estado**: Conectado (simulador). El perfil lo lee y lo escribe el almacén de
configuración; el diálogo de ajustes edita el mismo esquema.

- **Un solo perfil**, no una lista de perfiles que compiten: datos del telescopio
  (focal, apertura, longitud de rendija), datos de la cámara (modelo, tamaño de
  píxel, binning) y presets de ROI por cámara y óptica.
- **Presets de ROI** restaurados al abrir la cámara y reescritos al aplicar un
  ROI, para que la siguiente sesión empiece con la misma franja. Un preset que no
  cabe en el sensor se ajusta y se avisa.
- **Ajustes INI** heredados de `nightscribe-scan`, más las claves nuevas de ROI,
  tilt, montura, límites de captura y sesión. Cada clave tiene un valor por
  defecto y una explicación, así que un fichero editado a mano nunca impide
  arrancar.
- **Editable a mano**: el fichero es texto plano. Un valor que no se puede
  interpretar vuelve a su defecto, y el diálogo de ajustes explica qué controla
  cada clave.
- **Idioma**: el del sistema por defecto, con español e inglés disponibles.
  Cambiarlo pide reiniciar la aplicación para que recargue sus catálogos.

**Limitación conocida**: las explicaciones del diálogo de ajustes son los textos
`why` del esquema de configuración. En esta compilación están solo en inglés; las
etiquetas y el resto de la interfaz están traducidos. Las etiquetas no cambian
los hechos que explica el tooltip.

### 5.13 Modo seco y simuladores

**Estado**: Disponible. `--dry-run` comprueba la geometría sin abrir la cámara ni
mover la montura; el simulador de la interfaz ejecuta los motores reales contra un
cielo sintético.

- **Modo seco**: la montura se mueve y el motor mide, pero no se graba nada. Es la
  forma segura de ensayar una sesión, y es útil sin cámara o con el cielo nublado.
- **Simulador de espectro solar**: la ventana usa la `SimCamera(pattern="solar")`
  de primera clase, acoplada a la montura simulada, así que el disco dibujado se
  mueve con Dec y AR y los bucles reales de centrado y barrido convergen. **No
  tiene línea de rendija inclinada**, así que el tilt lee unos 0,0° en el
  simulador; el medidor de tilt lo ejercitan las pruebas unitarias. Las filas de
  la banda espectral están fijas en la banda de referencia, así que la vista
  previa muestra lo que produciría esa banda.
- **Simulador de cámara**: la misma `SimCamera` a través del contrato `Camera`,
  así que el motor de captura, los contadores y el visor toman el camino real.
- **Simulador de montura**: una montura que informa de su posición y acepta tasas,
  así que todo el flujo de sesión se puede ejercitar sin hardware.

**Límites honestos**: el simulador no es un instrumento radiométrico. Usa una tasa
de barrido fija para que una demo termine en segundos, y la grabación SER está
desactivada a propósito, así que una tanda simulada es un modo seco. Solo el
hardware real puede demostrar la tasa, el ruido y el caudal de disco.

Los simuladores son también lo que hace posibles las pruebas automáticas, y por eso
forman parte del diseño del producto y no son un añadido.

### 5.14 Ayuda al enfoque

**Estado**: el diálogo está en la interfaz; la rutina completa y sus pruebas
están previstas (fase 2).

Los indicadores de enfoque siguen la rutina del SHG-700:

1. **Espectrógrafo**: maximizar el contraste y el gradiente de las líneas de
   absorción. H-alpha es la línea principal.
2. **Colimador**: maximizar la nitidez del borde de la rendija y minimizar su
   planitud.
3. **Telescopio**: maximizar el contraste, el gradiente y el número de estructuras
   de la superficie.

Los indicadores se calculan en los dos ejes, así que la orientación de la cámara
no importa. El diseño reserva la rutina completa para la fase 2; el diálogo de la
interfaz actual muestra el nivel medio y el contraste del fotograma en vivo, que
son los dos indicadores que más importan.

### 5.15 Diagnóstico de dispositivos y backends de montura adicionales

**Estado**: el modo `--diagnostics` está disponible en esta compilación; los
backends de montura adicionales están previstos (fase 3).

- Un modo de **diagnóstico de dispositivos** informa de qué SDK y backends se
  encontraron, qué declara cada cámara y qué acepta la montura. Se ejecuta con
  `python -m solarscribe --diagnostics` e imprime las rutas, la óptica, los
  presets de ROI y el estado de la capa de dispositivos.
- Backends de montura adicionales: respaldo directo por serie (LX200, OnStep) e
  INDIGO.

Los backends adicionales no hacen falta para barrer con el equipo de referencia,
y por eso llegan después del MVP.

---

## 6. Criterios de aceptación

Una toma se considera buena cuando pasan estas comprobaciones. Son los mismos
criterios que usa el prototipo, más los que SolarScribe añade para el ROI y el
presupuesto de rendimiento.

| Comprobación | Criterio | Por qué |
| --- | --- | --- |
| `actual_xy` en `scan_log.csv` | 0,97–1,03 | El muestreo en X es 1:1; fuera de ese rango la reconstrucción sale estirada o comprimida |
| FPS medidos frente a usados | Menos del 2% | La tasa de barrido se calcula a partir de la tasa de fotogramas |
| `frames_short_pct` | Cerca de 0 | Los fotogramas que faltan son huecos en la reconstrucción |
| Frames perdidos por barrido | ≤ 0,1% | El presupuesto de ADR-013 |
| Huecos de secuencia | 0 en condiciones nominales | Un hueco es un fotograma que el host nunca vio |
| Avisos `CONSISTENCY` | Ninguno | Un cambio de escala entre barridos hace que las filas no concuerden |
| Dispersión de Dec por fila del mosaico | Menos de 10" | Las filas deben encajar sin escalón |
| Tilt registrado | Presente en `session_meta.json` | El post-proceso lo necesita para corregir la geometría |
| Altura del ROI | Banda + deriva por tilt + margen | Un ROI justo recorta el orden |
| Registros de sesión | Las mismas columnas que `nightscribe-scan`, sin quitar ninguna | El post-proceso existente sigue valiendo |
| Perfil escrito a mano | La aplicación arranca con todos los defectos | Un perfil es un dato, no un programa |
| Traducciones | 0 cadenas sin traducir en ES y EN | La interfaz es bilingüe desde el primer día |

**Estado**: la geometría se puede comprobar en el simulador; la tasa, los
fotogramas perdidos y las cifras de disco necesitan hardware real. La tabla es el
objetivo de una toma real, no la afirmación de que cada cifra se haya medido.

---

## 7. Paridad con `nightscribe-scan`

SolarScribe debe cubrir todas las funciones del prototipo, salvo las dos que
quedan fuera por diseño: el motor de captura de SharpCap, que SolarScribe
sustituye por el suyo, y las herramientas de post-proceso.

| # | Función de `nightscribe-scan` | SolarScribe |
| --- | --- | --- |
| 1 | Autocalibración de la tasa por el tiempo de cruce del limbo | Conectado (simulador) |
| 2 | Diámetro solar por efeméride local y UTC de cada barrido | Conectado (simulador) |
| 3 | Escala del eje de la rendija en vivo y paso del mosaico | Conectado (simulador) |
| 4 | Vigilancia del barrido: espera abortable, detección de stall, guarda de disco, contabilidad de frames, un reintento | Conectado (simulador); reintento previsto (MVP) |
| 5 | Comprobaciones de consistencia entre barridos | Conectado (simulador) |
| 6 | `scan_log.csv`, `scan_stats.jsonl`, `session_meta.json` | Conectado (simulador) |
| 7 | Panel de control con perfiles y configuración | Disponible en el simulador, como sesión PySide6 |
| 8 | Ayuda al enfoque | Diálogo presente; rutina completa prevista (fase 2) |
| 9 | Barrido simple y mosaico multífila con centrado en Dec por cuerdas | Conectado (simulador) |
| 10 | Bucle de autoexposición | Conectado (simulador) |
| 11 | Centrado en Dec: bucle izquierda/derecha y cuerda | Conectado (simulador) |
| 12 | Geometría del mosaico: longitud de rendija, magnificación, solape, margen, barridos por fila, backlash | Conectado (simulador) |
| 13 | Precarga de AR, parada adaptativa del limbo de salida, padding | Conectado (simulador) |
| 14 | Corrección de la tasa de AR por `1/cos(Dec)` | Conectado (simulador) |
| 15 | Detección del limbo por desviación típica | Conectado (simulador) |
| 16 | Medida de la extensión de rendija y de las medias izquierda/derecha | Conectado (simulador) |
| 17 | Perfiles y ajustes persistidos | Conectado (simulador) |
| 18 | ROI de captura | Conectado (simulador), como editor de ROI en vivo |
| 19 | Medición de tilt | Conectado (simulador), nuevo en SolarScribe |
| 20 | Alineación polar solar | Conectado (simulador), nuevo en SolarScribe |
| 21 | Buscar el Sol: GOTO por efeméride y centrado grueso por histograma | Conectado (simulador) |
| 22 | Motor de captura y grabador SER | Conectado (simulador) |
| N/A | `tools/align_stack_recon.py`, `tools/mosaic_from_recon.py` | Fuera de alcance: post-proceso externo |

Algunas filas merecen una nota:

- **Fila 7**: el panel HTML del prototipo se sustituye por la sesión nativa, pero
  las funciones son las mismas: perfiles, ajustes, arranque y parada.
- **Fila 18**: en el prototipo el ROI se ajusta en SharpCap. En SolarScribe es un
  paso de primera clase, con validación y tilt medido.
- **Filas 19 y 20** son añadidos, no elementos de paridad. Existen porque el
  diseño cierra dos huecos que el prototipo dejaba abiertos.
- **Las herramientas de post-proceso** no se portan. SolarScribe las alimenta,
  con las mismas columnas y el mismo formato SER.

---

## 8. Cuando algo va mal

Cada función de SolarScribe existe para detectar o corregir un fallo concreto.
Este es el mapa.

| Síntoma | Causa típica | Qué hace SolarScribe | Qué haces tú |
| --- | --- | --- | --- |
| Reconstrucción elíptica (X/Y ≠ 1) | Tasa de barrido o escala de rendija | Autocalibra X, mide `S_Y`, registra `actual_xy` | Revisa `actual_xy`; si está cerca de 1, el problema está en el eje de la rendija |
| Las filas del mosaico no encajan | Paso en Dec con la escala equivocada | Mide la escala de rendija y registra la Dec real de cada fila | Usa los desplazamientos medidos en la herramienta de mosaico |
| Una fila con otra escala | Los FPS o la escala cambiaron entre barridos | Emite un aviso `CONSISTENCY` | Busca qué cambió en la captura, o deja que la herramienta de mosaico reescale como último recurso |
| SER vacío o sin datos | Disco lleno, driver colgado | Guarda de disco, vigilancia de stall, SER preservado y un código de motivo | Libera espacio, revisa el enlace USB, sube `stall_timeout_s` solo si el hardware es lento |
| Faltan fotogramas | Ancho de banda USB o límite del driver | Compara los fotogramas escritos con duración × fps y avisa `FRAMES SHORT` | Baja la tasa, acorta la exposición o revisa el cable |
| Apilado blando | Deriva en Dec entre fotogramas | Recentrado en Dec y deriva en el registro | Revisa `dec_start`; mejora la alineación polar |
| Costura de brillo en un mosaico | La exposición cambió entre filas | Fija la exposición una vez por sesión | Usa la opción de normalización de la herramienta de mosaico |
| Deriva de seguimiento con el tiempo | Alineación polar | Resumen de deriva al final de la sesión | Ajusta azimut o altitud como se indicó |
| El Sol se sale de la rendija a mitad del barrido | Error de seguimiento o un golpe | Pausa, avisa y espera | Recentra con el panel de telescopio y continúa |
| La aplicación arranca sin cámara ni montura | Falta un SDK o el backend de la plataforma | Dice qué falta y sigue funcionando | Instala el SDK o el backend; usa el simulador para explorar |

**Estado**: los comportamientos están previstos; el texto de la interfaz se
escribirá con el código y se traducirá con el resto de las cadenas.

---

## 9. Ficheros y registros

**Estado**: Conectado (simulador). El motor de barrido escribe los tres registros
y el SER en una captura real; el simulador no graba SER, así que su carpeta de
sesión contiene el estado, los registros y el resumen, pero ningún fichero SER.
Los formatos se heredan de `nightscribe-scan`; las columnas nuevas se añaden,
nunca sustituyen a las antiguas.

### 9.1 La carpeta de sesión

Una carpeta por sesión, nombrada con su fecha y hora, dentro de una carpeta base
configurable. Los ficheros se llaman:

```
sun_AAAAMMDD_HHMM_scanNN.ser    un fichero por barrido o por fila del mosaico
scan_log.csv                    una fila por barrido, reescrita tras cada barrido
scan_stats.jsonl                una muestra JSON por barrido
session_meta.json               la configuración efectiva y la geometría
session_state.json              la memoria de la aplicación sobre los cuatro pasos
```

La ortografía de arriba es la que fija el contrato de configuración. La ubicación
exacta de la carpeta se resuelve por plataforma (ver la guía de instalación).

### 9.2 Qué hay en el SER

Un fichero SER estándar: ancho, alto, profundidad de bits, color ID y marcas de
tiempo por fotograma, con 16 bits por píxel en el MVP. El ROI de captura no es un
campo estándar del SER, así que se registra en `session_meta.json`, junto al
fichero.

### 9.3 Los tres registros

- **`scan_log.csv`**: una fila por barrido, reescrita tras cada barrido. Es el
  fichero que se lee primero cuando una toma parece mala.
- **`scan_stats.jsonl`**: las mismas métricas por barrido en JSON, una muestra por
  barrido, pensado para scripts y gráficas.
- **`session_meta.json`**: la configuración efectiva, la calibración, la geometría
  de rendija, el plan del mosaico, el ROI, el tilt, la versión de la aplicación y
  los contadores de frames perdidos.

Campos que conviene conocer, porque responden a las preguntas habituales:

| Campo | Qué te dice |
| --- | --- |
| `actual_xy` | Si el muestreo en X es 1:1; alrededor de 1.000 es correcto |
| `frames_short_pct` | La fracción de fotogramas que faltan frente a duración × fps |
| `problem` | El código de motivo de un barrido fallido; vacío cuando salió bien |
| `dec_offset_measured_arcsec` | La Dec real de una fila del mosaico |
| `slit_extent_px` | La extensión iluminada a lo largo de la rendija, la escala Y |
| `calibration_factor` | La corrección que aplicó la calibración de la tasa |

### 9.4 Dos ficheros que se confunden con facilidad

- **`session_state.json`** es la memoria de la aplicación: qué paso está hecho,
  qué números se midieron, dónde está la sesión. Se guarda en silencio y se puede
  descartar sin perder datos.
- **`session_meta.json`** es el contrato con el post-proceso: la geometría
  efectiva y la versión, con columnas estables. No es estado de la aplicación.

Mantenerlos separados es deliberado. Un paso se puede reabrir sin tocar el
registro de la toma, y el post-proceso nunca depende de cómo recuerda las cosas
la interfaz.

---

## 10. A fondo: cómo funciona y por qué

Esta sección reúne la geometría y el razonamiento, para que el comportamiento se
pueda entender y diagnosticar sin abrir los documentos de diseño.

### 10.1 Geometría del barrido y muestreo en X

Un SHG reconstruye una columna de imagen por fotograma capturado. Para que la
reconstrucción sea 1:1, el cielo debe moverse exactamente un píxel por fotograma:

```
velocidad_barrido ("/s) = escala_pixel ("/px) × fps (fotogramas/s)
multiplicador (×)       = velocidad_barrido / tasa_sidérea
```

`escala_pixel = 206265 × (tamaño_pixel_um / 1000) / focal_mm`.

Para la configuración de referencia: píxeles de 2 µm a 714 mm dan unos 0,578"/px;
a 120 fps son unos 69,3"/s, o 4,61× la tasa sidérea. El diámetro solar de unos
1934,8" ocupa entonces unos 3349 px, que coincide con la franja de referencia.

Dos trampas:

- La focal debe ser la focal **efectiva** en el sensor, medida sobre una
  reconstrucción nativa. Una escala de procesado copiada de una herramienta de
  post-proceso no es la focal física y escalará toda la imagen en X.
- La montura se mueve en coordenadas AR, así que la tasa real en el cielo es
  `tasa × cos(Dec)`. La corrección divide por `cos(Dec)`, lo que mantiene la
  escala X igual en cualquier declinación.

### 10.2 Efeméride y autocalibración de la tasa

El diámetro aparente del Sol cambia alrededor de un 3% a lo largo del año.
SolarScribe lo calcula a partir de la fecha con una efeméride local de baja
precisión, con un error de unos 0,01%, y registra el UTC de cada barrido para
poder recalcular el valor exacto después. Si la configuración fuerza un valor, el
registro lo dice; si la efeméride falla, se usa un respaldo y se anota.

Al empezar la sesión, una vez fijada la exposición, el motor mide la tasa real de
fotogramas y luego **autocalibra la tasa de barrido**: cruza el disco, mide el
tiempo de cruce contra el diámetro de la efeméride y escala la tasa de la montura
para que el cielo se mueva exactamente un píxel por fotograma. Así se elimina la
dependencia de que la focal y los FPS reportados sean exactos.

La calibración mide la tasa del cielo mientras se mueve a un múltiplo conocido de
la tasa científica, y escala por la tasa por unidad, no por el cociente bruto. El
prototipo lo hizo mal una vez y el barrido salió varias veces demasiado lento. Una
guarda rechaza una corrección que dejaría la tasa del cielo más de 2× fuera del
objetivo.

La misma efeméride local devuelve las cifras de rotación que muestra el calendario
del cielo: **P**, el ángulo de posición del polo norte solar (positivo hacia el
este), **B0**, la latitud heliográfica del centro del disco, y **L0**, su longitud
de Carrington. P orienta la imagen reconstruida; B0 y L0 dicen qué parte del Sol
cruza la rendija. Siguen las coordenadas solares de baja precisión de Meeus y se
comprueban contra el ejemplo publicado (P = 26,27°, B0 = +5,99°, L0 = 238,63° en
JD 2448908.5). No necesitan red.

### 10.3 El eje de la rendija y la anisotropía de la reconstrucción

En la reconstrucción, X es el barrido e Y es la rendija. Los dos ejes no
comparten escala de placa: la magnificación de la imagen de la rendija no es
necesariamente 1, así que el disco puede salir bastante más ancho que alto. En la
configuración de referencia la relación es de unas 1,28, con Y comprimida.

Con el disco centrado, SolarScribe mide la extensión iluminada a lo largo de la
rendija y deduce `S_Y = diámetro_solar / extensión_px`. La corrección es
**estirar Y**, no cambiar la tasa de la montura. Confundir las dos cosas es lo que
hace que el paso del mosaico salga mal aunque cada barrido individual se vea bien.

### 10.4 Centrado en Dec, zona muerta y cuerda

Dos métodos se reparten el trabajo:

- **Bucle izquierda/derecha**: parte el fotograma en dos mitades y compara su
  brillo medio, `offset = (L − R) / (L + R)`. Solo vale cuando el disco cabe a lo
  largo de la rendija. Cuando el disco desborda el fotograma, las dos mitades están
  llenas de disco, la métrica pierde su cruce por cero y el bucle puede empujar el
  Sol fuera de la rendija.
- **Método de la cuerda**: el intervalo en AR entre el limbo de entrada y el de
  salida es la cuerda del disco en la declinación de la rendija. Con `R` el radio
  solar, `S` la longitud efectiva de la rendija y `q` el desplazamiento firmado en
  Dec del centro de la rendija:

```
e = max(0, |q| − S/2)          borde de rendija más cercano al centro del disco
L = 2 × √(R² − e²)             la cuerda medida
|q| = e + S/2                  fuera de la zona muerta
```

Mientras la rendija abarca el centro del disco (`|q| ≤ S/2`), la cuerda es el
diámetro completo y no cambia con el desplazamiento. Es la **zona muerta**. Es
geometría, no ajuste. La rutina avanza en Dec hasta que el borde más cercano está
lo bastante lejos del centro, y luego sondea para saber de qué lado estaba la
rendija. Cuando el disco cabe en la rendija, la rutina de cuerda delega en el
bucle izquierda/derecha, más barato.

El centrado grueso por histograma hace rápida la puesta a punto pero no puede
eliminar la zona muerta. La interfaz lo dice, y el paso fino termina el trabajo.

### 10.5 Geometría del mosaico

```
slit_px = slit_mm × magnificación × 1000 / tamaño_pixel_um
strip   = min(ancho_roi, slit_px) × escala_pixel / magnificación
step    = strip × (1 − solape)
margin  = max(margen_configurado, incertidumbre)
rows    = 1                                              si strip ≥ diámetro
rows    = ceil((diámetro + 2 × margin − strip) / step) + 1 en caso contrario
```

`magnificación` es la magnificación de la imagen de la rendija, medida en vivo
cuando es posible. Las filas se colocan simétricamente alrededor de la
declinación centrada. Cuando una fila ya contiene todo el disco, el número de
filas se fuerza a 1. El plan se valida para cobertura y avisa si las filas
exteriores no llegan al limbo. Una fila de margen que no encuentra disco se salta;
si ocurre después de haber capturado datos, se trata como el borde de salida y el
mosaico termina.

### 10.6 Tilt y altura del ROI

Una recta ajustada al borde de la rendija da una pendiente. La deriva a lo ancho
del ROI, `W`, es:

```
deriva_px = W × tan(tilt)
altura    = altura_banda + |deriva_px| + márgenes
```

La fórmula explica por qué una línea inclinada obliga a una franja más alta. La
captura mide el tilt, lo usa para validar la altura, te guía para enderezar la
rendija y lo registra. No endereza los datos. El post-proceso tiene los datos
crudos y la cifra que necesita para corregir la geometría sin una segunda
interpolación.

### 10.7 Por qué la alineación polar se mide en el Sol

De noche, la alineación polar usa Polaris. De día no hay Polaris, pero el Sol es
una referencia precisa en Dec sobre la rendija. El asistente muestrea su
declinación, resta el movimiento propio del Sol según la efeméride y ajusta la
deriva residual. Los errores de azimut y altitud producen patrones de deriva
distintos según la hora angular del Sol; por eso el asistente recomienda medir
cerca del meridiano para la altitud y hacia el Este o el Oeste para el azimut, y
por eso reparte las muestras en 20–40 minutos.

Hace falta una segunda medida antes de aceptar el resultado. Es más lento que una
lectura única, y es la única forma de distinguir una corrección real del ruido.

### 10.8 Hilos, pérdidas y presupuesto de rendimiento

El hilo de captura hace una sola cosa: obtener un fotograma del SDK y entregarlo
a consumidores en línea baratos. La cola de grabación es acotada a propósito. Un
disco lento cuesta fotogramas que se cuentan, nunca un hilo de captura bloqueado.
El visor es un buzón de un fotograma: una interfaz lenta descarta fotogramas de
vídeo en vez de acumularlos.

Las pérdidas se cuentan en tres sitios: dentro del SDK, al desbordar la cola y
como huecos en la secuencia de fotogramas que ve el host. Las tres aparecen en el
panel de salud y en los registros, porque un solo número escondería dónde se
perdió.

El presupuesto provisional para el ROI de referencia es 120 fps, unos 207 MB/s,
como mucho un 0,1% de fotogramas perdidos por barrido, 150 ms de latencia de
visor, una cola acotada de 512 MB, al menos 250 MB/s de disco sostenidos y un
arranque de captura en 5 s. Se mide en la fase 0 y se corrige con números reales;
la interfaz compara cada cifra con él.

**El recon rápido es barato a propósito.** La banda de cada fotograma se promedia
a lo largo del eje de dispersión, lo que deja una intensidad por posición de
rendija; esos perfiles se apilan en el tiempo, y en la posición de barrido `x` la
longitud iluminada de la rendija es la cuerda `2·√(R² − x²)`. El resultado se
reduce y se normaliza de 0 a 1. La información espectral desaparece, no hay
alineado, ni flat, ni corrección `1/cos(Dec)`, ni fotometría, y no se exporta
nada. Por eso puede correr mientras la sesión continúa y por eso no debe
confundirse con el resultado.

### 10.9 Red y privacidad

Las efemérides se calculan localmente. La red se usa solo, opcionalmente, para la
imagen real del Sol del día (SDO) en el calendario y la visualización. Sin
conexión se muestra el disco esquemático y todo lo demás funciona. No hay
telemetría: no se envía nada a ningún sitio.

### 10.10 Idioma y traducción

Se admiten español e inglés desde el primer día. Toda cadena visible pasa por el
mecanismo de traducción de Qt, los catálogos se regeneran cuando cambian las
cadenas y los dos idiomas deben quedarse en cero cadenas sin traducir. El idioma
sigue al sistema por defecto y se puede cambiar en los ajustes.

Las cifras de la interfaz se traducen como frases, nunca como códigos desnudos:
el motor informa de un código de motivo estable y la interfaz lo convierte en una
frase con sus números.

---

## 11. Límites y honestidad

Estos son los límites que conviene conocer antes de fiarse de una toma:

- **La tasa es una propiedad del hardware.** El presupuesto de 120 fps es un
  objetivo para la franja de referencia, no una promesa para cualquier cámara,
  cable o disco.
- **El histograma tiene zona muerta.** El centrado grueso es rápido pero no
  resuelve el centro; hace falta el paso fino.
- **La alineación polar lleva tiempo.** Una medida corta no separa azimut de
  altitud, y el asistente lo dice en vez de inventar precisión.
- **El tilt se mide, no se corrige.** Los fotogramas crudos siguen crudos; el
  post-proceso aplica la corrección.
- **El recon rápido no es el resultado.** Responde a "¿salió la toma?", no a "¿cómo
  está el Sol?".
- **SolarScribe no hace post-proceso.** El recon, el apilado y el mosaico siguen
  siendo externos.
- **El MVP no cubre todas las marcas de cámara.** Los cuatro backends nativos y el
  simulador son el plan; los backends genéricos de cámara llegan después.
- **Los motores están probados contra el simulador, no contra el cielo.** Todo lo
  marcado como Conectado (simulador) está enganchado pero no se ha validado en
  hardware real, y aún puede cambiar con un ADR. Lo marcado como Previsto todavía
  no está conectado.

---

## 12. Referencias

- [Guía de instalación](../install/INSTALACION.md).
- [Registro de cambios](../../CHANGELOG.es.md).
- [Diseño](../../design/DESIGN.md) y
  [contratos entre capas](../../design/ARCHITECTURE.md).
- [Índice de ADRs](../../design/adr/README.md). Las decisiones más visibles aquí:
  ADR-006 (centrado), ADR-007 (alineación polar), ADR-010 (ROI), ADR-011 (pasos de
  sesión), ADR-013 (rendimiento), ADR-018 (contrato con el post-proceso), ADR-019
  (montura), ADR-020 (resultado), ADR-021 (red), ADR-022 (tilt).
- Guía de usuario y herramientas de `nightscribe-scan`, el prototipo al que esta
  aplicación sustituye en la captura.
