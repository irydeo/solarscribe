# ADR-026: Interfaz simplificada, la imagen primero / Simplified image-first interface

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-009 (UI, tema y menú), ADR-011 (flujo por pasos),
ADR-019 (panel de telescopio), ADR-020 (visualización del barrido y recon
rápido). Corrige la presentación de ADR-011; no cambia sus reglas.

## Español

**Contexto**: la primera versión de la ventana cumplía ADR-011 al pie de la
letra, pero lo hacía a costa de la imagen. Medido en la ventana de referencia
(1280 x 820): el raíl de pasos ocupaba 64 px con dos líneas por paso, el panel
izquierdo llegaba a 460 px y llevaba párrafos completos por paso, el panel de
telescopio medía 290 px con campos de GOTO, Sync y una lectura de RA/Dec que un
observador solar no usa, el visor se quedaba en 345 px de alto (el 42% de la
ventana) y el histograma y el progreso del barrido vivían en cajas fijas de
90 px y 130 px. El usuario lo resumió sin rodeos: la ventana está sobrecargada,
la imagen tiene poco sitio, y maximizar no lo arregla.

**Decisión**:

1. **La imagen primero**. El visor ocupa la mayor parte de la ventana y crece
   con ella: en la ventana de referencia pasa a 650 px de alto (el 79%). El
   panel lateral tiene un máximo de 330 px, el raíl 28 px, y las bandas
   inferiores se pliegan. Maximizar da el espacio extra al visor, no a los
   paneles.
2. **Raíl de pasos mínimo, no suprimido**. Los cinco pasos siguen (ADR-011),
   pero en una sola línea de 28 px: `1. Find Sun · Pending`. El estado se
   sigue escribiendo con palabras, no solo con color. Navegación libre,
   recomendación, autoguardado silencioso y «reabrir paso» no cambian.
3. **Un quinto paso, Focus**. El foco de los tres focusers y la inclinación de
   la rendija con Dec son un paso pesado, no un diálogo de Tools. Va entre
   Alineación polar y ROI. Muestra en vivo las métricas de `shg.focus`
   (contraste y nitidez de las líneas del espectrógrafo, nitidez y tambaleo del
   borde del colimador, contraste, nitidez y número de detalles del telescopio)
   y su mejor valor desde el último reinicio (`FocusWatcher`); el tilt de
   `shg.tilt` (grados y píxeles de deriva) guía a girar la rendija hasta dejarla
   paralela a Dec y dice la altura de ROI que necesita. Las métricas y el tilt
   son de shg; la interfaz solo mide en vivo y explica. El paso ROI conserva una
   medición rápida del tilt porque la altura de la tira la necesita, pero la
   alineación guiada vive en Focus. El antiguo diálogo **Tools → Focus aid…**
   desaparece.
4. **Fuera el ampliador del espectro**. El visor ya tiene zoom, rejilla, cruz y
   el overlay del ROI; el ampliador duplicaba esa información y robaba altura.
   El zoom del visor y el histograma sobre la banda cubren su función.
5. **Panel de telescopio plegable y esencial**. Visible por defecto, se cierra
   con su barra de título o desde **Tools → Panels**, y se reabre desde ahí.
   Quedan: conectar, buscar montura, **Go to the Sun**, N/S/E/W con tasa, Stop,
   seguimiento y park, con su mensaje en lenguaje llano. Se retiran los campos
   de GOTO por coordenadas, Sync, Abort slew y el grupo **Where it points** con
   la lectura viva de RA/Dec: en un observador solar el único blanco es el Sol,
   su posición viene de la efeméride y el seguimiento ya está en la casilla de
   abajo. El contrato `Mount` conserva `slew`, `sync` y `abort_slew` para los
   motores y para un futuro modo avanzado; la interfaz deja de exponerlos.
6. **Panel izquierdo reescrito como tarjeta de paso**. Cada paso muestra un
   título, una frase corta de por qué, sus lecturas vivas y **una sola acción
   principal**. Los párrafos largos se mudan al tooltip del título o del campo.
   El panel cabe en 250 a 330 px y sigue siendo desplazable.
