# AGENTS.md: SolarScribe

*Reglas de trabajo para personas y agentes. Bilingüe ES/EN.*
*Working rules for people and agents. Bilingual ES/EN.*

---

## Español

### Qué es esto

SolarScribe es la aplicación de **captura** para un espectroheliógrafo (SHG),
hermana de NightScribe y con sus mismos patrones. Abre la cámara y la montura,
mide en vivo y ejecuta el barrido, y deja los SER y los registros listos para el
post-proceso. **No hace post-proceso.**

- Multilenguaje de facto: **Python 3.11+** (3.12 recomendado), GUI **PySide6** y
  CLI.
- **GPL-3**.
- **Windows y Linux funcionales de serie** desde el MVP.
- El diseño marco vive en [design/DESIGN.md](design/DESIGN.md); los contratos
  entre capas en [design/ARCHITECTURE.md](design/ARCHITECTURE.md); las decisiones
  en `design/adr/`.

### Reglas de código (obligatorias)

- **El código es siempre inglés**: identificadores, comentarios y cabeceras. La
  documentación de usuario va en `docs/`, en español e inglés; el diseño interno,
  en `design/`.
- **Los mensajes de commit y el texto de los PR son siempre inglés.**
- **La cabecera de abajo va en TODOS los ficheros `.py`** (ajustando el módulo):

```python
############################################################
# -*- coding: utf-8 -*-
#
# SolarScribe - <Module name> module
# Python  v3.12
#
# Francisco José Calvo Fernández
# (c) 2026
#
# Licence GPL v3
#
############################################################
```

- **Voz humana**: comentarios cortos `# @args:` / `# @return:` sobre cada método.
  Sin docstrings robóticas, sin sobreingeniería.
- **Código didáctico (regla permanente)**: quien lo lea debe entender el **por
  qué**, no solo el qué. Cada bloque no obvio explica su razón, la física o el
  fallo que evita; los números medidos van en el comentario. Un comentario que no
  enseña nada es ruido.
- **Ningún número sin explicación**: la interfaz nunca muestra una cifra
  (magnitud, fps, frames perdidos, error de alineación) sin decir qué significa y
  por qué importa.
- **La interfaz se define en `ui/*.ui`** (ADR-009): estructura, textos y tooltips
  en Designer; el código solo conecta señales y rellena datos. Los widgets
  personalizados (visor, histograma, overlay de ROI) no entran en un `.ui`:
  placeholder `QWidget` + `replaceWidget`.
- **Toda cadena visible pasa por `self.tr()`** (i18n ES/EN, ADR-016).
- **Docs en lenguaje natural**: nunca el guion largo; se escribe con ":", "," y
  ";". El guion medio queda reservado para rangos numéricos (0–100).
- **TDD estricto (regla permanente)**: ningún cambio de producto sin una prueba
  escrita antes que falle sin él. La red de seguridad la custodia el agente QE
  (ADR-015).

### Layout del repositorio

Un único repositorio **público** (`solarscribe`): aquí corre el arnés, con
`AGENTS.md` y `.opencode/`, y aquí vive también el código. No hay submódulos.

```
solarscribe/                   (repo público, raíz de trabajo)
  AGENTS.md                    reglas + equipo
  .opencode/agents/            las 7 definiciones
  design/                      diseño, contratos y ADRs
    DESIGN.md · ARCHITECTURE.md · adr/ · AGENTS.md · notes/
  solarscribe/                 el paquete Python
    devices/ capture/ shg/ ui/ cli/ config/
  tests/  installer/  docs/ (usuario)  pyproject.toml
```

Los comandos de desarrollo se ejecutan **desde la raíz del repositorio**. Regla de
dependencias: `ui` y `cli` dependen de `capture` y `shg`; `capture` y `shg`
dependen de `devices`; `devices` no depende de nada de la aplicación.

### Al clonar

```bash
git clone https://github.com/irydeo/solarscribe.git
cd solarscribe
```

Abre OpenCode en la **raíz del repositorio**: así carga `AGENTS.md` y descubre los
agentes de `.opencode/agents/`. El proceso completo para la IA está en
[`design/BOOTSTRAP.md`](design/BOOTSTRAP.md).

