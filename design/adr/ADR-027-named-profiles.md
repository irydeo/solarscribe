# ADR-027: Perfiles con nombre / Named profiles

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-003 (configuración y perfiles), ADR-024 (reconciliación del
INI), ADR-010 (ROI), ADR-028 (raíl de cinco pasos).

## Español

**Contexto**: `config/store.py` guarda un solo `Profile` en `profile.json`. El uso
real pide **varios perfiles visibles por su nombre** y uno activo al arrancar,
como `nightscribe-scan`, que ya guarda `{version, active, profiles: {...}}`. Un
observador cambia de montaje o de preset de ROI sin querer reescribir el único
perfil; la UI y la CLI necesitan listar nombres, saber cuál está activo y
cambiarlo sin adivinar.

El perfil v2 de SolarScribe (telescopio, cámara y presets de ROI) es más rico que
el v1 del prototipo y se conserva; lo que cambia es que deja de ser único.

**Decisión**:

1. **Un solo `profiles.json`** en la carpeta de configuración
   (`paths.profiles_path()`) con esta forma:

   ```jsonc
   {
     "version": 2,
     "active": "SHG-700",
     "profiles": {
       "SHG-700": { "version": 2, "telescope": {}, "camera": {}, "roi_presets": [] },
       "SHG-700 wide": { "version": 2, "telescope": {}, "camera": {}, "roi_presets": [] }
     }
   }
   ```

   Cada bloque es un `Profile` v2 completo, el mismo documento que escribe
   `save_profile()`, para que exportar o importar un perfil suelto no necesite
   conversión.

2. **Por qué un fichero y no uno por perfil**: el arranque necesita la lista y el
   activo en una lectura; con un fichero por perfil harían falta un barrido de
   carpeta y un marcador separado del activo, y renombrar o borrar serían dos
   escrituras que un cierre a medias puede dejar inconsistentes. Un solo fichero
   convierte cada operación en un `os.replace` atómico y coincide con el
   prototipo, así que su `nightscribe-profiles.json` se migra tal cual.

3. **API explícita y pura** en `config/store.py`. Las operaciones devuelven un
   `ProfileStore` nuevo; solo `save_profiles()` escribe:

   ```python
   load_profiles(path, *, legacy_path=None) -> ProfileStore
   save_profiles(store, path) -> None
   profile_names(store) -> tuple[str, ...]
   active_profile(store) -> Profile | None
   set_active_profile(store, name) -> ProfileStore
   save_named_profile(store, name, profile, *, make_active=False) -> ProfileStore
   rename_profile(store, old, new) -> ProfileStore
   delete_profile(store, name) -> ProfileStore
   ```

   Los nombres se recortan y no pueden quedar vacíos. `set_active_profile()` y
   `delete_profile()` lanzan `KeyError` ante un nombre que no existe;
   `rename_profile()` lanza `ValueError` si el nombre nuevo está vacío o ya se
   usa. Guardar el primer perfil lo activa: un almacén con un perfil y ninguno
   activo no tiene nada que enseñar.

4. **Arranque y migración**:
   - Sin `profiles.json` y sin `profile.json`: un perfil `"default"` activo.
   - Sin `profiles.json` pero con `profile.json` en la misma carpeta (o el que
     diga `legacy_path`): se carga como `"default"` activo, en memoria. La
     lectura no escribe; el primer guardado lo persiste y el `profile.json`
     antiguo no se toca.
   - Con `profiles.json`: es la verdad; el `profile.json` antiguo se ignora.
   - Un `nightscribe-profiles.json` v1 se acepta entero: todos los nombres y el
     `active`, con cada bloque traducido por las reglas de ADR-024.
   - Un `profiles.json` truncado intenta el `profile.json` antiguo y, si no hay,
     el perfil por defecto: la app nunca arranca sin perfil.
   - Un fichero válido con `profiles: {}` es un almacén vacío: borrar el último
     perfil se respeta y no se resucita el perfil por defecto.

5. **Selección activa honesta**: si `active` nombra un perfil que no existe
   (errata a mano), la cadena se conserva y `active_profile()` devuelve `None`.
   No se activa otro instrumento en silencio. Borrar el perfil activo deja
   `active=""` por la misma razón.

6. **Compatibilidad**: `load_profile(path)` y `save_profile(profile, path)` se
   quedan como el lector y el escritor de un perfil suelto (el `profile.json`
   antiguo y la exportación). La UI y la CLI pasan al almacén cuando quieran
   nombres; no se rompe ninguna llamada existente.

**Migración**: no hay migración de código: la API es nueva y las funciones de un
perfil siguen igual. La migración de datos es de lectura: `profile.json` se
convierte en el perfil `"default"` activo al cargar, y el primer guardado crea
`profiles.json`. Un `nightscribe-profiles.json` v1 se migra al cargarlo.

**Alternativas**:

- **Un fichero por perfil**: obliga a barrer una carpeta al arrancar y a mantener
  el activo aparte; renombrar o borrar deja de ser atómico. Se descarta.
- **Una base de datos**: aporta concurrencia y consultas que una app de escritorio
  de un usuario no necesita, y aleja el fichero de la edición a mano. Se
  descarta.
