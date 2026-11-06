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

- **Motores reales conectados a la ventana**: el panel de cámara descubre y abre
  una cámara, restaura el preset de ROI de su sensor y envía; el ROI se aplica al
  motor de captura real; el centrado del Sol corre grueso y fino con la zona
  muerta declarada; el motor de barrido calcula el plan, prepara, repite ciclos y
  recentra si se pide; el asistente de alineación polar muestrea, ajusta y pide
  confirmación. El simulador de la interfaz dibuja ahora un espectro solar
  acoplado a la montura simulada, así que los bucles reales convergen contra él.
- **Cifras del calendario del cielo**: la pestaña Sol añade el ángulo de posición
  del polo norte (P) y el centro heliográfico (B0 y L0), calculados localmente con
  las efemérides.
- **Recon rápido conectado**: la ventana llama a `shg.recon.quick_recon` y pinta
  su resultado a medida que avanza el barrido, con el recuento de fotogramas y
  filas en la leyenda y códigos de motivo en lenguaje llano cuando no puede
  construir la vista previa. Es ligero, no autoritativo y nunca se exporta.
- **Decisión del simulador**: la ventana usa la `SimCamera(pattern="solar")` de
  primera clase, acoplada a la montura simulada. A propósito no tiene línea de
  rendija inclinada, así que el tilt lee unos 0,0° en el simulador, y fija las
  filas de la banda espectral en la banda de referencia. El medidor de tilt lo
  ejercitan las pruebas unitarias; un fotograma real es lo que lo demuestra.
- **Versión**: `solarscribe.__version__` lee los metadatos de la distribución
  instalada, así que la ventana, la CLI y `session_meta.json` coinciden con la
  versión del paquete; un árbol de fuentes que nunca se instaló vuelve a `0.0.0`.
- **i18n**: los contextos nuevos `CameraPanel` y `Session` y las cadenas nuevas de
  MainWindow, calendario del cielo y recon rápido están traducidas, 0 sin traducir
  en ES y EN.
- `design/ARCHITECTURE.md` pasa a **v1**: los contratos están escritos en código
  y el documento guarda el inventario y las razones de cada tipo, que es lo que no
  se puede leer de una firma.
- El índice de ADRs lista el ADR-024, y el conjunto cubre el diseño hasta ese
  número: medición de tilt (ADR-022), módulos de contrato (ADR-023) y
  reconciliación del INI con `nightscribe-scan` (ADR-024).

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
  todavía no están validados en hardware.
- Todavía no hay instalador compilado ni publicado. Solo está disponible la
  instalación desde el código fuente.
- Los catálogos ES/EN cubren todo lo que `lupdate` puede extraer de la interfaz,
  con 0 cadenas sin traducir. Son una foto del momento: vuelve a ejecutar
  `lupdate` tras cualquier cambio en un `.ui` o en un `self.tr()`.
- Las explicaciones de los ajustes en `config/schema.py` son prosa en inglés y
  `lupdate` no las extrae; necesitan una estrategia de traducción antes de que se
  publique el diálogo de ajustes.
