# Guía de instalación de SolarScribe

**Español** · [English → INSTALL.md](INSTALL.md)

Esta guía cubre los sistemas admitidos, los requisitos y las dos formas de
conseguir SolarScribe: los instaladores empaquetados y la instalación desde el
código fuente.

> **Estado (2026-11-07)**: los instaladores empaquetados están **previstos**, no
> publicados. La instalación desde el código fuente funciona y la ventana
> principal arranca con el simulador; la captura con cámara y montura reales
> todavía no está validada. Los instaladores descritos en las secciones 2 y 3 son
> la forma acordada (ADR-004, ADR-017); toma sus nombres de fichero y diálogos
> exactos como provisionales.

---

## 1. Antes de empezar

### 1.1 Sistemas admitidos

| Sistema | Paquete | Estado |
| --- | --- | --- |
| Windows 10/11 x64 | Compilación PyInstaller envuelta en un instalador Inno Setup | Previsto (MVP) |
| Debian, Ubuntu y derivadas | `.deb` | Previsto (MVP) |
| Fedora, RHEL y derivadas | `.rpm` | Previsto (MVP) |
| Cualquier sistema con Python 3.11 o 3.12 | Instalación desde el código fuente | Disponible hoy |

Las dos plataformas son de primera clase desde el MVP. Linux no es un añadido y
Windows no es una ocurrencia posterior: una versión no se publica hasta que las
dos compilan y arrancan (ADR-017).

### 1.2 Hardware

- **Cámara**: uno de los backends nativos, ZWO ASI, QHY, Player One o Touptek,
  más el simulador incluido. La cámara de referencia es una Touptek G3M678M,
  mono, 16 bits, con un ROI de referencia de 3480×248 px.
- **Montura**: OnStep en la configuración de referencia. En Windows la vía es
  ASCOM COM; en Linux es INDI contra un `indiserver` en marcha.
- **Conexión**: USB 3 para la cámara. La franja de referencia produce unos
  207 MB/s, lo que exige un enlace USB 3 y un disco que sostenga al menos
  250 MB/s.
- **Disco**: reserva varios GB por barrido. La aplicación se niega a empezar una
  grabación por debajo de un mínimo configurable de espacio libre, un gigabyte por
  defecto, porque un disco lleno a mitad de barrido pierde la toma.
- **¿Sin hardware?** Los simuladores de cámara y montura permiten instalar,
  arrancar y ensayar una sesión sin cámara ni montura.

### 1.3 Qué trae el instalador y qué no

Los binarios de los SDK de cámara viajan dentro del paquete, porque una aplicación
de captura que obliga a buscar DLLs no es utilizable de serie. En Linux el paquete
también trae las reglas `udev` y, para QHY, el firmware.

Lo que **no** trae:

- La **plataforma ASCOM** en Windows. Es la vía estándar a la montura y se instala
  aparte, con su runtime de .NET.
- Un **servidor INDI** en Linux. Tú arrancas `indiserver` con el driver de tu
  montura, como con cualquier cliente INDI.
- Python, en las instalaciones empaquetadas. Solo la instalación desde el código
  fuente lo necesita.

Si falta una pieza, SolarScribe dice cuál y sigue funcionando con el resto; no se
niega a arrancar.

---

## 2. Instalar en Windows (previsto, MVP)

1. Descarga `SolarScribe-x.y.z-win64.exe` desde **GitHub Releases**.
2. Ejecútalo. El instalador **no está firmado**, así que SmartScreen puede mostrar
   un aviso. Comprueba que el fichero viene de la página de Releases del proyecto
   y usa **Más información → Ejecutar de todas formas**. La firma es una decisión
   de release (ADR-017), no un paso que falte en tu máquina.
3. Acepta la licencia (GPL-3) y elige la carpeta. Por defecto, bajo `Program
   Files`.
4. El instalador comprueba los requisitos e informa de lo que encuentra. Si falta
   la plataforma ASCOM, la montura no estará disponible hasta que la instales; la
   cámara y el simulador siguen funcionando.
5. Termina y arranca SolarScribe desde el menú Inicio.

**Requisito de montura**: instala la **plataforma ASCOM** (que trae el runtime de
.NET) antes de la primera sesión. El puente COM de Python es una dependencia de
la aplicación; el driver ASCOM de tu montura no.

