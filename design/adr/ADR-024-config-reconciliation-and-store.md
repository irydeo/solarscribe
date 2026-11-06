# ADR-024: Reconciliación del INI con nightscribe-scan y contrato de configuración / INI reconciliation with nightscribe-scan and configuration contract

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-003 (configuración y perfiles), ADR-012 (contratos entre
capas), ADR-013 (presupuesto), ADR-018 (post-proceso), ADR-023 (módulos de
contrato), `design/notes/NIGHTSCRIBE-SCAN-PARITY.md`.

## Español

**Contexto**: ADR-003 decide que SolarScribe hereda el esquema INI de
`nightscribe-scan` con las mismas claves, porque el usuario ya conoce ese fichero
y el post-proceso existente depende de sus formatos. El esquema v1 de
`config/schema.py` se escribió sin el prototipo a mano: marcaba como heredadas
claves que el prototipo no tiene (`[observatory]`, `[camera]`, `[mount]`,
`[session]`) y no contenía las 66 claves reales de `[optics]`, `[scan]`, `[fps]`,
`[limb]`, `[dec]`, `[mosaic]`, `[exposure]`, `[calibration]` y `[logging]`.
Además, varias claves propias repetían un comportamiento heredado (`scan.cycles`
frente a `num_cycles`, `capture.stall_timeout_s` frente a
`fps.capture_stall_seconds`, etc.), de modo que el fichero podía contener dos
verdades contradictorias. Faltaba también la implementación prometida:
`load_settings`/`save_settings`, `load_profile`/`save_profile`,
`load_session_state`/`save_session_state`, los nombres de sesión y las carpetas
por plataforma.

Ahora el clon real está disponible (`CONFIG_SCHEMA`, `CONFIG_DEFAULTS` y
`docs/nightscribe-scan.cfg.reference`), y siete agentes necesitan una sola
respuesta antes de escribir código contra el esquema.

**Decisión**:

1. **Las 66 claves heredadas se copian con su sección, ortografía y default
   exactos.** La sección solo organiza; el nombre es la constante del prototipo
   en minúsculas. La tabla es la prueba: `tests/unit/test_config_store.py`
   contiene el inventario completo.
2. **Una sola desviación de default, escrita aquí**: `scan.num_cycles` vale 3,
   no 1, porque DESIGN.md §6 y §7 piden tres ciclos por sesión. ADR-003 permite
   que un ADR cambie un default; este es el ADR. Si el fichero del usuario trae
   `num_cycles = 1`, se respeta su 1: el default solo actúa cuando la clave no
   está.
3. **El origen se corrige.** `[observatory]`, `[camera]`, `[mount]`,
   `[session]` y `[roi]` son claves de SolarScribe (`origin="new"`): el
   prototipo tomaba esos datos de SharpCap o no los tenía. Solo las nueve
   secciones del punto 1 son `origin="scan"`.
4. **Los nombres propios que duplicaban un comportamiento heredado se
   conservan como alias, pero el nombre heredado es el canónico**
   (`LEGACY_KEYS`):

   | Alias SolarScribe | Clave canónica |
   | --- | --- |
   | `scan.cycles` | `scan.num_cycles` |
   | `scan.padding_s` | `scan.padded_duration` |
   | `scan.preload_s` | `scan.scan_preload_seconds` |
   | `scan.adaptive_stop` | `scan.trailing_limb_stop` |
   | `capture.stall_timeout_s` | `fps.capture_stall_seconds` |
   | `capture.min_free_disk_gb` | `fps.capture_min_free_gb` |
   | `camera.auto_exposure` | `scan.enable_auto_exp` |

   Reglas: `load_settings()` lee el alias solo si el canónico no está en el
   fichero, y refleja el valor resuelto en los dos nombres; `save_settings()`
   escribe solo el canónico; `keys_of(seccion)` oculta los alias y
   `keys_of(seccion, include_legacy=True)` los devuelve para una migración. Los
   defaults del alias y del canónico son iguales, así que un fichero mudo no
   puede dar dos respuestas.
