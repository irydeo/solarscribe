# Registro de cambios

Todos los cambios notables de SolarScribe se documentan aquí. El formato sigue
[Keep a Changelog](https://keepachangelog.com/) y el proyecto se rige por
[Versionado semántico](https://semver.org/lang/es/).

## [Sin publicar]

### Añadido

- **Capa de contratos v1** (ADR-012, ADR-023): `devices/abc.py` (cámara, montura
  y gestor de dispositivos), `capture/abc.py` (motor, escritor SER, modelo de
  ROI), `shg/abc.py` (motor de barrido, puertos, medidor de tilt) y
  `config/schema.py` (esquema INI, perfil y estado de sesión). Allí quedan fijados
  los tipos de valor, los protocolos, las unidades y los códigos de motivo.
- **Soporte de configuración y perfiles**: el esquema INI con la sección, el
  tipo, el valor por defecto, la explicación y el origen de cada clave; el perfil
  JSON v2 con datos del telescopio, datos de cámara y presets de ROI; y el estado
  persistente de los cuatro pasos de sesión. `config/store.py` los lee y los
  escribe con un valor por defecto para cada clave ausente, escritura atómica,
  migración de perfil v1 a v2 y el nombrado de los ficheros de sesión;
  `config/paths.py` resuelve las carpetas por plataforma.
- **Test de la regla de dependencias** `tests/unit/test_layers.py`: analiza las
  fuentes con `ast` y falla si una capa importa hacia arriba, si Qt aparece fuera
  de `ui`, si `ctypes` aparece fuera de `devices` o si un módulo de contrato
  pierde un nombre de su superficie.
- **Catálogos Qt Linguist ES/EN** en `solarscribe/ui/i18n/`, más el flujo de
  extracción y compilación (`pyside6-lupdate` / `pyside6-lrelease`), documentado
  en `docs/README.md`.
- **Guía de usuario y guía de instalación**, en español e inglés, con el estado
  de cada función por escrito: disponible, conectado (simulador), previsto (MVP),
  previsto (fase 2/3) o solo diseño.
- **Registro de cambios bilingüe** (`CHANGELOG.md` / `CHANGELOG.es.md`).

### Cambiado

- **Interfaz imagen primero de cinco pasos** (ADR-026, ADR-028): el visor ocupa la
  mayor parte de la ventana, el raíl es una sola línea de 28 px con cinco pasos
  (Buscar Sol, Polar, Enfoque, ROI, Barrido), el panel lateral está acotado y los
  paneles de cámara, telescopio y salud se pliegan. Se retiran el ampliador del
  espectro, el GOTO por coordenadas, el Sync, la lectura viva de AR/Dec, el
  diálogo de ayuda al enfoque y la ceremonia de sesión nueva/abrir sesión;
  **Abrir carpeta de datos** los sustituye.
- **Paso Enfoque** (ADR-026, ADR-028): los tres enfoques corren como paso con las
  métricas de `shg.focus` (contraste y nitidez de líneas, nitidez y ondulación del
  borde, contraste, nitidez y recuento de detalle), un mejor valor retenido de
  `FocusWatcher` y un reinicio, más el tilt rendija-Dec de `shg.tilt` y la altura
  de ROI que necesita. Un espectro blando y una rendija inclinada se miden en vez
  de adivinarse.
- **Identificación nativa de líneas espectrales**: el `SpectrumPanel` ejecuta
  `shg.spectrum` sobre la banda en vivo, detecta depresiones de absorción, las
  empareja con un catálogo integrado y nombra las líneas con una confianza F1.
  Usa la línea objetivo y la dispersión de Ajustes → Espectro, etiqueta las
  líneas telúricas y nunca llama a JSol'Ex. Los nombres son una coincidencia de
  patrón, no una calibración de longitud de onda.
- **Perfiles con nombre** (ADR-027): una barra de perfiles visible y un gestor
  guardan varios perfiles con nombre en un `profiles.json`, con un perfil activo
  cargado al arrancar. Cambiar de perfil recarga óptica y presets de ROI sin mover
  el telescopio ni reiniciar la cámara. El antiguo `profile.json` se lee como
  `default`, y un `nightscribe-profiles.json` v1 se migra.
- **Correcciones de la capa de dispositivos**: cuatro defectos de SDK, incluido
  el crash de Touptek. (1) La estructura de dispositivo de Touptek medía 20 bytes
  donde el SDK escribe 136, un desbordamiento de heap y el core dump de "Find
  cameras".
  (2) Las llamadas de apertura de Touptek y QHY devolvían handles de 64 bits por
  el restype `c_int` por defecto, truncándolos y provocando un segfault en la
  llamada siguiente. (3) Las constantes `IMAGE` y `BITDEPTH` de Touptek eran
  `FRONT_OVERFLOW` y `DEMOSAIC_VIDEO`, así que el driver esperaba para siempre.
  (4) El ancho de `long` de la info de cámara ASI y el diseño de propiedades de
  Player One estaban mal, desplazando campos y arriesgando otro desbordamiento.
  El modo de diagnóstico nativo imprime las cifras medidas.
- **Backend de montura INDIGO**: JSON sobre TCP con `indigo_server`, con el mapeo
  de propiedades de INDIGO y sus clases de tasa. No inventa una tasa arbitraria en
  arcosegundos/s; la calibración del barrido mide la tasa que la montura da de
  verdad.
- **i18n**: los contextos nuevos `ProfileManagerDialog` y `SpectrumPanel`, el paso
  Enfoque y las cadenas del rediseño están traducidas; los catálogos tienen
  896 mensajes con 0 sin traducir y 0 obsoletos en ES y EN.
- **Motores reales conectados a la ventana**: el panel de cámara descubre y abre
  una cámara, restaura el preset de ROI de su sensor y envía; el ROI se aplica al
  motor de captura real; el centrado del Sol corre grueso y fino con la zona
  muerta declarada; el motor de barrido calcula el plan, prepara, repite ciclos y
  recentra si se pide; el asistente de alineación polar muestrea, ajusta y pide
  confirmación.
- **Cifras del calendario del cielo**: la pestaña Sol añade el ángulo de posición
  del polo norte (P) y el centro heliográfico (B0 y L0), calculados localmente con
  las efemérides.
- **Recon rápido conectado**: la ventana llama a `shg.recon.quick_recon` y pinta
  su resultado a medida que avanza el barrido, con el recuento de fotogramas y
  filas en la leyenda y códigos de motivo en lenguaje llano cuando no puede
  construir la vista previa.
- **Decisión del simulador**: la ventana usa la `SimCamera(pattern="solar")` de
  primera clase, acoplada a la montura simulada. A propósito no tiene línea de
  rendija inclinada, así que el tilt lee unos 0,0° en el simulador, y fija las
  filas de la banda espectral en la banda de referencia.
- **Versión**: `solarscribe.__version__` lee los metadatos de la distribución
  instalada, así que la ventana, la CLI y `session_meta.json` coinciden con la
  versión del paquete; un árbol de fuentes que nunca se instaló vuelve a `0.0.0`.
- **Tooltips de ajustes traducidos**: los 111 textos `why` pasaron a
  `solarscribe/ui/settings_text.py`, marcados con
  `QT_TRANSLATE_NOOP("Settings", ...)` y consultados con
  `QCoreApplication.translate("Settings", ...)`.
- `design/ARCHITECTURE.md` pasa a **v1**: los contratos están escritos en código
  y el documento guarda el inventario y las razones de cada tipo.
- El índice de ADRs lista el ADR-028, y el conjunto cubre el diseño hasta ese
  número, incluidos la interfaz imagen primero (ADR-026), los perfiles con nombre
  (ADR-027) y el raíl de cinco pasos (ADR-028).

### Líneas de trabajo

El proyecto se organiza en siete líneas de trabajo paralelas con propiedad de
ficheros disjunta: lead (contratos y diseño), video (cámara, montura, captura),
shg (ciencia), ux (interfaz), qe (pruebas y gates), packaging (instaladores y CI)
y docs (documentación e i18n). Esta entrada recoge los primeros entregables que
cruzan más de una: los contratos, el modelo de configuración y perfiles, el test
de dependencias, los catálogos y las guías bilingües.

### Limitaciones conocidas

- La interfaz arranca desde el código fuente, y los modos `--diagnostics` y
  `--dry-run` funcionan. La captura y el barrido con cámara y montura reales
  todavía no están validados en hardware. Las métricas de enfoque y la
  identificación de líneas espectrales se ejercitan contra el simulador y
  fixtures unitarios, no contra espectros reales.
- Todavía no hay instalador compilado ni publicado. Solo está disponible la
  instalación desde el código fuente.
- Los catálogos ES/EN cubren todo lo que `lupdate` puede extraer de la interfaz,
  con 0 cadenas sin traducir y 0 obsoletas. Son una foto del momento: vuelve a
  ejecutar `lupdate` tras cualquier cambio en un `.ui` o en un `self.tr()`.
