# ADR-009: Interfaz, tema y menú / UI, theme and menu

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-006 (centrado), ADR-007 (alineación polar), ADR-010 (ROI),
ADR-011 (flujo de sesión).

## Español

**Contexto**: SolarScribe es hermano de NightScribe y comparte con él usuario,
hábitos y pila (PySide6). Reutilizar su aspecto y su organización ahorra tiempo,
reduce la curva de aprendizaje y evita una segunda identidad visual que mantener.
Las utilidades de observación solar, además, no deben vivir sueltas: han de estar
donde el observador ya las busca.

**Decisión**:

1. **Mismo estilo que NightScribe**: se adopta su `theme.py` como fuente única de
   la identidad visual, el patrón de ficheros `.ui` + `ui_loader.py` y la i18n
   `.ts` ES/EN. **Solo tema oscuro**, con **icono, logo y acento propios** de
   SolarScribe (sol). Conviven bajo la misma licencia (GPL-3) y con atribución.
2. **Disposición**: **raíl de pasos arriba** (horizontal), **panel lateral** con
   las opciones del paso activo, el **vídeo** en el área principal (con
   histograma, stretch, zoom, rejilla y cruz, más una **vista ampliada del
   espectro**) y una **barra de estado** abajo (fps, frames perdidos, estado y
   disco). **Ventana principal + diálogos**.
3. **Bienvenida e idioma**: un **asistente de bienvenida** en línea al primer
   arranque; el **idioma es el del sistema** por defecto, con opción de cambiarlo.
4. **Menú**: una `QMenuBar` con **File / Tools / Help**, como NightScribe. En
   **Tools** viven las utilidades: Settings…, **Sky calendar…**, **ROI manager…**,
   Focus aid…, Device diagnostics… y **Logs** (visor dentro de la app). **No** hay
   barra de navegación superior (breadcrumbs/atrás-adelante): SolarScribe tiene
   pocas vistas y no la necesita.
5. **Tools → Sky calendar… → Sun**: las utilidades de observación solar se
   integran en la pestaña **Sun** del calendario, que es una **copia propia
   adaptada** del calendario de NightScribe (no una dependencia compartida:
   ambos son proyectos independientes). Se amplía con lo propio del SHG:
   diámetro y ángulo solar de la fecha (alimentan la geometría del barrido),
   rotación solar, coordenadas heliográficas y regiones activas.

**Alternativas**: importar el diálogo de NightScribe como dependencia compartida
(acopla ambos proyectos); un diálogo solar mínimo sin Moon/Planets (pierde
utilidades ya resueltas); barra de navegación superior (sobredimensionada para
pocas vistas). Se descartan.

**Consecuencias**: dos aplicaciones que se sienten iguales; una sola identidad
visual que mantener por app; el calendario solar queda a un clic desde Tools y
reutiliza el trabajo de NightScribe sin acoplarse a él.

## English

**Context**: SolarScribe is NightScribe's sibling and shares its user, habits and
stack (PySide6). Reusing its look and organisation saves time, shortens the
learning curve and avoids maintaining a second visual identity. The solar
observing utilities, moreover, should not live loose: they belong where the
observer already looks for them.

**Decision**:

1. **Same style as NightScribe**: adopt its `theme.py` as the single source of the
   visual identity, the `.ui` + `ui_loader.py` pattern and the ES/EN `.ts` i18n.
   **Dark theme only**, with **SolarScribe's own icon, logo and accent** (sun).
   They coexist under the same licence (GPL-3) and with attribution.
2. **Layout**: **step rail on top** (horizontal), a **side panel** with the active
   step's options, the **video** in the main area (with histogram, stretch, zoom,
   grid and cross, plus a **magnified view of the spectrum**) and a **status bar**
   at the bottom (fps, dropped frames, state and disk). **Main window + dialogs**.
3. **Welcome and language**: an inline **welcome assistant** on first run; the
   **language is the system's** by default, with an option to change it.
4. **Menu**: a `QMenuBar` with **File / Tools / Help**, as in NightScribe. The
   utilities live under **Tools**: Settings…, **Sky calendar…**, **ROI manager…**,
   Focus aid…, Device diagnostics… and **Logs** (in-app viewer). There is **no**
   top navigation bar (breadcrumbs/back-forward): SolarScribe has few views and
   does not need one.
5. **Tools → Sky calendar… → Sun**: the solar observing utilities are integrated
   in the calendar's **Sun** tab, which is an **own adapted copy** of
   NightScribe's calendar (not a shared dependency: both are independent
   projects). It is extended with what the SHG needs: solar diameter and angular
   size for the date (they feed the scan geometry), solar rotation, heliographic
   coordinates and active regions.

**Alternatives**: import NightScribe's dialog as a shared dependency (couples both
projects); a minimal solar dialog without Moon/Planets (loses already-solved
utilities); a top navigation bar (oversized for few views). Dropped.

**Consequences**: two applications that feel the same; one visual identity to
maintain per app; the solar calendar is one click away under Tools and reuses
NightScribe's work without coupling to it.