5. **Se retiran tres claves que no pueden ser alias** porque su tipo o su
   significado no coincide: `general.dry_run` (es `scan.enable_capture = false`),
   `scan.mode` (es `scan.enable_mosaic`) y `camera.auto_exposure_target` (el
   bloque heredado `[exposure]` dirige un percentil, no una media). No había
   código consumiéndolas.
6. **`config/store.py` es el único lector y escritor.** Devuelve tipos completos:
   - `load_settings(path) -> Settings`, con una entrada por clave del esquema y
     `unknown` para las claves que el fichero trae y el esquema no conoce.
     `Settings.get()` lanza `KeyError` fuera del esquema, para que una errata no
     se lea como un cero.
   - `save_settings(settings, path)` escribe secciones, un comentario con el
     `why` de cada clave y solo nombres canónicos.
   - `load_profile(path) -> Profile` y `save_profile(profile, path)`, con el JSON
     v2 de ARCHITECTURE §3.2.
   - `load_session_state(path) -> SessionState` y `save_session_state()`.
   - Los nombres: `session_folder()`, `scan_ser_path()`, `scan_log_path()`,
     `scan_stats_path()`, `session_meta_path()` y `session_state_path()`.
7. **Lectura tolerante, escritura atómica.** Falta el fichero, falta una clave,
   el número no se puede leer o el JSON está truncado: default del esquema. La
   codificación es UTF-8 con Latin-1 de respaldo, como el prototipo. Los
   booleanos usan un vocabulario fijo (`1`, `true`, `yes`, `on` y sus
   negativos). Toda escritura va a un temporal en la misma carpeta y se mueve
   con `os.replace`, de modo que un cierre a media escritura deja el fichero
   anterior intacto.
8. **El INI es la verdad de la sesión; el perfil es una instantánea con
   nombre.** Seleccionar un perfil escribe sus datos en el INI; `store.py` no
   fusiona las dos fuentes. Es lo que hacía el panel del prototipo y evita que
   un perfil antiguo pise un ajuste reciente sin que nadie lo vea. Los datos
   físicos están en los dos sitios y sus defaults coinciden; la sesión siempre
   lee el INI.
9. **Migración de perfil v1.** Un `{version: 1, profiles: {...}}` (o un `config`
   plano) se convierte a v2 traduciendo `FOCAL_LENGTH`, `PIXEL_SIZE`,
   `MOSAIC_SLIT_LENGTH_MM` y `meta.camera`/`meta.aperture_mm`. El resto de las
   claves v1 pertenece al INI, no al perfil, y allí sigue. Un perfil v2 escrito a
   mano se acepta aunque traiga números como texto o claves desconocidas.
10. **Estado de sesión tolerante.** Pasos que faltan, pasos inventados, estados
    desconocidos y métricas que no son números no rompen el raíl: se completan
    con `PENDING` y se descartan los valores no numéricos. Las métricas son
    números; la frase la escribe la UI (ADR-016, ADR-023).
11. **Nombres de sesión.** La carpeta es `YYYYMMDD_HHMM` en hora local, con
    sufijo `_2`, `_3` si dos sesiones caen en el mismo minuto. El SER es
    `sun_YYYYMMDD_HHMM_scanNN.ser` con `NN` a dos dígitos y numeración desde 1;
    un 0 es un error de programación y lanza `ValueError`. Los tres registros de
    ADR-018 son uno por sesión, como en el prototipo; el SER es uno por barrido.
    Las claves heredadas `[logging]` pueden mover los registros: vacías significan
    la carpeta de la sesión, una ruta absoluta se usa tal cual y una relativa se
    resuelve contra la carpeta de la sesión.