**Cámara**: conecta la cámara a un puerto USB 3. El SDK ya está dentro del
paquete; no hace falta descargar ningún SDK aparte para los cuatro backends
nativos. Si Windows pide un driver para la cámara, instala el driver firmado del
fabricante, que normalmente viene con el paquete del SDK. Si la cámara sigue sin
aparecer, consulta la sección 9.

---

## 3. Instalar en Linux (previsto, MVP)

### 3.1 Debian, Ubuntu y derivadas

```bash
sudo apt install ./solarscribe_x.y.z_amd64.deb
```

`apt` resuelve las dependencias de ejecución de la distribución. Instalar con
`dpkg -i` también funciona, pero después hace falta `sudo apt -f install` para
terminar las dependencias.

### 3.2 Fedora, RHEL y derivadas

```bash
sudo dnf install ./solarscribe-x.y.z.x86_64.rpm
```

### 3.3 Permisos de cámara y `udev`

El paquete instala las reglas `udev` que dan acceso al usuario con sesión iniciada
a las cámaras admitidas. Si la cámara estaba conectada antes de la instalación,
desconéctala y vuelve a conectarla, o recarga las reglas:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

El firmware de QHY, cuando hace falta, también viaja con el paquete.

### 3.4 La montura: `indiserver`

Linux usa INDI. Arranca `indiserver` con el driver de tu montura antes de abrir
SolarScribe:

```bash
indiserver -v <tu_driver_de_montura>
```

El nombre exacto del driver depende de la montura; es el mismo que usarías con
cualquier otro cliente INDI. Si `indiserver` no está en marcha, SolarScribe
informa de que el backend de montura no está disponible y mantiene la cámara y el
resto de la sesión funcionando.

Si prefieres un panel gráfico de INDI, `kstars`/`ekos` o `indistarter` pueden
arrancar el servidor por ti; SolarScribe solo necesita el servidor.

---

## 4. Instalar desde el código fuente (disponible hoy)

Es el único camino que funciona antes de la primera versión, y el que se usa para
desarrollar.

### 4.1 Requisitos

- Python 3.11 o superior; se recomienda 3.12.
- Una pila sin compilador: la aplicación usa Python puro con `ctypes`, así que no
  hace falta compilar nada.
- `git`.
- En Linux, las reglas `udev` de la cámara y el servidor INDI, como en la sección
  3. Al ejecutar desde el código fuente las reglas no las instala un paquete: usa
  el script que acompaña al proyecto o las reglas del fabricante de la cámara.
- En Windows, la plataforma ASCOM para la montura.

### 4.2 Pasos

```bash
git clone https://github.com/irydeo/solarscribe.git
cd solarscribe
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit
.venv/bin/python -m solarscribe --version
```

En Windows el entorno virtual vive en `.venv\Scripts` en vez de `.venv/bin`:

```powershell
py -3.12 -m venv --system-site-packages .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest tests/unit
.venv\Scripts\python -m solarscribe --version
```

Las pruebas unitarias no necesitan hardware ni red. Son la forma más rápida de
saber que la instalación está sana.

### 4.3 Limitación actual

`python -m solarscribe --version` funciona e imprime la versión del paquete
instalado; un árbol de fuentes que nunca se instaló vuelve a `0.0.0`.
`python -m solarscribe` abre la ventana principal; sin cámara ni montura arranca
con el simulador. `python -m solarscribe --diagnostics` imprime un informe de la
instalación y de la capa de dispositivos, y `python -m solarscribe --dry-run`
comprueba la geometría sin abrir la cámara ni mover la montura. La captura con
cámara y montura reales todavía no está validada; el simulador es el camino que
funciona hoy.

### 4.4 Herramientas de traducción (desarrollo)

Las herramientas de Qt Linguist vienen con PySide6 dentro del entorno virtual:

```bash
.venv/bin/pyside6-lupdate --help
.venv/bin/pyside6-lrelease --help
```

El flujo de trabajo y la ubicación de los catálogos están documentados en el
[índice de documentación](../README.md).

---

## 5. Primer arranque (previsto, MVP)

