# CN3S Project — Copilot Instructions

## Project Overview
CN3S (Curve Number with Three-Step Antecedent Precipitation) is a deterministic monthly
rainfall-runoff model developed by Taborga & Freitas (1987), widely applied to Brazilian
river basins. This repository implements the model as an installable Python package.

## Repository Structure
```
src/cn3s/        # Model, parameters, calibration, objectives, and metrics
src/hydro/       # Stations, rainfall, forecasts, inference, and related analyses
src/hydrography/ # Hydrography and watershed processing
src/utils/       # Shared utilities and data connectors
web/             # Flask application, templates, and browser assets
nbs/             # Jupyter research workflows
agents/iterations/ # Plans and session records
pyproject.toml   # Package metadata, dependencies, Ruff and mypy configuration
```
The code and `pyproject.toml` are the authoritative sources for current interfaces
and package requirements. Inspect relevant implementation and callers before changes.

## Package Conventions

### Language & Style
- Python support is declared in `pyproject.toml` (currently ≥ 3.10); do not raise
  the minimum version without an explicit decision.
- Type annotations on **all** function signatures (`from __future__ import annotations`)
- `ruff` for linting and formatting (line length 100, enforced via `.vscode/settings.json`)
- Before finishing an iteration, run `ruff format --check` and the full `ruff check`
  with the repository configuration on every Python file created or modified in that
  iteration. Do not restrict checks to a subset of rules; fix all new findings before
  handing off. Report any remaining pre-existing findings that prevent a clean check.
- Follow enabled Ruff rules while implementing: assign exception messages to a local
  variable before raising, avoid raising inside a `try` just to catch the exception in
  that same block, use explicit `strict=` for `zip`, and avoid accessing private members.
  Use narrowly scoped, explained `noqa` exceptions only for justified existing APIs.
  Respect the project's configured ignores, including `TRY003` and `COM812`.
- `mypy` for static type checking in strict mode
- Google-style docstrings with `Args:` and `Returns:` sections where applicable.
- Every method, including properties and special methods, must have a Google-style
  docstring. Document arguments and return values where applicable, with units and
  scientific assumptions when relevant. Keep multiline docstring formatting consistent.
- Include concise comments explaining scientific processing, methodological decisions,
  and non-obvious behavior rather than restating Python syntax.

### Model Implementation (`src/cn3s/`)
- `params.py` defines `CN3SParams`; `model.py` defines `CN3S` and its model equations.
  `optim.py`, `objectives.py`, and `metrics.py` support calibration and evaluation.
- `__init__.py` re-exports the public model, parameter, optimizer, and objective APIs.
  Implement new functionality in an appropriate module, not directly in `__init__.py`.
- Preserve the existing `CN3S` and `CN3SParams` design. `CN3S` retains results and
  state during runs; inspect `step`, `run`, and `reset` when changing that behavior.
- Model equation methods follow the paper's notation. Preserve units, time-step and
  antecedent-precipitation conventions when modifying calculations.

### Notebooks (`nbs/`)
- Notebooks are numbered and prefixed: `01-`, `02-`, etc.
- Always load with `%autoreload 2` and `%load_ext autoreload`
- Import the package as `from cn3s import CN3S, CN3SParams`
- User-configured constants in notebooks must use uppercase names with underscores
  (e.g., `STATION_CODE`, `STATIONS_DIR`, `WATERSHEDS_PATH`).

## Dev Container
- Image: `cordmaur/planetary:v5`
- Extensions installed automatically: `charliermarsh.ruff`, `ms-python.mypy-type-checker`, `ms-toolsai.jupyter`
- After container creation, the package is installed in editable mode automatically via `postCreateCommand`
- Data mounts are configured in `.devcontainer/devcontainer.json`; inspect the current host path before use.

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
Google-style docstrings on every method and on meaningful functions without unnecessary boilerplate.

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
When a calculation is particularly important and likely to change again, a small,
self-contained reference calculation with expected values and assumptions may be
preserved if it is useful; do not introduce a test framework for this purpose.

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


## Iteration records

Save each distinct work iteration's plan and session record under
`agents/iterations/YYYY-MM-DD_HH-MM-SS_<description>/plan.md`.
Use America/Sao_Paulo local time for the directory's creation timestamp.
During discussion of the same iteration, overwrite its existing plan.md in place.
Do not version plans: do not add version numbers to filenames, directory names,
or plan titles, and do not keep revision copies or create a new timestamped
folder for each discussion update. Create a new folder only for a distinct work
iteration. Do not place plan.md at the repository root.

Keep the record proportional to the work. For substantial work, make its status
clear (for example, proposed, implemented, or investigation only), and record the
objective and scope, important decisions or implementation, verification, and
limitations or pending work where applicable. Distinguish actual results from planned
checks and identify substituted data or unavailable checks. Link related iteration
records when design and implementation are separate. Include proposed method-call
examples at the end when relevant; for non-code work, state that they do not apply.
