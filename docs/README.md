# SolarScribe documentation

*Documentación de usuario. Bilingüe ES/EN.*
*User documentation. Bilingual ES/EN.*

The internal design and the architecture decision records live in `design/` at
the repository root. Everything in this folder is for the person using the
application.

El diseño interno y los registros de decisiones de arquitectura viven en
`design/`, en la raíz del repositorio. Todo lo de esta carpeta es para quien usa
la aplicación.

---

## User guide / Guía de usuario

- **English**: [user-guide/USER_GUIDE.md](user-guide/USER_GUIDE.md).
- **Español**: [user-guide/GUIA_USUARIO.md](user-guide/GUIA_USUARIO.md).

What the application does, how a session runs, the features and their limits, the
acceptance criteria and the deep dive into the geometry.

Qué hace la aplicación, cómo transcurre una sesión, las funciones y sus límites,
los criterios de aceptación y el análisis a fondo de la geometría.

## Installation / Instalación

- **English**: [install/INSTALL.md](install/INSTALL.md).
- **Español**: [install/INSTALACION.md](install/INSTALACION.md).

Windows, Linux and source installs, prerequisites, file locations and
troubleshooting.

Instalación en Windows, Linux y desde el código fuente, requisitos, ubicación de
los ficheros y solución de problemas.

## Changelog / Registro de cambios

- [CHANGELOG.md](../CHANGELOG.md) (English).
- [CHANGELOG.es.md](../CHANGELOG.es.md) (español).

---

## Translation workflow (contributors) / Flujo de traducción (desarrollo)

The interface is bilingual from day one (ADR-016). Every GUI-visible string goes
through `self.tr()`; the catalogues are Qt Linguist `.ts` files and the compiled
`.qm` files are what the application loads.

La interfaz es bilingüe desde el primer día (ADR-016). Toda cadena visible pasa
por `self.tr()`; los catálogos son ficheros `.ts` de Qt Linguist y los `.qm`
compilados son lo que carga la aplicación.

**Where the catalogues live / Dónde viven los catálogos**

```
solarscribe/ui/i18n/solarscribe_es.ts    source catalogue, Spanish
solarscribe/ui/i18n/solarscribe_en.ts    source catalogue, English
solarscribe/ui/i18n/solarscribe_es.qm    compiled, loaded at run time
solarscribe/ui/i18n/solarscribe_en.qm    compiled, loaded at run time
```

`solarscribe_en.ts` is not a leftover: English is also a catalogue, so a missing
translation shows in the same check in both languages. The `.qm` files are
package data (`solarscribe.ui` includes `i18n/*.qm` in `pyproject.toml`).

`solarscribe_en.ts` no es un resto: el inglés también es catálogo, para que una
traducción que falte se vea en la misma comprobación en los dos idiomas. Los
ficheros `.qm` son datos del paquete (`solarscribe.ui` incluye `i18n/*.qm` en
`pyproject.toml`).

**Extract and update / Extraer y actualizar**

Run from the repository root, with the project virtual environment active. Use
the PySide6 tools inside `.venv`; the system `lupdate` may belong to another Qt
and fail or write an incompatible file.

Se ejecuta desde la raíz del repositorio, con el entorno virtual del proyecto.
Usa las herramientas de PySide6 que están dentro de `.venv`; el `lupdate` del
sistema puede pertenecer a otro Qt y fallar o escribir un fichero incompatible.

```bash
.venv/bin/pyside6-lupdate \
    $(find solarscribe/ui -type f \( -name '*.py' -o -name '*.ui' \) | sort) \
    -locations relative -no-obsolete \
    -ts solarscribe/ui/i18n/solarscribe_es.ts \
       solarscribe/ui/i18n/solarscribe_en.ts
```

The explicit file list is not decoration: the `lupdate` bundled with this PySide6
scans `.ui` files when it recurses into a directory, but it does **not** pick up
`.py` files that way. Naming the files makes the Python `self.tr()` strings come
out. If the list is empty, check that you are running from the repository root.

La lista explícita de ficheros no es decoración: el `lupdate` que trae este
PySide6 recorre los `.ui` al escanear una carpeta, pero **no** coge los `.py` por
esa vía. Nombrando los ficheros salen las cadenas de `self.tr()` de Python. Si la
lista sale vacía, comprueba que ejecutas desde la raíz del repositorio.

Translate the new and changed entries (`pyside6-linguist
solarscribe/ui/i18n/solarscribe_es.ts`), then compile:

Traduce las entradas nuevas y cambiadas (`pyside6-linguist
solarscribe/ui/i18n/solarscribe_es.ts`) y compila:

```bash
.venv/bin/pyside6-lrelease solarscribe/ui/i18n/solarscribe_es.ts \
    -qm solarscribe/ui/i18n/solarscribe_es.qm
.venv/bin/pyside6-lrelease solarscribe/ui/i18n/solarscribe_en.ts \
    -qm solarscribe/ui/i18n/solarscribe_en.qm
```

