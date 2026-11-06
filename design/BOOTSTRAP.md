# Bootstrap del repositorio / Repository bootstrap

*Proceso para la IA al clonar el repositorio.*
*Process for the AI when cloning the repository.*

---

## Español

SolarScribe vive en **un único repositorio público**: el código y el diseño
viajan juntos, no hay submódulos. Sigue este orden.

### 1. Clonar

```bash
git clone https://github.com/irydeo/solarscribe.git
cd solarscribe
```

### 2. Comprobar el layout

- `AGENTS.md` y `.opencode/` en la raíz: reglas y agentes.
- `design/`: diseño, contratos y ADRs.
- `solarscribe/`: el paquete Python; `tests/`, `installer/` y `docs/` al lado.

### 3. Leer las fuentes de verdad, en este orden

1. `AGENTS.md`: reglas, equipo y gates.
2. `design/DESIGN.md`: diseño marco.
3. `design/ARCHITECTURE.md`: contratos entre capas y modelo de datos.
4. `design/adr/README.md`: índice de decisiones; lee el ADR que vayas a tocar.

### 4. Preparar el entorno

Los comandos se ejecutan **desde la raíz del repositorio**:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit
```

### 5. Ejecutar el arnés desde la raíz

Abre OpenCode en la **raíz del repositorio**: así carga `AGENTS.md` y descubre los
agentes de `.opencode/agents/`.

### 6. Dónde va cada cambio

- **Código** -> dentro de `solarscribe/`.
- **Diseño, ADRs, agentes** -> dentro de `design/` y `.opencode/`.
- **Guía de usuario** -> dentro de `docs/`.

### 7. Si faltan los modelos

Los `.opencode/agents/*.md` fijan un `model:` del proveedor `fireworks-ai`. Si en
esta máquina no está disponible, cambia ese campo por un modelo equivalente; el
resto de la definición no depende del modelo.

### 8. Reglas duras

- **TDD estricto**: la prueba en rojo va antes de tocar el producto.
- Todo cambio pasa por los gates G1-G5 de `AGENTS.md`.

---

## English

SolarScribe lives in a **single public repository**: the code and the design
travel together, there are no submodules. Follow this order.

### 1. Clone

```bash
git clone https://github.com/irydeo/solarscribe.git
cd solarscribe
```

### 2. Check the layout

- `AGENTS.md` and `.opencode/` at the root: rules and agents.
- `design/`: design, contracts and ADRs.
- `solarscribe/`: the Python package; `tests/`, `installer/` and `docs/` beside
  it.

### 3. Read the sources of truth, in this order

1. `AGENTS.md`: rules, team and gates.
2. `design/DESIGN.md`: framework design.
3. `design/ARCHITECTURE.md`: layer contracts and data model.
4. `design/adr/README.md`: decision index; read the ADR you are about to touch.

### 4. Set up the environment

The commands run **from the repository root**:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit
```

### 5. Run the harness from the root

Open OpenCode at the **repository root**: that way it loads `AGENTS.md` and
discovers the agents in `.opencode/agents/`.

### 6. Where each change goes

- **Code** -> inside `solarscribe/`.
- **Design, ADRs, agents** -> inside `design/` and `.opencode/`.
- **User guide** -> inside `docs/`.

### 7. If the models are missing

The `.opencode/agents/*.md` set a `model:` from the `fireworks-ai` provider. If it
is not available on this machine, change that field for an equivalent model; the
rest of the definition does not depend on the model.

### 8. Hard rules

- **Strict TDD**: the red test comes before touching the product.
- Every change goes through gates G1-G5 of `AGENTS.md`.
