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
    __init__.py   # Re-exports CN3S and CN3SParams from model
    model.py      # Model implementation: CN3SParams dataclass + CN3S class
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
- All model code lives in `model.py`; `__init__.py` only re-exports `CN3S` and `CN3SParams`
- `CN3SParams` is a `@dataclass` in `model.py` holding all basin descriptors and calibration parameters
- `CN3S` is a pure-computation class in `model.py` that takes `CN3SParams` in `__init__`; each method represents one equation from the original paper
- Method naming follows the paper notation: `vj`, `cnv`, `s`, `q_up`, `r1`, `q_low`, `r`, `q_calc_mm`, `q_calc_m3s`
- All outputs are `float`; numpy arrays only appear as input to `vj` (past precipitation)
- No global state — every time step receives explicit inputs
- Never add new classes or functions directly to `__init__.py`; always implement in `model.py` (or a new dedicated module) and re-export from `__init__.py`

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

## Research-code guidelines

The following guidelines govern research work in this repository alongside the CN3S
conventions above. Preserve the existing `CN3S` and `CN3SParams` design; the preference
for functions applies to new code and does not require refactoring those classes.
Keep type annotations on all function signatures, using simple types, and retain
Google-style docstrings for meaningful functions without unnecessary boilerplate.

This repository contains **research code**, not production software.

The main goals are:

1. scientific correctness
2. human readability
3. minimal code
4. easy inspection and modification
5. reproducibility

Do not optimize for production-grade robustness, extensibility, scalability, or architectural purity unless explicitly requested.

## General coding style

Prefer the **simplest clear implementation** that solves the current task.

Favor:

- direct code over abstraction
- functions over classes
- existing patterns over new patterns
- explicit processing steps over indirection
- readable intermediate variables over clever expressions
- fewer files and fewer layers
- standard Python and existing dependencies

Do not write code for hypothetical future requirements.

A small amount of duplication is acceptable if it makes the scientific workflow easier to understand.

Do not reduce line count at the expense of readability. The goal is **minimal and understandable code**, not code golf.

## Avoid overengineering

Do not introduce production-style architecture unless it is clearly necessary.

Avoid by default:

- service layers
- repository patterns
- dependency injection
- factories
- plugin architectures
- abstract base classes
- complex class hierarchies
- generalized frameworks
- elaborate configuration systems
- extensive validation layers
- custom exception hierarchies
- retry frameworks
- unnecessary logging infrastructure
- compatibility layers
- unnecessary type machinery
- abstractions created only for possible future reuse

If a task seems to require a significant abstraction, new architecture, framework, or class hierarchy, **ask before implementing it**.

Briefly explain:

1. what problem the abstraction solves
2. why a simpler implementation is insufficient
3. what complexity it adds

Small helper functions that clearly improve readability do not require approval.

## Keep changes local

Modify the minimum amount of code necessary.

Do not:

- refactor unrelated code
- rename unrelated functions or variables
- reorganize files unnecessarily
- redesign existing architecture during a feature change
- clean up unrelated technical debt
- modify code merely because there is a "better" pattern

If you notice unrelated problems, mention them instead of fixing them automatically.

## Research workflow first

Important scientific processing should remain visible and easy to trace.

Prefer code that reads roughly like the research workflow:

```python
swot = load_swot(path)
swot = filter_quality_flags(swot)
swot = swot.rio.reproject_match(reference)

water_mask = swot.water_frac >= threshold
metrics = calculate_metrics(water_mask, reference)
```

Avoid hiding important scientific operations behind many classes, wrappers, managers, services, or nested abstractions.

A researcher should be able to follow how the input becomes the output without navigating through many files.

## Documentation

The code should be understandable months later without requiring reconstruction of the original reasoning.

Document:

- scientific assumptions
- algorithms
- equations
- thresholds
- units
- coordinate systems
- dataset conventions
- transformations
- important methodological decisions
- non-obvious implementation choices

Use concise docstrings for meaningful functions.

Comments should explain **why**, not repeat obvious Python syntax.

Good:

```python
# SWOT water fraction ranges from 0 to 1.
water_mask = water_frac >= 0.5
```

Avoid:

```python
# Check whether water fraction is greater than or equal to 0.5.
water_mask = water_frac >= 0.5
```

Do not add documentation boilerplate just for completeness.

## Functions and classes

Prefer functions.

Create a class only when:

- persistent state is genuinely useful, or
- the domain naturally represents a stateful object.

Do not create classes merely to group related functions.

Prefer:

```python
def calculate_water_mask(water_fraction, threshold=0.5):
    ...
```

over introducing processors, managers, services, factories, strategies, or similar structures without a clear need.

## Tests

Do **not** create or expand a formal test suite unless explicitly requested.

Codex may use temporary tests, assertions, scripts, sample calculations, or other checks internally to verify that a change works.

Temporary verification code should normally be removed before finishing.

Do not automatically create:

- test directories
- pytest suites
- fixtures
- mocks
- test frameworks
- exhaustive edge-case tests

For numerical and scientific changes, prefer a small representative sanity check when useful.

Correctness is important; maintaining production-style test infrastructure is not a default goal of this repository.

## Validation and error handling

Handle errors that are realistically expected in the actual research workflow.

Do not add extensive defensive programming for hypothetical misuse.

Internal functions do not need to validate every possible input type if the repository controls how they are called.

Prefer clear failures over large amounts of defensive code.

Do not silently hide scientific or data-quality problems.

## Dependencies

Prefer libraries already used by the repository.

Do not add a new dependency when the task can reasonably be solved with existing dependencies or the Python standard library.

Ask before introducing a significant new dependency.

## Type hints

Use type hints when they improve understanding.

Do not introduce complicated typing constructs solely to satisfy theoretical type completeness.

Avoid complex generics, protocols, type hierarchies, or excessive annotations unless they materially improve the research code.

Clarity is more important than sophisticated typing.

## Before implementing

For any non-trivial change, first consider:

1. What is the simplest solution?
2. Can existing code handle this with a small modification?
3. What is the minimum number of files that need to change?
4. Am I introducing anything only because it might be useful later?
5. Is there a direct implementation that a researcher would understand more easily?

If the implementation starts becoming substantially more complex than the requested feature, stop and reconsider the design.

If significant additional architecture appears necessary, ask before proceeding.

## After implementing

Review the implementation specifically for unnecessary complexity.

Check whether:

- a class can become a function
- a helper can be removed
- multiple layers can become one
- unnecessary validation was added
- hypothetical future requirements were implemented
- unrelated code was changed
- important scientific operations became hidden
- the same behavior can be expressed more directly

Simplify when possible without reducing clarity or correctness.

## Scope discipline

Implement what was requested.

Do not expand the task because additional improvements seem useful.

If something outside the requested scope looks important, mention it separately.

Do not implement it unless it is necessary for the requested change.

## Default decision rule

When multiple approaches are reasonable, choose the one with:

- fewer concepts
- fewer abstractions
- fewer files
- fewer dependencies
- less indirection
- less code

provided that it remains readable and scientifically correct.

The default philosophy of this repository is:

> **Simple, explicit, documented research code is preferred over robust, generalized production architecture.**

When a more complex solution genuinely appears necessary, explain why and ask before introducing it.