12. **Carpetas por plataforma con `platformdirs`.** `config_dir()` guarda
    `config.ini` y `profile.json`; `data_dir()` guarda las sesiones
    (`default_session_base()` es `data_dir()/sessions`) y `log_dir()` el log de
    la aplicación. En Windows las dos primeras son
    `%LOCALAPPDATA%\SolarScribe`; en Linux, `$XDG_CONFIG_HOME/SolarScribe` y
    `$XDG_DATA_HOME/SolarScribe`. Nada se escribe junto al ejecutable, porque
    `Program Files` y `/usr` son de solo lectura. Las funciones de
    `config/paths.py` solo resuelven: la carpeta se crea cuando se escribe.
13. **`Settings` vive en `config/store.py`, no en `schema.py`.** El módulo de
    contrato declara la tabla y los tipos de valor, pero no contiene algoritmos
    (ADR-023); el tipo que devuelve el lector y sus accesores viven con el
    lector. Es la misma frontera que `validate_roi()` en `capture/roi.py`.

**Migración**: no hay código consumiendo las claves retiradas ni los alias fuera
de `config/schema.py`, así que no hay migración de código. Un
`nightscribe-scan.cfg` se puede copiar al `config.ini` de SolarScribe: todas sus
claves se reconocen. El prototipo busca su fichero junto al script o en
`$NIGHTSCRIBE_CONFIG`; SolarScribe usa la carpeta de configuración de la
plataforma, así que no lo descubre solo: la importación es una copia, no un
descubrimiento automático. Un perfil v1 se migra al cargarlo.

**Alternativas**:

- **Mantener las claves duplicadas y elegir una por precedencia sin declararlo**:
  dos verdades en el mismo fichero y dos controles en el diálogo. Se descarta.
- **Convertir las claves duplicadas en alias con conversión de tipo**
  (`scan.mode` de texto a booleano): más código y dos formas de decir lo mismo.
  Se descarta; se retira la clave.
- **Un esquema nuevo en TOML o JSON**: ADR-003 ya lo descartó: rompe el
  post-proceso y los hábitos del usuario sin ganar nada.
- **Guardar la configuración junto al ejecutable**: falla en `Program Files` y
  en `/usr`, y obliga a root. Se descarta.
- **Fusionar perfil e INI al cargar**: el perfil antiguo pisa el ajuste reciente
  sin que el usuario lo vea. Se descarta; se aplica explícitamente.
- **Un registro por barrido**: rompe las columnas y la lectura del post-proceso
  de ADR-018. Se descarta.
- **Devolver un `dict` de `load_settings`**: el contrato quedaría implícito y
  una clave ausente se leería como `None`. Se descarta.

**Consecuencias**: un fichero de `nightscribe-scan` sigue valiendo; un fichero
editado a mano nunca impide arrancar y dice qué clave no se reconoce; el diálogo
de ajustes tiene un control por comportamiento; el INI y el perfil no se pisan.
El coste es una tabla de alias pequeña y una migración v1 de unas pocas líneas.
Cambiar una clave heredada exige ahora un ADR nuevo que referencie este, porque
la ortografía es parte del contrato con el post-proceso.

## English

**Context**: ADR-003 decides that SolarScribe inherits the INI schema of
`nightscribe-scan` with the same keys, because the user already knows that file
and the existing post-processing depends on its formats. The v1 schema in
`config/schema.py` was written without the prototype at hand: it marked as
inherited keys the prototype does not have (`[observatory]`, `[camera]`,
`[mount]`, `[session]`) and it did not contain the real 66 keys of `[optics]`,
`[scan]`, `[fps]`, `[limb]`, `[dec]`, `[mosaic]`, `[exposure]`, `[calibration]`
and `[logging]`. On top of that, several of its own keys duplicated an inherited
behaviour (`scan.cycles` against `num_cycles`, `capture.stall_timeout_s` against
`fps.capture_stall_seconds`, and so on), so the file could hold two contradictory
truths. The promised implementation was also missing: `load_settings` /
`save_settings`, `load_profile` / `save_profile`, `load_session_state` /
`save_session_state`, the session naming and the per-platform directories.

