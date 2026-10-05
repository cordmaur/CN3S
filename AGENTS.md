# CN3S — Working instructions

This repository contains **research code**, not production software.

The main goals are:

1. scientific correctness
2. human readability
3. minimal code
4. easy inspection and modification
5. reproducibility

Do not optimize for production-grade robustness, extensibility, scalability, or architectural purity unless explicitly requested.

These instructions apply to every assistant session in this repository. This file is the
main source for the iteration protocol. The project overview and current technical state
are in `README.md`; historical iteration records are in `agents/iterations/`.

## Session and iteration protocol

1. **Ask at the start of every session:** "Should this session be recorded as an iteration?"
   Ask before substantive project work, even if the opening request seems small. If the
   user already answered in the opening message, acknowledge that answer and proceed.
   Do not assume that every session is recorded.
2. **Discuss requirements first.** Inspect relevant existing code, notebooks, data
   contracts, and previous iteration records as needed. Establish the objective, scope,
   expected behavior, constraints, acceptance criteria, and open decisions with the user.
   In particular, treat `nbs/01-Initial_Tests.ipynb` as an exploratory sketch of a broader
   station-to-basin workflow; do not assume the existing `StationCalibrationWorkflow`
   completes every part of that sketch.
3. **If the session is recorded, create its folder after the initial requirements
   conversation.** Use `agents/iterations/YYYY-MM-DD-short-descriptive-slug/`; add a
   numeric suffix if that name already exists. Create `plan.md` there before any
   implementation. If the user declines recording, discuss and plan in the conversation
   without creating an iteration folder.
4. **Write a detailed `plan.md` for a recorded iteration.** Include:
   - objective and background, with links to relevant repository paths and prior records;
   - agreed requirements and explicit out-of-scope items;
   - current behavior and the gap to close;
   - proposed design, data flow, interfaces, and affected files;
   - implementation steps in order, with dependencies and migration or compatibility
     considerations where relevant;
   - validation plan and concrete acceptance criteria;
   - unresolved questions, assumptions, and risks.
   Keep the plan current when requirements change. Mark unresolved decisions clearly;
   do not present guesses as agreed requirements.
5. **Stop at the plan boundary.** Do not write or alter implementation code, tests,
   notebooks, schemas, or runtime configuration until the user explicitly asks to
   implement. A request to analyze, discuss, draft, or revise a plan is not an
   implementation request. Creating or editing the iteration plan is allowed during
   planning. Present the plan for review and wait for an explicit implementation request.
6. **After implementation is requested,** follow the agreed plan, record material
   decisions or scope changes in `plan.md`, run relevant checks, and write `outcome.md`
   in the same folder. The outcome should state what changed, how it was verified,
   remaining limitations, and any departures from the plan. Never claim a check passed
   unless it ran.

The recording choice applies to the session. A later user instruction can change it.
If the user asks to record a session after work has begun, create the iteration folder
and reconstruct the requirements and decisions already made before proceeding.

## Project context

CN3S implements the Taborga and Freitas (1987) rainfall–runoff model as an installable
Python package. The model supports monthly and experimental daily steps. The repository
also contains hydrography and station selection tools, a per-station calibration workflow,
and exploratory notebooks. The one-station workflow and its decisions are recorded in
`agents/iterations/2026-09-29-station-calibration-workflow/outcome.md`.

```text
src/cn3s/          Model, objectives, optimizer, and station calibration workflow
src/hydrography/   Otto-code network, watershed, and station tools
src/utils/         Data access and spatial helpers
nbs/              Exploratory notebooks, including the initial workflow sketch
tests/            Offline station and workflow tests
```

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

## Repository conventions

- Use Python 3.11 or newer for development. `pyproject.toml` currently declares
  `>=3.10`; reconcile the discrepancy in a future iteration rather than assuming it
  is already resolved.
- Use `from __future__ import annotations` in Python modules and concise Google-style
  docstrings where useful. Keep type hints simple and respect the existing strict
  mypy settings for `src/cn3s` without adding unnecessary type machinery.
- Follow the repository's Ruff configuration (100-character line length).
- Keep model equations in `src/cn3s/model.py`. Put other behavior in the closest
  appropriate existing module; create a new module only when it improves clarity.
  Re-export public APIs from `src/cn3s/__init__.py` where appropriate.
- Keep development notebooks as thin, readable entry points to reusable package
  functions or existing stateful APIs. Make the scientific processing steps visible;
  do not introduce classes merely to move notebook code into the package. Number
  notebooks and use the existing autoreload convention.
- Run relevant existing checks and representative scientific sanity checks. Do not
  create or expand a formal test suite unless explicitly requested. Avoid `make check`
  during read-only review because its Ruff target includes `--fix` and can edit files.

Install locally with `pip install -e ".[dev,workflow]"`. Live MERGE and Hydro access
need additional external data, credentials, and the MERGE downloader described in
`README.md`.