1. **Idioma**: la aplicación sigue el idioma del sistema y ofrece español e
   inglés. La elección se guarda en los ajustes.
2. **Asistente de bienvenida**: pide la latitud y la longitud del observatorio, y
   después los datos del telescopio y de la cámara (focal, apertura, longitud de
   rendija, tamaño de píxel). Los valores de referencia son 714 mm, 80 mm, 7 mm y
   2 µm.
3. **Descubrimiento de dispositivos**: la cámara y la montura se buscan en segundo
   plano. El descubrimiento habla con los SDK y puede tardar un segundo o más;
   nunca bloquea la ventana.
4. **Degradación**: un SDK de cámara, una plataforma ASCOM o un `indiserver` que
   falten producen un mensaje en lenguaje llano que dice qué falta. El resto de la
   aplicación sigue siendo utilizable.
5. **Modo seco**: antes de la primera sesión real, ejecuta en modo seco: la
   montura se mueve y el motor mide, pero no se escribe nada en disco. Valida la
   ubicación, el perfil, la cámara y la montura sin arriesgar una toma.

El asistente de bienvenida es en línea, no un asistente modal aparte, y se puede
saltar. Todo lo que pide se puede cambiar después en los ajustes.

---

## 6. Dónde guarda SolarScribe sus ficheros

SolarScribe sigue las convenciones de la plataforma a través de `platformdirs`
(ADR-004, ADR-017, ADR-024). No se escribe nada junto al ejecutable: el
instalador deja el programa y los datos del usuario van a las carpetas del
usuario.