The real clone is now available (`CONFIG_SCHEMA`, `CONFIG_DEFAULTS` and
`docs/nightscribe-scan.cfg.reference`), and seven agents need one answer before
writing code against the schema.

**Decision**:

1. **The 66 inherited keys are copied with their exact section, spelling and
   default.** The section only organises; the name is the prototype constant in
   lower case. The table is the test: `tests/unit/test_config_store.py` holds the
   complete inventory.
2. **One default deviation, written here**: `scan.num_cycles` is 3, not 1,
   because DESIGN.md §6 and §7 ask for three cycles per session. ADR-003 allows an
   ADR to change a default; this is that ADR. If the user's file says
   `num_cycles = 1`, their 1 is respected: the default only acts when the key is
   absent.
3. **The origin is corrected.** `[observatory]`, `[camera]`, `[mount]`,
   `[session]` and `[roi]` are SolarScribe keys (`origin="new"`): the prototype
   took those values from SharpCap or did not have them. Only the nine sections
   of point 1 are `origin="scan"`.
4. **The own names that duplicated an inherited behaviour survive as aliases,
   but the inherited name is canonical** (`LEGACY_KEYS`):

   | SolarScribe alias | Canonical key |
   | --- | --- |
   | `scan.cycles` | `scan.num_cycles` |
   | `scan.padding_s` | `scan.padded_duration` |
   | `scan.preload_s` | `scan.scan_preload_seconds` |
   | `scan.adaptive_stop` | `scan.trailing_limb_stop` |
   | `capture.stall_timeout_s` | `fps.capture_stall_seconds` |
   | `capture.min_free_disk_gb` | `fps.capture_min_free_gb` |
   | `camera.auto_exposure` | `scan.enable_auto_exp` |

   Rules: `load_settings()` reads the alias only when the canonical key is absent
   from the file, and mirrors the resolved value into both names;
   `save_settings()` writes the canonical name alone; `keys_of(section)` hides
   the aliases and `keys_of(section, include_legacy=True)` returns them for a
   migration. Alias and canonical defaults are equal, so a silent file cannot
   answer two different things.
5. **Three keys are removed because they cannot be aliases**: their type or
   their meaning does not match. `general.dry_run` is `scan.enable_capture =
   false`; `scan.mode` is `scan.enable_mosaic`; `camera.auto_exposure_target` is
   replaced by the inherited `[exposure]` block, which drives a percentile and
   not a mean. No code consumed them.
6. **`config/store.py` is the only reader and writer.** It returns complete
   types:
   - `load_settings(path) -> Settings`, with one entry per schema key and
     `unknown` for the file keys the schema does not know. `Settings.get()`
     raises `KeyError` outside the schema, so a typo cannot read as a zero.
   - `save_settings(settings, path)` writes sections, one comment with each
     key's `why`, and canonical names only.
   - `load_profile(path) -> Profile` and `save_profile(profile, path)`, with the
     v2 JSON of ARCHITECTURE §3.2.
   - `load_session_state(path) -> SessionState` and `save_session_state()`.
   - The names: `session_folder()`, `scan_ser_path()`, `scan_log_path()`,
     `scan_stats_path()`, `session_meta_path()` and `session_state_path()`.
7. **Tolerant reading, atomic writing.** A missing file, a missing key, an
   unreadable number or a truncated JSON all fall back to the schema default.
   The encoding is UTF-8 with Latin-1 as a fallback, like the prototype. Booleans
   use a fixed vocabulary (`1`, `true`, `yes`, `on` and their negatives). Every
   write goes to a temporary file in the same folder and is moved with
   `os.replace`, so a crash mid-write leaves the previous file intact.
8. **The INI is the session truth; the profile is a named snapshot.** Selecting
   a profile writes its data into the INI; `store.py` never merges the two
   sources. That is what the prototype panel did and it keeps an old profile from
   silently overriding a recent adjustment. The physical data lives in both and
   their defaults agree; the session always reads the INI.