**Rules / Reglas**

- After touching a visible string, rebuild both catalogues. The target is **0
  unfinished** entries in Spanish and in English; a release does not ship with an
  unfinished string.
- Close the application before recompiling. `QTranslator` maps the `.qm` file,
  and rewriting a mapped file in place can crash a running session; the atomic
  rename the build uses protects the file, but closing the app is the safe habit.
- The `.ts` files are text and are reviewed like code. The `.qm` files are build
  output; regenerate them, do not edit them. They are checked in so a source
  checkout runs translated without a build step.
- Inside `self.tr()`, write the string as a literal. `lupdate` cannot extract
  `self.tr(some_variable)`, so a table of titles passed through a variable stays
  in English however well the catalogue is translated; wrap the literals with
  `QT_TR_NOOP` or call `self.tr()` on each one.
- In Designer, mark the dynamic property keys (`role="title"`, `state="muted"`)
  as non-translatable (`notr="true"`). They are not prose; leaving them
  translatable only fills the catalogue with tokens nobody reads.
- Reason codes and numbers are translated as sentences, never shown raw: the
  engine reports a stable code and the interface composes the phrase with
  `self.tr()`.
- The `why` texts in `config/schema.py` are shown as tooltips by the settings
  dialog. `solarscribe/ui/settings_text.py` marks each one with
  `QT_TRANSLATE_NOOP("Settings", ...)` and the dialog looks it up with
  `QCoreApplication.translate("Settings", ...)`, so `lupdate` extracts them into
  the `Settings` context. When a key or its text changes, update both the schema
  and `settings_text.py`.
- **Current state (2026-11-06)**: the catalogues hold every string the interface
  has today, with 0 unfinished entries in Spanish and English. Re-run the two
  commands after touching a `.ui` or a `self.tr()` string; the number grows with
  the interface.

**Reglas**

- Tras tocar una cadena visible, regenera los dos catálogos. El objetivo es **0
  sin traducir** en español y en inglés; una versión no sale con una cadena sin
  traducir.
- Cierra la aplicación antes de recompilar. `QTranslator` mapea el fichero `.qm`,
  y reescribir un fichero mapeado en sitio puede tumbar una sesión en marcha; el
  renombrado atómico que usa la compilación protege el fichero, pero cerrar la
  app es la costumbre segura.
- Los `.ts` son texto y se revisan como código. Los `.qm` son salida de
  compilación; regenéralos, no los edites. Están versionados para que un clon del
  código fuente arranque traducido sin un paso de compilación.
- Dentro de `self.tr()`, escribe la cadena como literal. `lupdate` no puede
  extraer `self.tr(una_variable)`, así que una tabla de títulos pasada por una
  variable se queda en inglés por bien que se traduzca el catálogo; envuelve los
  literales con `QT_TR_NOOP` o llama a `self.tr()` en cada uno.
- En Designer, marca las claves de propiedades dinámicas (`role="title"`,
  `state="muted"`) como no traducibles (`notr="true"`). No son prosa; dejarlas
  traducibles solo llena el catálogo de fichas que nadie lee.
- Los códigos de motivo y los números se traducen como frases, nunca se muestran
  crudos: el motor informa de un código estable y la interfaz compone la frase
  con `self.tr()`.
- Los textos `why` de `config/schema.py` se muestran como tooltips en el diálogo
  de ajustes. `solarscribe/ui/settings_text.py` marca cada uno con
  `QT_TRANSLATE_NOOP("Settings", ...)` y el diálogo lo consulta con
  `QCoreApplication.translate("Settings", ...)`, así que `lupdate` los extrae al
  contexto `Settings`. Cuando cambie una clave o su texto, actualiza el esquema y
  `settings_text.py`.
- **Estado actual (2026-11-06)**: los catálogos contienen todas las cadenas que
  la interfaz tiene hoy, con 0 sin traducir en español y en inglés. Vuelve a
  ejecutar los dos comandos tras tocar un `.ui` o una cadena de `self.tr()`; el
  número crece con la interfaz.

---

## Design / Diseño

The internal documents are not duplicated here:

- [design/DESIGN.md](../design/DESIGN.md): framework design.
- [design/ARCHITECTURE.md](../design/ARCHITECTURE.md): layer contracts and data
  model (v1).
- [design/adr/README.md](../design/adr/README.md): the ADR index.

Los documentos internos no se duplican aquí:

- [design/DESIGN.md](../design/DESIGN.md): diseño marco.
- [design/ARCHITECTURE.md](../design/ARCHITECTURE.md): contratos entre capas y
  modelo de datos (v1).
- [design/adr/README.md](../design/adr/README.md): índice de ADRs.