### Equipo de agentes

Siete agentes. Cada uno es **propietario** de unos módulos y **custodio** de unos
ADRs. Los detalles operativos están en `.opencode/agents/*.md` y su versión
legible en [`design/AGENTS.md`](design/AGENTS.md).

| Agente | Misión | Propiedad | Custodia |
| --- | --- | --- | --- |
| **lead** | Contratos entre capas, ADRs, revisión cruzada, resolver conflictos | `design/`, `config/`, frontera entre capas | 000, 001, 003, 012, 018, 021 |
| **video** | Que la app hable con cámara y montura y que el stream no pierda frames | `devices/` (con `devices/sim/`), `capture/`, ROI de captura | 002, 008, 010, 013, 019 |
| **shg** | Que el cálculo sea correcto: limbo, tasa, centrado, mosaico, polar, tilt | `shg/` | 006, 007, 022 |
| **ux** | Que escanear sea fácil para cualquiera | `ui/`, editor de ROI (UI) | 009, 011, 020 |
| **qe** | La red de seguridad: unitaria (TDD), funcional (mocks/vídeos) y rendimiento | `tests/`, fixtures, banco de rendimiento, gates | 005, 015 |
| **packaging** | Windows y Linux funcionales de serie, CI, licencias, versionado | `installer/`, CI, `pyproject.toml` | 004, 017 |
| **docs** | Documentación bilingüe y traducción `.ts` ES/EN | `design/`, `solarscribe/docs/`, `.ts`, CHANGELOG | 000, 016 |

El **lead** no es jefe: es quien evita que siete agentes rompan los contratos
entre capas. El **qe** no escribe producto: escribe pruebas y **puede bloquear**
cualquier cambio que no cumpla los gates.

### Gates de calidad

Todo cambio pasa por:

- **G1 TDD**: prueba en rojo, luego verde, luego refactor.
- **G2 Funcional**: prueba funcional con mock o con vídeo real.
- **G3 Rendimiento**: se cumple el presupuesto de rendimiento (ADR-013).
- **G4 Usabilidad**: si toca UI, revisión del agente `ux` con guion de tareas.
- **G5 Empaquetado**: si toca release, instala y arranca en Windows y Linux.

**Hecho** = tests verdes, presupuesto cumplido, ADR actualizado e i18n al día.

### Cómo trabajar

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit        # rápido, sin hardware
.venv/bin/python -m pytest tests/functional  # mocks, vídeos y hardware
.venv/bin/python -m solarscribe gui          # arranca la GUI
```

### Decisiones

Toda decisión de arquitectura o diseño está en `design/adr/` (bilingües; índice
en `design/adr/README.md`). Antes de cambiar una decisión, lee el ADR; si la
cambias, crea uno nuevo que lo referencie (los aceptados no se reescriben).

---

## English

### What this is

SolarScribe is the **capture** application for a spectroheliograph (SHG), a
sibling of NightScribe with the same patterns. It opens the camera and the mount,
measures live and runs the scan, and leaves the SER files and logs ready for
post-processing. **It does not post-process.**

- Effectively one language: **Python 3.11+** (3.12 recommended), **PySide6** GUI
  and CLI.
- **GPL-3**.
- **Windows and Linux functional out of the box** from the MVP.
- The framework design lives in [design/DESIGN.md](design/DESIGN.md); the layer
  contracts in [design/ARCHITECTURE.md](design/ARCHITECTURE.md); the decisions in
  `design/adr/`.

### Code rules (mandatory)

- **Code is always English**: identifiers, comments, headers. User documentation
  lives in `docs/`, in Spanish and English; the internal design, in `design/`.
- **Commit messages and PR text are always English.**
- **The header block above goes in EVERY `.py` file** (adjust the module name).
- **Human voice**: short `# @args:` / `# @return:` comments above each method. No
  robotic docstrings, no over-engineering.
- **Didactic code (permanent rule)**: whoever reads it must understand **why**,
  not just what. Every non-obvious block explains its reason, the physics, or the
  failure it prevents; measured numbers go in the comment. A comment that teaches
  nothing is noise.
- **No figure without an explanation**: the UI never shows a number (magnitude,
  fps, dropped frames, alignment error) without saying what it means and why it
  matters.
