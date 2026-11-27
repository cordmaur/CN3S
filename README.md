# CN3S

Python implementation of the CN3S (Curve Number with Three-Step Antecedent
Precipitation) rainfall–runoff model, developed by Taborga and Freitas (1987).
The repository also contains hydrological research workflows and a Flask
application for station analysis, calibration, and monthly forecasting.

## Where to look

- `src/cn3s/`: model equations and run state (`model.py`), basin and calibration
  parameters (`params.py`), calibration (`optim.py`), objectives and metrics.
- `src/hydro/`: station data, rainfall processing, forecasts, inference and
  related hydrological analysis.
- `src/hydrography/`: hydrography and watershed delineation.
- `src/utils/`: shared utilities and data connectors.
- `nbs/`: notebooks for research and data workflows.
- [`web/README.md`](web/README.md): SHC application, CN3S screens, data paths,
  local development and deployment.
- `agents/iterations/`: task plans and session records, including verification
  and decisions; see [AGENTS.md](AGENTS.md) for the project workflow.

The implementation and docstrings are the source for current interfaces and
scientific details. Iteration records explain the history of particular changes;
they do not replace the current code or documentation.

## Installation

The declared Python minimum and dependencies are in [pyproject.toml](pyproject.toml).
Install the package in editable mode with `pip install -e .`; the development
and web extras are available as `pip install -e '.[dev]'` and
`pip install -e '.[web]'`. Research notebooks and external data access may require
additional environment-specific dependencies and credentials; see the notebooks
and the web README for their respective workflows.