| Contenido | Windows | Linux |
| --- | --- | --- |
| Ajustes (`config.ini`) y perfiles (`profiles.json`; un `profile.json` antiguo se lee como `default`) | `%LOCALAPPDATA%\SolarScribe\` | `~/.config/SolarScribe/` |
| Carpetas de datos (carpetas de sesión), ficheros SER y registros | `%LOCALAPPDATA%\SolarScribe\sessions\` por defecto, configurable | `~/.local/share/SolarScribe/sessions/` por defecto, configurable |

La carpeta base de datos se configura en los ajustes; el diseño y los registros la
llaman base de sesiones. Windows usa `%LOCALAPPDATA%` y no el perfil móvil a
propósito: una carpeta de datos de varios gigabytes no tiene sitio en un perfil
móvil.

La carpeta de datos se crea por tanda y se nombra con su fecha y hora. Los
ficheros de dentro siguen el patrón `sun_AAAAMMDD_HHMM_scanNN`.

**Importante**: la carpeta de datos es **tuya**. La aplicación nunca borra un SER
ni un registro. Desinstalar el programa no elimina tus capturas, así que cópialas
antes de borrar la carpeta de datos a mano.

---

## 7. Verificar la instalación

| Comprobación | Cómo | Cómo se ve bien |
| --- | --- | --- |
| El programa arranca | Lánzalo desde el menú o con `python -m solarscribe` | Se abre la ventana principal con el simulador; `--self-test` hace lo mismo en modo offscreen y sale |
| Versión | `python -m solarscribe --version` | Imprime la versión, `0.0.0` desde un árbol de fuentes limpio |
| Pruebas unitarias | `python -m pytest tests/unit` | Todas en verde, sin hardware |
| Modo seco | `python -m solarscribe --dry-run` | Imprime la óptica, el ROI y la geometría, y termina con "the dry run is valid" |
| Cámara encontrada | Descubrimiento de dispositivos en la aplicación | La cámara aparece con su backend y su número de serie |
| Montura encontrada | Panel de telescopio, conectar | RA/Dec y estado se actualizan, los botones mueven la montura |
| Idioma | Ajustes, selector de idioma | La interfaz cambia entre español e inglés |
| Rendimiento | Panel de salud durante un modo seco | FPS, pérdidas, cola y caudal de disco cerca del presupuesto para el ROI elegido |
| Estado de traducción | `pyside6-lupdate` y `pyside6-lrelease` sobre los catálogos | 0 cadenas sin traducir en los dos idiomas |

Las filas marcadas como previstas no pueden pasar hasta que exista la función
correspondiente. Las pruebas unitarias y la comprobación de versión sí funcionan
hoy.

---

## 8. Actualizar y desinstalar

### Windows

- **Actualizar**: ejecuta el instalador nuevo sobre la versión instalada. Los
  ajustes y las capturas se conservan.
- **Desinstalar**: Configuración → Aplicaciones → Aplicaciones instaladas →
  SolarScribe → Desinstalar. Las capturas y los ajustes no se borran; elimínalos
  a mano si quieres una máquina limpia.

### Linux

- **Actualizar**: `sudo apt install ./solarscribe_x.y.z_amd64.deb` o
  `sudo dnf upgrade ./solarscribe-x.y.z.x86_64.rpm`, según la distribución.
- **Desinstalar**: `sudo apt remove solarscribe` o `sudo dnf remove solarscribe`.
  La configuración y las capturas se quedan en tu carpeta personal.

### Código fuente

```bash
git pull
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit
```

El `.venv` es autocontenido; borrar la carpeta elimina la instalación de
desarrollo.

---

## 9. Solución de problemas

| Síntoma | Causa probable | Qué hacer |
| --- | --- | --- |
| La cámara no aparece | Falta el SDK, hay un problema de USB o las reglas `udev` no están cargadas | Revisa el puerto USB 3 y el cable; en Linux vuelve a conectar la cámara o recarga las reglas; usa el diagnóstico de dispositivos cuando llegue (fase 2) |
| La cámara aparece pero no da fotogramas | Ancho de banda USB u otro programa usando la cámara | Cierra el otro software de captura, prueba otro puerto, baja la tasa o el ROI |
| La montura no está disponible en Windows | Falta la plataforma ASCOM o el driver de la montura | Instala la plataforma ASCOM y el driver ASCOM del fabricante; comprueba que el ancho de bits del driver coincide |
| La montura no está disponible en Linux | `indiserver` no está en marcha o el driver es incorrecto | Arranca `indiserver` con el driver de la montura y confirma que escucha |
| La montura conecta pero no se mueve | El driver no declara tasas, o la montura está aparcada | Desaparca, revisa el selector de tasa, prueba un movimiento pequeño con el panel de telescopio |
| La aplicación arranca pero no aparece la ventana desde el código fuente | `solarscribe.ui.app` todavía no existe | Es lo esperado en esta etapa; usa la versión y las pruebas unitarias para validar la instalación |
| SmartScreen bloquea el instalador de Windows | El instalador no está firmado | Comprueba la página de Releases y usa **Más información → Ejecutar de todas formas** |
| Un barrido se niega a empezar por falta de disco | Se alcanzó el mínimo de espacio libre (1 GB por defecto) | Libera espacio o apunta la carpeta de datos a otro disco |
| La interfaz sigue en inglés en un sistema en español | El ajuste de idioma está forzado, o falta el `.qm` | Cambia el idioma en los ajustes; en desarrollo, regenera los catálogos |
| Un perfil escrito a mano impide arrancar | Un error de sintaxis o una versión desconocida | La aplicación debe volver a los valores por defecto; si no lo hace, es un fallo, notifícalo con el fichero |

---

## 10. Requisitos de un vistazo

| Requisito | Windows | Linux |
| --- | --- | --- |
| Sistema operativo | Windows 10/11 x64 | Debian/Ubuntu o Fedora/RHEL, 64 bits |
| Python para la instalación empaquetada | No hace falta | No hace falta |
| Python para la instalación desde el código fuente | 3.11+ (se recomienda 3.12) | 3.11+ (se recomienda 3.12) |
| SDK de cámara | Incluidos | Incluidos |
| Permisos de cámara | Driver USB del SDK | Reglas `udev` del paquete |
| Backend de montura | Plataforma ASCOM y driver del fabricante | `indiserver` y el driver de la montura |
| Disco | Unos GB libres por barrido; 250 MB/s sostenidos | Igual |
| Red | No hace falta | No hace falta |

---

## 11. Referencias

- [Guía de usuario](../user-guide/GUIA_USUARIO.md).
- [ADRs de instalación](../../design/adr/README.md): ADR-004 (empaquetado
  multiplataforma), ADR-017 (empaquetado, CI, versionado y licencias), ADR-019
  (control de montura).
- [Registro de cambios](../../CHANGELOG.es.md).