- **The interface is defined in `ui/*.ui`** (ADR-009): structure, texts and
  tooltips in Designer; code only wires signals and fills data. Custom widgets
  (viewer, histogram, ROI overlay) never enter a `.ui`: placeholder `QWidget` +
  `replaceWidget`.
- **Every GUI-visible string goes through `self.tr()`** (ES/EN i18n, ADR-016).
- **Docs in natural language**: never the em dash; write with ":", "," and ";".
  The en dash is reserved for numeric ranges (0–100).
- **Strict TDD (permanent rule)**: no product change without a test written first
  that fails without it. The QE agent custodies the safety net (ADR-015).

### Repository layout

A single **public** repository (`solarscribe`): the harness runs here, with
`AGENTS.md` and `.opencode/`, and the code lives here too. No submodules.

```
solarscribe/                   (public repo, working root)
  AGENTS.md                    rules + team
  .opencode/agents/            the seven definitions
  design/                      design, contracts and ADRs
    DESIGN.md · ARCHITECTURE.md · adr/ · AGENTS.md · notes/
  solarscribe/                 the Python package
    devices/ capture/ shg/ ui/ cli/ config/
  tests/  installer/  docs/ (user)  pyproject.toml
```

Development commands run **from the repository root**. Dependency rule: `ui` and
`cli` depend on `capture` and `shg`; `capture` and `shg` depend on `devices`;
`devices` depends on nothing from the application.

### On cloning

```bash
git clone https://github.com/irydeo/solarscribe.git
cd solarscribe
```

Open OpenCode at the **repository root**: that way it loads `AGENTS.md` and
discovers the agents in `.opencode/agents/`. The full process for the AI is in
[`design/BOOTSTRAP.md`](design/BOOTSTRAP.md).

### Agent team

Seven agents. Each one **owns** some modules and **custodies** some ADRs. The
operational details live in `.opencode/agents/*.md` and their readable version in
[`design/AGENTS.md`](design/AGENTS.md).

| Agent | Mission | Ownership | Custody |
| --- | --- | --- | --- |
| **lead** | Layer contracts, ADRs, cross review, resolve conflicts | `design/`, `config/`, layer boundary | 000, 001, 003, 012, 018, 021 |
| **video** | That the app talks to camera and mount and the stream loses no frames | `devices/` (including `devices/sim/`), `capture/`, capture ROI | 002, 008, 010, 013, 019 |
| **shg** | That the maths is correct: limb, rate, centring, mosaic, polar, tilt | `shg/` | 006, 007, 022 |
| **ux** | That scanning is easy for anybody | `ui/`, ROI editor (UI) | 009, 011, 020 |
| **qe** | The safety net: unit (TDD), functional (mocks/videos) and performance | `tests/`, fixtures, performance bench, gates | 005, 015 |
| **packaging** | Windows and Linux functional out of the box, CI, licences, versioning | `installer/`, CI, `pyproject.toml` | 004, 017 |
| **docs** | Bilingual documentation and ES/EN `.ts` translation | `design/`, `solarscribe/docs/`, `.ts`, CHANGELOG | 000, 016 |

The **lead** is not a boss: it keeps seven agents from breaking the layer
contracts. The **qe** does not write product: it writes tests and **can block**
any change that fails the gates.

### Quality gates

Every change goes through:

- **G1 TDD**: test red, then green, then refactor.
- **G2 Functional**: a functional test with a mock or a real video.
- **G3 Performance**: the performance budget holds (ADR-013).
- **G4 Usability**: if it touches the UI, the `ux` agent reviews it with a task
  script.
- **G5 Packaging**: if it touches a release, it installs and starts on Windows and
  Linux.

**Done** = tests green, budget met, ADR updated and i18n current.

### How to work

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit        # fast, no hardware
.venv/bin/python -m pytest tests/functional  # mocks, videos and hardware
.venv/bin/python -m solarscribe gui          # start the GUI
```

### Decisions

Every architecture or design decision lives in `design/adr/` (bilingual; index in
`design/adr/README.md`). Read the ADR before changing a decision; if you change
it, write a new one that references it (accepted ones are not rewritten).