9. **v1 profile migration.** A `{version: 1, profiles: {...}}` (or a flat
   `config`) becomes v2 by translating `FOCAL_LENGTH`, `PIXEL_SIZE`,
   `MOSAIC_SLIT_LENGTH_MM` and `meta.camera`/`meta.aperture_mm`. The rest of the
   v1 keys belong to the INI, not to the profile, and stay there. A hand-written
   v2 profile is accepted even with numbers as text or unknown keys.
10. **Tolerant session state.** Missing steps, invented steps, unknown statuses
    and non-numeric metrics do not break the rail: they become `PENDING` and the
    non-numeric values are dropped. Metrics are numbers; the sentence is written
    by the UI (ADR-016, ADR-023).
11. **Session names.** The folder is `YYYYMMDD_HHMM` in local time, with a `_2`,
    `_3` suffix when two sessions fall in the same minute. The SER is
    `sun_YYYYMMDD_HHMM_scanNN.ser` with `NN` zero padded and the numbering
    starting at 1; a 0 is a programming error and raises `ValueError`. The three
    ADR-018 logs are one per session, like the prototype; the SER is one per
    scan. The inherited `[logging]` keys can move the logs: empty means the
    session folder, an absolute path is used as is and a relative one resolves
    against the session folder.
12. **Per-platform directories with `platformdirs`.** `config_dir()` holds
    `config.ini` and `profile.json`; `data_dir()` holds the sessions
    (`default_session_base()` is `data_dir()/sessions`) and `log_dir()` the
    application log. On Windows the first two are
    `%LOCALAPPDATA%\SolarScribe`; on Linux they are
    `$XDG_CONFIG_HOME/SolarScribe` and `$XDG_DATA_HOME/SolarScribe`. Nothing is
    written next to the executable, because `Program Files` and `/usr` are
    read-only. The functions in `config/paths.py` only resolve: the folder is
    created when something is written.
13. **`Settings` lives in `config/store.py`, not in `schema.py`.** The contract
    module declares the table and the value types but holds no algorithm
    (ADR-023); the type the reader returns and its accessors live with the
    reader. It is the same boundary as `validate_roi()` in `capture/roi.py`.

**Migration**: no code consumes the removed keys or the aliases outside
`config/schema.py`, so there is no code migration. A `nightscribe-scan.cfg` can
be copied into SolarScribe's `config.ini`: every key is recognised. The prototype
looks for its file next to the script or in `$NIGHTSCRIBE_CONFIG`; SolarScribe
uses the platform configuration folder, so it does not discover it on its own:
the import is a copy, not an automatic discovery. A v1 profile is migrated when
it is loaded.

**Alternatives**:

- **Keep the duplicate keys and pick one by an undeclared precedence**: two
  truths in one file and two controls in the dialog. Dropped.
- **Turn the duplicates into type-converting aliases** (`scan.mode` from text to
  boolean): more code and two ways to say the same thing. Dropped; the key is
  removed.
- **A new schema in TOML or JSON**: ADR-003 already dropped it: it breaks the
  post-processing and the user's habits with nothing gained.
- **Store the configuration next to the executable**: it fails in `Program
  Files` and `/usr`, and demands root. Dropped.
- **Merge profile and INI on load**: the old profile overrides the recent
  adjustment without the user seeing it. Dropped; it is applied explicitly.
- **One log per scan**: it breaks the columns and the ADR-018 post-processing
  reader. Dropped.
- **Return a `dict` from `load_settings`**: the contract would stay implicit and
  a missing key would read as `None`. Dropped.

**Consequences**: a `nightscribe-scan` file still works; a hand-edited file never
stops the app and says which key it does not recognise; the settings dialog has
one control per behaviour; the INI and the profile do not override each other.
The cost is a small alias table and a few lines of v1 migration. Changing an
inherited key now requires a new ADR referencing this one, because the spelling
is part of the contract with the post-processing.