7. **Histograma estilo UFE, pensado para el Sol**. Una tira plegable de 24 px
   de cabecera; al abrirse, 256 bins en escala logarítmica calculados **solo
   sobre la banda espectral**, no sobre el fotograma entero (las filas oscuras
   dominarían la cuenta). Dos asas arrastrables, negro y blanco, al estilo
   AstroImageJ: un clic mueve la más cercana; el blanco nunca cruza el negro.
   Las zonas que el stretch tira se sombrean. La cabecera avisa de saturación
   con el porcentaje de banda en el nivel máximo y un tooltip que explica por
   qué importa. El combo de brillo conserva los presets y añade un modo manual
   que refleja las asas.
8. **Progreso del barrido integrado**. La caja fija de 130 px desaparece. El
   disco capturado, la línea de la rendija y el recon rápido viven en una tira
   plegable; su cabecera lleva el porcentaje y el ciclo, y **se abre sola al
   empezar un barrido**. El mismo dato sigue en el panel de Scanning.
9. **Sin ceremonia de sesión**. Las carpetas de sesión se quedan porque son
   donde viven el SER y los logs, pero la interfaz deja de gestionarlas: fuera
   **New session** y **Open session…**, y en su lugar queda **Open data
   folder**. El flujo visible es abrir cámara, apuntar al Sol, ajustar el ROI y
   barrer. El autoguardado del estado sigue, sin botón de guardar.

**Alternativas**: conservar el raíl de 64 px (gasta imagen y no aporta más que
la versión de 28 px); conservar el ampliador (duplica el zoom del visor);
conservar el GOTO por coordenadas y la lectura RA/Dec (controles que el usuario
solar no usa y que empujan el panel a 290 px); conservar la caja fija de
progreso (130 px permanentes para un dato que solo importa durante el barrido);
dejar los párrafos en el panel (el usuario no los lee y empujan los controles
fuera de pantalla); dejar el foco como un diálogo de Tools (no mide en vivo
ni guía la rendija). Se descartan.

**Consecuencias**: la ventana enseña la imagen, no la administración. El
histograma y el progreso siguen a un clic y no cuestan altura cuando no se usan.
El paso Focus añade la lectura en vivo de los tres focusers y del tilt; no
bloquea el barrido, que puede correr con un ROI más alto. El observador que
quiera GOTO por coordenadas o Sync no lo encuentra en la
interfaz; el contrato de montura lo conserva y puede volver como modo avanzado
en otra ADR. Las cadenas visibles cambian (ver el informe para `docs`), y el
panel de telescopio deja de mostrar RA/Dec: el estado de seguimiento vive en su
casilla y en la barra de estado. ADR-011 sigue vigente en lo que importa:
navegación libre, recomendaciones, autoguardado y reabrir paso. El conjunto de
pasos pasa de cuatro a cinco con Focus.

## English

**Context**: the first window followed ADR-011 to the letter, but it did so at
the expense of the image. Measured on the reference window (1280 x 820): the
step rail took 64 px with two lines per step, the left panel reached 460 px and
carried full paragraphs per step, the telescope panel measured 290 px with GOTO
fields, Sync and a live RA/Dec readout a solar observer never uses, the viewer
was left 345 px tall (42% of the window), and the histogram and scan progress
lived in fixed 90 px and 130 px boxes. The user put it bluntly: the window is
overloaded, the image has too little room, and maximising does not fix it.

**Decision**:

1. **Image first**. The viewer takes most of the window and grows with it: on
   the reference window it becomes 650 px tall (79%). The side panel has a
   330 px maximum, the rail is 28 px, and the bottom bands fold. Maximising
   gives the extra space to the viewer, not to the panels.
2. **Minimal step rail, not removed**. The five steps stay (ADR-011), but on a
   single 28 px line: `1. Find Sun · Pending`. The status is still spelled
   out in words, not only a colour. Free navigation, recommendation, silent
   auto-save and "reopen step" do not change.
