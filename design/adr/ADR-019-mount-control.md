# ADR-019: Control de montura por plataforma y panel de telescopio / Per-platform mount control and telescope panel

**Estado / Status**: Aceptado / Accepted · **Fecha / Date**: 2026-11-06

**Ver / See**: ADR-002 (backends), ADR-007 (alineación polar), ADR-012
(contratos), ADR-009 (UI).

## Español

**Contexto**: la montura es esencial para el SHG: el barrido **es** un movimiento
en RA sobre la rendija, y el centrado en Dec y la alineación polar son pequeños
movimientos en Dec. El observador necesita además **controlar el telescopio a
mano** desde la interfaz, como hace SharpCap (mover, apuntar, seguimiento, park).
Cada sistema operativo tiene su vía estándar: **ASCOM** en Windows, **INDI** en
Linux. La montura de referencia del MVP es **OnStep**.

**Decisión**:

1. **Backend de montura por plataforma**: **ASCOM con COM nativo** en Windows (la
   vía estándar; requiere la **plataforma ASCOM** instalada y un puente COM de
   Python, `pywin32`/`pythonnet`) e **INDI** en Linux (cliente del protocolo INDI
   contra un **`indiserver`** en marcha). Ambos implementan el **mismo contrato
   `Mount`** (ADR-012), de modo que el motor SHG y la UI no saben en qué sistema
   están.
2. **Respaldo directo opcional**: `native` (LX200, OnStep) por serie, e `indigo`.
3. **Panel de telescopio en la UI** (como SharpCap): conectar/desconectar, GOTO
   por coordenadas y **GOTO al Sol** por efeméride, botones de movimiento N/S/E/W
   con **selector de tasa**, seguimiento, park/unpark, sync y abortar slew, con
   **lectura viva de RA/Dec** y del estado. Vive en el paso *Buscar el Sol* y es
   accesible en todo momento.
4. **Simulador de montura** de primera clase (ADR-005): todas las pruebas de
   montura y de barrido corren sin hardware.

**Alternativas**: **Alpaca/HTTP en Windows** (más simple y ya multiplataforma,
pero se descarta: el usuario quiere COM nativo, la vía estándar de Windows); un
solo backend genérico en ambos SO (Alpaca o INDI). Se elige el reparto por
plataforma con contrato único.

**Consecuencias**: dos backends de montura que mantener, ambos tras el mismo
contrato; el panel de telescopio es requisito del MVP; el simulador cubre las
pruebas; la latencia de ASCOM/INDI no afecta a la tasa de vídeo (esa es la
cámara, no la montura). En Windows hay que gestionar la **plataforma ASCOM**, el
puente COM y la coincidencia de bits (32/64) del driver; en Linux, que haya un
**`indiserver`** en marcha. La app **degrada con elegancia** si falta la
plataforma ASCOM o el `indiserver`: lo dice y sigue.

## English

**Context**: the mount is essential for the SHG: the scan **is** a movement in RA
across the slit, and Dec centring and polar alignment are small movements in Dec.
The observer also needs to **control the telescope by hand** from the interface,
as SharpCap does (move, point, track, park). Each operating system has its
standard path: **ASCOM** on Windows, **INDI** on Linux. The MVP's reference mount
is **OnStep**.

**Decision**:

1. **Per-platform mount backend**: **ASCOM with native COM** on Windows (the
   standard path; it requires the **ASCOM Platform** installed and a Python COM
   bridge, `pywin32`/`pythonnet`) and **INDI** on Linux (client of the INDI
   protocol against a running **`indiserver`**). Both implement the **same `Mount`
   contract** (ADR-012), so the SHG engine and the UI do not know which system
   they are on.
2. **Optional direct fallback**: `native` (LX200, OnStep) over serial, and
   `indigo`.
3. **Telescope panel in the UI** (like SharpCap): connect/disconnect, GOTO by
   coordinates and **GOTO to the Sun** by ephemeris, N/S/E/W movement buttons with
   a **rate selector**, tracking, park/unpark, sync and abort slew, with a **live
   RA/Dec readout** and status. It lives in the *Find the Sun* step and is
   accessible at all times.
4. **First-class mount simulator** (ADR-005): every mount and scan test runs
   without hardware.

**Alternatives**: **Alpaca/HTTP on Windows** (simpler and already cross-platform,
but dropped: the user wants native COM, Windows' standard path); a single generic
backend on both OSes (Alpaca or INDI). Chosen: per-platform split with a single
contract.

**Consequences**: two mount backends to maintain, both behind the same contract;
the telescope panel is an MVP requirement; the simulator covers the tests;
ASCOM/INDI latency does not affect the video rate (that is the camera, not the
mount). On Windows the **ASCOM Platform**, the COM bridge and the driver's bit
width (32/64) must be managed; on Linux a running **`indiserver`** is required.
The app **degrades gracefully** if the ASCOM Platform or the `indiserver` is
missing: it says so and carries on.