- **Mantener un solo perfil y llamar "perfiles" a los presets de ROI**: no
  cumple el requisito de nombres visibles y selección al arrancar. Se descarta.
- **Guardar el activo dentro de cada bloque**: cada perfil tendría un booleano y
  dos podrían estar activos tras una edición a mano. Se descarta.

**Consecuencias**: la UI puede listar, crear, renombrar, borrar y cambiar de
perfil con una API pequeña y sin tocar el disco hasta que decide guardar. Un
cierre a medias no corrompe el almacén. El coste aceptado es que dos instancias de
la app escribiendo a la vez se pisan, igual que en el prototipo; es una
aplicación de escritorio de un solo usuario. Cambiar la forma del fichero exige un
ADR nuevo que referencie este.

## English

**Context**: `config/store.py` keeps a single `Profile` in `profile.json`. Real
use asks for **several profiles visible by name** and one active at startup, like
`nightscribe-scan`, which already stores `{version, active, profiles: {...}}`. An
observer changes mount or ROI preset without wanting to overwrite the only
profile; the UI and the CLI need to list names, know which one is active and
switch without guessing.

SolarScribe's v2 profile (telescope, camera and ROI presets) is richer than the
prototype's v1 and is kept; what changes is that it is no longer unique.

**Decision**:

1. **A single `profiles.json`** in the configuration folder
   (`paths.profiles_path()`) with this shape:

   ```jsonc
   {
     "version": 2,
     "active": "SHG-700",
     "profiles": {
       "SHG-700": { "version": 2, "telescope": {}, "camera": {}, "roi_presets": [] },
       "SHG-700 wide": { "version": 2, "telescope": {}, "camera": {}, "roi_presets": [] }
     }
   }
   ```

   Each block is a complete v2 `Profile`, the same document `save_profile()`
   writes, so exporting or importing a single profile needs no converter.

2. **Why one file and not one per profile**: startup needs the list and the
   active one in one read; one file per profile would need a directory scan and a
   separate active marker, and rename or delete would be two writes that a
   half-finished close can leave inconsistent. One file turns every operation
   into an atomic `os.replace` and matches the prototype, so its
   `nightscribe-profiles.json` migrates as is.

3. **Explicit, pure API** in `config/store.py`. The operations return a new
   `ProfileStore`; only `save_profiles()` writes:

   ```python
   load_profiles(path, *, legacy_path=None) -> ProfileStore
   save_profiles(store, path) -> None
   profile_names(store) -> tuple[str, ...]
   active_profile(store) -> Profile | None
   set_active_profile(store, name) -> ProfileStore
   save_named_profile(store, name, profile, *, make_active=False) -> ProfileStore
   rename_profile(store, old, new) -> ProfileStore
   delete_profile(store, name) -> ProfileStore
   ```

   Names are trimmed and cannot be empty. `set_active_profile()` and
   `delete_profile()` raise `KeyError` for a missing name; `rename_profile()`
   raises `ValueError` when the new name is empty or already used. Saving the
   first profile activates it: a store with one profile and no active one has
   nothing to show.

4. **Startup and migration**:
   - No `profiles.json` and no `profile.json`: one active `"default"` profile.
   - No `profiles.json` but a `profile.json` in the same folder (or the one
     given as `legacy_path`): it loads as the active `"default"` in memory.
     Loading does not write; the first save persists it and the old
     `profile.json` is left untouched.
   - With `profiles.json`: it is the truth; the old `profile.json` is ignored.
   - A v1 `nightscribe-profiles.json` is accepted whole: every name and the
     `active` one, each block translated by the ADR-024 rules.
   - A truncated `profiles.json` tries the old `profile.json` and then the
     default profile: the app never starts without a profile.
   - A valid file with `profiles: {}` is an empty store: deleting the last
     profile is respected and the default profile is not resurrected.

5. **Honest active selection**: when `active` names a profile that does not exist
   (a hand edit), the string is preserved and `active_profile()` returns `None`.
   No other instrument is activated silently. Deleting the active profile leaves
   `active=""` for the same reason.

6. **Compatibility**: `load_profile(path)` and `save_profile(profile, path)` stay
   as the reader and writer of a single profile (the old `profile.json` and
   export). The UI and the CLI move to the store when they want names; no
   existing call breaks.

**Migration**: no code migration: the API is new and the single-profile functions
are unchanged. Data migration is read-only: `profile.json` becomes the active
`"default"` profile on load, and the first save creates `profiles.json`. A v1
`nightscribe-profiles.json` is migrated when loaded.

**Alternatives**:

- **One file per profile**: it forces a directory scan at startup and a separate
  active marker; rename or delete stop being atomic. Dropped.
- **A database**: it brings concurrency and queries a single-user desktop app does
  not need, and moves the file away from hand editing. Dropped.
- **Keep one profile and call the ROI presets "profiles"**: it does not meet the
  requirement of visible names and a startup selection. Dropped.
- **Store the active flag inside each block**: a hand edit could leave two
  profiles active. Dropped.

**Consequences**: the UI can list, create, rename, delete and switch profiles with
a small API and without touching the disk until it decides to save. A crash mid
write cannot corrupt the store. The accepted cost is that two app instances
writing at once clobber each other, as in the prototype; it is a single-user
desktop app. Changing the file shape requires a new ADR referencing this one.