3. **A fifth step, Focus**. The three focusers and the slit-to-Dec tilt are a
   heavyweight step, not a Tools dialog. It sits between Polar alignment and
   ROI. It shows the `shg.focus` metrics live (spectrograph line contrast and
   line sharpness, collimator edge sharpness and edge wobble, telescope detail
   contrast, detail sharpness and detail count) and their running best since the
   last reset (`FocusWatcher`); the `shg.tilt` tilt (degrees and pixels of
   drift) guides the observer to rotate the slit until it is parallel to Dec and
   says the ROI height it needs. The metrics and the tilt are shg's; the
   interface only measures live and explains. The ROI step keeps a quick tilt
   measure because the strip height needs it, but the guided alignment lives in
   Focus. The old **Tools → Focus aid…** dialog is removed.
4. **No spectrum magnifier**. The viewer already has zoom, grid, cross and the
   ROI overlay; the magnifier duplicated that information and stole height. The
   viewer zoom and the band histogram cover its job.
5. **Collapsible, essential telescope panel**. Visible by default, it closes
   with its title bar or from **Tools → Panels**, and comes back from there.
   What stays: connect, find the mount, **Go to the Sun**, N/S/E/W with rate,
   Stop, tracking and park, with its plain-language message. The coordinate GOTO
   fields, Sync, Abort slew and the **Where it points** group with the live
   RA/Dec readout are removed: for a solar observer the only target is the Sun,
   its position comes from the ephemeris and tracking is already the checkbox
   below. The `Mount` contract keeps `slew`, `sync` and `abort_slew` for the
   engines and for a future advanced mode; the interface stops exposing them.
6. **Left panel rewritten as a step card**. Each step shows a title, one short
   sentence of why, its live readings and **a single primary action**. The long
   paragraphs move into the tooltip of the title or the field. The panel fits
   in 250 to 330 px and still scrolls.
7. **UFE-style histogram, thought for the Sun**. A foldable strip with a 24 px
   header; when open, 256 log-scaled bins computed **only over the spectral
   band**, not the whole frame (the dark rows would dominate the count). Two
   draggable handles, black and white, AstroImageJ style: a click moves the
   nearest one; white never crosses black. The zones the stretch throws away are
   shaded. The header warns about saturation with the percentage of the band at
   the top level and a tooltip that explains why it matters. The brightness
   combo keeps its presets and adds a manual mode that mirrors the handles.
8. **Scan progress integrated**. The fixed 130 px box is gone. The captured
   disk, the slit line and the quick recon live in a foldable strip; its header
   carries the percentage and the cycle, and **it opens by itself when a scan
   starts**. The same figure stays in the Scanning panel.
9. **No session ceremony**. Session folders stay because the SER and the logs
   live there, but the interface stops managing them: **New session** and
   **Open session…** are gone, and **Open data folder** takes their place. The
   visible flow is open the camera, point at the Sun, set the ROI and scan. The
   state auto-save stays, with no Save button.

**Alternatives**: keep the 64 px rail (wastes image and adds nothing over the
28 px version); keep the magnifier (duplicates the viewer zoom); keep the
coordinate GOTO and RA/Dec readout (controls the solar user does not use and
that push the panel to 290 px); keep the fixed progress box (130 px permanent
for a figure that only matters during the sweep); leave the paragraphs in the
panel (the user does not read them and they push the controls off screen);
leave focus as a Tools dialog (it neither measures live nor guides the slit).
Dropped.

**Consequences**: the window shows the image, not the administration. The
histogram and the progress are one click away and cost no height when unused.
The Focus step adds the live reading of the three focusers and the tilt; it
does not gate the scan, which can run with a taller ROI. The observer who wants
coordinate GOTO or Sync will not find it in the
interface; the mount contract keeps it and it can return as an advanced mode in
another ADR. The visible strings change (see the report for `docs`), and the
telescope panel no longer shows RA/Dec: the tracking state lives in its checkbox
and in the status bar. ADR-011 still holds where it matters: free navigation,
recommendations, auto-save and reopen step. The step set grows from four to five
with Focus.
