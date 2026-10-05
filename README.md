# CN3S

CN3S is a Python implementation of the rainfall–runoff model described by Taborga and Freitas (1987). It combines a Curve Number runoff calculation, antecedent precipitation, and a groundwater store to turn basin rainfall into estimated discharge. The repository also contains tools to delineate upstream watersheds, prepare rainfall and observed discharge for gauging stations, calibrate model parameters, and map calibration quality.

The original model is monthly. This implementation can run at **monthly (`M`) or daily (`D`) steps**; the daily application is an extension explored in this repository. It is currently a research and calibration workflow, not a production forecasting service.

## What is here

| Location | Purpose |
| --- | --- |
| `src/cn3s/model.py` | `CN3SParams` and the stateful `CN3S` simulation. |
| `src/cn3s/metrics.py`, `objectives.py`, `optim.py` | NSE scoring, calibration objectives, and SciPy differential evolution. |
| `src/cn3s/workflow.py` | Per-station data preparation, calibration, saved results, and quality maps. |
| `src/hydrography/` | Basin overview, watershed-based Otto assignment, upstream selection, and mapping. |
| `src/utils/` | Legacy basin loader, Hydro SQL client, and spatial helpers. |
| `src/hydro/` | SQL-backed historical and telemetric station access. |
| `nbs/` | Exploratory notebooks and executed development notebooks in `nbs/dev/`. |
| `tests/` | Offline tests for basin overview, station selection, and calibration. |
| `agents/iterations/` | Plans and outcomes for recorded iterations. |

`cn3s` re-exports `CN3S`, `CN3SParams`, `CN3SOptimizer`, `Objective`, `Objectives`, `HydroDischargeSource`, and `StationCalibrationWorkflow`. `hydrography` re-exports `BasinOverview`, `Hydrography`, and `Stations`.

## Model and calibration

For each step, `CN3S` uses the previous `warmup_steps` rainfall values to calculate an antecedent moisture coefficient (`vj`). This adjusts the Curve Number (`cnv`) and retention (`s`). Current rainfall produces direct runoff (`q_up`) and groundwater recharge (`r1`); recession from that store produces baseflow (`q_low`). The two runoff depths are added and converted to mean discharge (`q_m3s`) using basin area. The conversion uses **one day for daily steps and a fixed 30 days for monthly steps**.

`CN3SParams` contains the basin name and area plus eight parameters represented by the optimization vector: `r0`, `cn_i`, `alfa`, `beta`, `k0`, `k1`, `k2`, and integer `act` (a discharge timing shift in days). `warmup_steps` controls the number of antecedent rainfall values and the initial rows excluded from results. `CN3S.run()` takes a dated `pandas.Series` of rainfall in mm and stores the simulated series in `model.results`; `evaluate()` aligns observed discharge in m³/s and computes Nash–Sutcliffe efficiency (NSE). The model object retains results and groundwater state during a run, so use `run()` again to start a fresh series.

`CN3SOptimizer` calibrates seven monthly or eight daily parameters with SciPy differential evolution. It divides the aligned record chronologically using a fixed date cutoff, then scores the final parameter vector on distinct training and held-out test periods. The workflow defaults to the `PlainNSE` objective, an 80/20 split, three warmup steps, and 100 optimizer iterations with one worker. `NSETopBlend` and custom objectives are also available. A completed optimization can still have `converged: false` when SciPy reaches its iteration limit.

## Basin overview

`BasinOverview` starts from a basin GeoParquet and the telemetric station GeoParquet. The current `Stations` loader filters source records to numeric `ESTRESPONSAVEL == 1`, `OGMORGAO == "RHN"`, and `ESTSTATUS == 0`, then groups by the textual `ESTCODIGOADICIONAL` key. The record with the highest numeric `ESTCODIGO` wins within each group. Leading zeros in the station key are preserved. `Stations.assign_cobacia()` spatially joins the resulting points to the watersheds in `Hydrography` and records the matching `cobacia`, network version, and assignment status.

```python
from pathlib import Path

from hydrography import BasinOverview, Hydrography

data_root = Path("/data/CN3S")
network_root = Path("/data/Geospatial_BR_Data/Hidrografia/BHO_2017_5k")
hydro = Hydrography(
    watersheds_path=network_root / "geoft_bho_2017_5k_area_drenagem.parquet",
    reaches_path=network_root / "geoft_bho_2017_5k_trecho_drenagem.parquet",
)
overview = BasinOverview(
    data_root / "geoparquets/geoparquets/bacia_Doce.parquet",
    data_root / "Estacoes_Telemetricas.parquet",
    hydro,
)
stations_in_basin = overview.station_table()
summary = overview.summary()
fig = overview.figure()
```

