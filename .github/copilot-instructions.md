# CN3S Project — Copilot Instructions

## Project Overview
CN3S (Curve Number with Three-Step Antecedent Precipitation) is a deterministic monthly
rainfall-runoff model developed by Taborga & Freitas (1987), widely applied to Brazilian
river basins. This repository implements the model as an installable Python package.

## Repository Structure
```
.devcontainer/    # Dev container configuration (Docker)
.github/          # GitHub workflows and Copilot instructions
.vscode/          # Editor settings and recommended extensions
nbs/              # Jupyter notebooks for exploration and testing
src/
  cn3s/
    __init__.py   # Re-exports CN3S and CN3SParams from core
    core.py       # Model implementation: CN3SParams dataclass + CN3S class
pyproject.toml    # Build config; install with: pip install -e .
```

## Package Conventions

### Language & Style
- Python ≥ 3.11
- Type annotations on **all** function signatures (`from __future__ import annotations`)
- `ruff` for linting and formatting (line length 100, enforced via `.vscode/settings.json`)
- `mypy` for static type checking in strict mode
- Google-style docstrings with `Args:` and `Returns:` sections

### Model Implementation (`src/cn3s/`)
- All model code lives in `core.py`; `__init__.py` only re-exports `CN3S` and `CN3SParams`
- `CN3SParams` is a `@dataclass` in `core.py` holding all basin descriptors and calibration parameters
- `CN3S` is a pure-computation class in `core.py` that takes `CN3SParams` in `__init__`; each method represents one equation from the original paper
- Method naming follows the paper notation: `vj`, `cnv`, `s`, `q_up`, `r1`, `q_low`, `r`, `q_calc_mm`, `q_calc_m3s`
- All outputs are `float`; numpy arrays only appear as input to `vj` (past precipitation)
- No global state — every time step receives explicit inputs
- Never add new classes or functions directly to `__init__.py`; always implement in `core.py` (or a new dedicated module) and re-export from `__init__.py`

### Notebooks (`nbs/`)
- Notebooks are numbered and prefixed: `01-`, `02-`, etc.
- Always load with `%autoreload 2` and `%load_ext autoreload`
- Import the package as `from cn3s import CN3S, CN3SParams`

## Dev Container
- Image: `cordmaur/planetary:v5`
- Extensions installed automatically: `charliermarsh.ruff`, `ms-python.mypy-type-checker`, `ms-toolsai.jupyter`
- After container creation, the package is installed in editable mode automatically via `postCreateCommand`
- Data mounts are configured via the `CN3S_DATA_FOLDER` environment variable on the host

## Build & Install
```bash
pip install -e .                  # install package in editable mode
pip install -e ".[dev]"           # include dev dependencies (mypy, ruff, pytest)
```