The current Doce inputs produce 16 filtered, grouped stations, all assigned to one BHO 5k watershed. The source station file has no CRS metadata; the loader assigns the agreed EPSG:4674. Basin files that declare another CRS are transformed to EPSG:4674. An unmatched, ambiguous, or reach-missing watershed assignment remains visible in the table and cannot be used for upstream selection until resolved. The map uses `Hydrography.plot_reaches()` to scale river widths and show reaches within the axes, including those outside the basin polygon. The [basin overview notebook](nbs/dev/01-basin-overview.ipynb) shows the current reusable entry point. Larger basins may need `overview.figure(labels=False)` alongside the station table.

## Station calibration workflow

The last iteration added `StationCalibrationWorkflow` to connect the geospatial and model components:

1. `Hydrography` loads reaches and watershed polygons. `Stations` associates station codes (`CÓDIGO`) with Otto basin codes (`cobacia`).
2. `prepare_station()` selects and dissolves the upstream watersheds. It sums their `nuareacont` values for the **calibration area in km²** and separately records the station's reported `AreaDrenagem` when present. It fetches mean areal MERGE rainfall and daily Hydro `Vazao`; monthly discharge is the mean of daily values.
3. `load_station()` reads saved inputs and checks that rainfall covers every requested day or month.
4. `calibrate_station()` fits one chosen frequency and saves the final parameters, train/test metrics, optimization history, and modeled discharge.
5. `quality_data()` and `plot_quality()` show held-out test NSE for stations with a current calibration in a named `RIO` basin. Stations without a current finite test NSE appear gray.

Example, using an Otto-referenced station GeoParquet with `CÓDIGO`, `cobacia`, and `RIO`:

```python
import matplotlib.pyplot as plt

from cn3s import HydroDischargeSource, StationCalibrationWorkflow
from hydrography import Hydrography, Stations
from utils.hydrology import Hydrology

hydro = Hydrography("/path/to/watersheds.parquet", "/path/to/reaches.parquet")
stations = Stations("/path/to/otto-referenced-stations.parquet", hydro)

hydrology = Hydrology()
workflow = StationCalibrationWorkflow(
    stations, data_root="/data/CN3S", discharge_source=HydroDischargeSource(hydrology)
)
metadata = workflow.prepare_station(56920000, "2000-01-01", "2025-12-31", ("M",))
hydrology.close()

offline = StationCalibrationWorkflow.from_prepared("/data/CN3S")
summary = offline.calibrate_station(56920000, "M", max_act=0)

fig = offline.calibration_figure(56920000, "M")
```

For calibration, the station file must contain `CÓDIGO` (as a column or index) and `cobacia`; quality maps also require `RIO`. Reaches need `cobacia`, `cocursodag`, `nuareamont`, and `dsversao`. Watersheds need `cobacia`, `dsversao`, and numeric `nuareacont`. The station's `cobacia` must exist in the reach network, with matching watershed codes and network versions. The telemetric file used by `BasinOverview` does not supply `RIO` or `AreaDrenagem`, so the old quality map and area comparison need additional station metadata before using that path.

The MERGE rainfall adapter is created when a preparation workflow has `Stations`. Hydro access requires an explicitly supplied discharge source; `HydroDischargeSource` borrows a caller-owned `Hydrology` instance. `Hydrology()` requests Azure authentication when constructed. The offline workflow creates no source clients. `rain_source` and `discharge_source` can also be supplied for other sources or tests; their `fetch()` contracts are defined in `workflow.py`. The `merge-downloader` package is installed from a Git branch by the dev container and is not declared in `pyproject.toml`.

The MERGE provider opens one source day or month at a time and crops to the watershed's grid window before averaging. This keeps long preparation windows within memory. Each calibration summary also records the ACT bound, optimizer options, split date, and paired train/test counts; the fitted parameters retain the station name.

The four [development notebooks](nbs/dev/README.md) cover basin overview, live data preparation, calibration from saved inputs, and offline evaluation with manual parameter experiments. Monthly calibration fixes `act=0`; daily calibration can optimize ACT in days. The prior [56696000 notebook](agents/iterations/2026-09-29-monthly-station-56696000-calibration/02-2026-09-29-monthly-station-56696000-calibration.ipynb) is retained with its original outputs.

### Saved data

The default root is `/data/CN3S`; `data_root` changes it. One station uses:

```text
stations/<station_code>/
├── watershed.parquet
├── metadata.json
├── rain/
│   ├── daily/<year>.parquet
│   └── monthly.parquet
├── discharge/
│   ├── daily.parquet
│   └── monthly.parquet
└── calibration/<D-or-M>/
    ├── summary.json, history.parquet, modeled.parquet  # retained legacy fit, if present
    ├── latest.json                                  # newest complete calibration
    ├── selected.json                                # optional explicit selection
    ├── attempts/<run_id>.json                        # status + callback-best recovery
    └── runs/<run_id>/
        ├── manifest.json                            # schema, code provenance, hashes
        ├── summary.json
        ├── history.parquet
        ├── modeled.parquet                          # all simulated dates, including gaps in Qobs
        └── inputs/                                  # rain, discharge, metadata, watershed if available
```

Daily rain is fetched in year-sized chunks within the requested date window; monthly rain is fetched directly, including boundary months. Rain is saved as `prec`, discharge as `Vazao`, and dates are normalized to calendar days or month starts. The shared raw MERGE cache is under `downloads/`. Older notebook data in `/data/CN3S/basins/` use a separate layout and are not migrated by this workflow.

Repeating preparation for the same window reuses saved inputs. A different date window, hydrography version, or upstream contribution area requires `refresh=True`. Refreshing gives the affected inputs a new revision; existing calibration files remain on disk but no longer count as current on the quality map. Prepare enough observations for warmup plus meaningful train and test periods.

### Evaluation and manual experiments

```python
from cn3s import CalibrationEvaluation, CalibrationStore, ModelPlayground

store = CalibrationStore("/data/CN3S")
store.list_runs("56610000", "D")
evaluation = CalibrationEvaluation.from_run(
    "/data/CN3S", station_code="56610000", frequency="D", run_id="latest",
)
evaluation.metrics("test")
evaluation.hydrograph(rainfall=True)
playground = ModelPlayground(evaluation)
playground.widget()                       # notebook numeric controls + Run/Reset/Save
trial = playground.run({"k1": 0.2})       # plain Python alternative; one simulation
playground.comparison("test")            # common-date reference/trial scores
# Explicit optional writes:
# experiment_id = playground.save("lower-recharge experiment")
# store.select("56610000", "D", "<completed-calibration-run-id>")
```

Evaluation provides NSE, original KGE and its components, RMSE/MAE, signed bias,
calendar-weighted volume bias, coverage, climatology/persistence baselines, scatter,
residuals, flow-duration, seasonal and optimization-history plots. Undefined metrics
include reasons. Daily/monthly runs can be compared with `evaluation.compare(other,
monthly=True)` using complete daily months and common observed values. Manual trials
retain the reference forcing, area and split, and use separate model instances.
Repeated test-period tuning is exploratory validation, not independent forecast skill.

Calibration prints its phases even with SciPy `disp=False` (disable with
`progress=False`). `polish=True` now requests a separate L-BFGS-B refinement, with
`polish_maxiter=50` and `polish_maxfun=500` by default. The evaluation cap is enforced before each model call; if exhausted, the DE
solution is retained and the budget stop is reported. Requested/effective settings, counts, stop reasons,
pre/post objectives and phase timings are saved. `polish=False` skips that phase.
The final best vector is simulated once and reused for metrics and storage.
An interrupt after a completed generation saves a labeled recovered result without
moving latest or selected; attempt JSON also records callback-best parameters. This
supports a restart from those parameters, not exact population/RNG continuation.

New results use immutable run IDs and checksummed input snapshots. Manual experiments
and interrupted results never replace the latest complete calibration. Legacy flat
files stay unchanged and are exposed as `legacy`; direct file readers should migrate
to `CalibrationStore`. New runs remain historically evaluable after input refresh;
legacy replay requires matching prepared inputs. The optional selected pointer is
used by quality maps; selection does not happen automatically by test NSE.

## Hydro station access

`hydro` provides `Hidro`, `Telemetria`, and `Station` for local SQL access without
Spark or Databricks mounts. Install `pip install -e ".[workflow,notebook]"` and make
ODBC Driver 18 available. Importing the package and constructing its providers do
not authenticate; querying a default provider creates a `SqlConnector` and starts
Azure device-code authentication.

```python
from hydro import Hidro, Station, Telemetria
from utils.sql_connector import SqlConnector

connector = SqlConnector()
hidro = Hidro(connector)
telemetria = Telemetria(connector)
try:
    station = Station(
        56610000, hidro=hidro, telemetria=telemetria,
        start="2015-01-01", end="2025-01-01",
    )
    inventory = station.info
    telemetric_inventory = station.telemetric_info
    sources = station.available_series()
    discharge = station.get_series("hidro/telemetria", "vazao")
    stage = station.get_series("hidro", "cota")
    ax = station.plot_series("hidro/telemetria", "vazao")
finally:
    connector.close()
```

Historical data use `hidro.pivotcotas` and `hidro.pivotvazoes`. Daily series require
`MediaDiaria`, `NivelConsistencia`, and `cota_data`/`cota_val` or
`vazao_data`/`vazao_val`. Only daily means (`MediaDiaria == 1`) and valid dated
measurements are retained. `Hidro.get_series()` accepts `raw`, `validated`, or
`combined`; combined selects the highest available consistency for each day.
Returned frames have a sorted `Data` datetime index, `val`, and `Sistema`.
Empty results return an empty DataFrame rather than `None`.

Historical inventory and rating-curve tables are resolved from SQL metadata using
`estacao`/`tb_estacao` and `curvadescarga`/`tb_curvadescarga` in schema `hidro`.
Override with `Hidro(connector, stations_table="schema.table", curves_table="schema.table")`
when names differ or metadata is unavailable. Inventory needs `Codigo` and `Nome`;
rating curves retain the copied coefficients and centimetre stage-range contract.
`get_rating_curves()` and `compute_stage_from_flow()` fetch curves only on request.
The existing 20% extension of outer stage limits remains in place.

Telemetry uses `hidroInfoAna.Estacao`, `origem`, `cotas`, and `vazoes`. Inventory joins
`ESTORIGEM` to `OGMCODIGO`, and associates historical codes through `ESTANEELFLU`.
Observations use `HORESTACAO`, `HORDATAHORA`, and `HORNIVELADOTADO` or `HORVAZAO`.
Measurements are averaged by calendar day. `Station` gives historical records
precedence, followed by telemetric origin precedence (RHN first). Unknown origins
are retained after known origins. Date windows are filtered in SQL, with the entire
end day included. Sanitization replaces existing daily measurements without
modifying the cached source frames.

A default `Station` owns a shared connection and supports `with Station(...) as station:`.
Injected providers and connectors remain caller-owned. `Station.get_series()` now
returns a DataFrame directly, without the copied statistics tuple. Statistics and
reporter modules are deferred and are not part of the supported local API yet.
The existing `utils.hydrology.Hydrology` and calibration adapter remain available.
See [05-hydro-station.ipynb](nbs/dev/05-hydro-station.ipynb) for the live notebook.

## Setup and checks

The package metadata declares Python **3.10 or newer**; the repository's `AGENTS.md` specifies **3.11 or newer** for development. Use Python 3.11 or newer until those requirements are reconciled.

```bash
pip install -e ".[dev,workflow]"
python -m pytest -q
ruff check src/cn3s/workflow.py src/hydrography/stations.py tests
mypy src/cn3s
```

The `workflow` extra installs Azure and SQL client dependencies, but a local ODBC driver, credentials, external data, and `merge-downloader` are still needed for live preparation. The dev container provides its own setup. `make check` runs `ruff check . --fix` and mypy, so it may edit files. The targeted Ruff command above passes; a broader check of `src/cn3s`, `src/hydrography`, and `tests` currently reports 14 pre-existing issues. Existing notebooks and legacy utilities are exploratory and are not fully covered by the tests or repository-wide linting.

## Current iteration boundaries

- The basin overview iteration is recorded in [`agents/iterations/2026-09-29-basin-overview-telemetric-stations/outcome.md`](agents/iterations/2026-09-29-basin-overview-telemetric-stations/outcome.md). The earlier [station calibration iteration](agents/iterations/2026-09-29-station-calibration-workflow/outcome.md) covers preparation, calibration, and quality maps. The current test suite passes without MERGE or Hydro access.
- Monthly ACT is fixed to zero and nonzero values are rejected. Daily ACT shifts simulated response dates; evaluation rainfall stays on its original forcing dates.
- Live MERGE download and Hydro authentication have not been validated by the offline suite. The seasonal forecast notebook is exploratory; no integrated forecast workflow is provided.
- Several older notebook cells use earlier API calls or the legacy basin layout. The station workflow above and current package code are the reference for new work.

Reference: Taborga, J. and Freitas, M. A. S. (1987), *Simulação da Lâmina de Escoamento Mensal*, III Simpósio Luso-Brasileiro de Hidráulica e Recursos Hídricos, vol. 2, pp. 558–570.
