# CN3S evaluation, calibration records, and forecast roadmap

Date: 2026-09-30. Status: **Group 1 (A/B/C plus parameter experiments) implemented**.

## Phase groups

- **Group 1 — A, B, C and interactive parameter experiments:** implemented.
  See [implementation plan](group-1/plan.md) and, after completion,
  [outcome](group-1/outcome.md). This includes `04-evaluation.ipynb` and an interface
  to change parameters and simulate without optimization.
- **Remaining phases D–H:** remain proposed and unimplemented. Their grouping will
  be chosen by the user; no additional group assignment is assumed.

The original research below is retained as background. The Group 1 plan supersedes
its earlier planning-only status and unresolved first-delivery scope.

## 1. Objective and scope

Understand the current project, identify improvements, investigate the delay after
differential evolution, and define how to evaluate whether CN3S is useful before
extending it to forecasting and additional discharge locations.

The user requested this recorded planning document and proposed a fourth development
notebook for evaluation. The opening message ends with an incomplete sentence after
requesting that notebook. Clarification was requested; this plan interprets the
immediate deliverable as planning, following the explicit repository plan boundary.
The notebook design below is ready for review, but has not been implemented.

Requested requirements:

- Review package code, current development notebooks, forecast experiments, saved
  calibrations, and the three supplied PDFs under `/data/CN3S/docs`.
- Design `nbs/dev/04-evaluation.ipynb` to load persisted calibration results without
  recalibration, supporting both daily and monthly models.
- Include observed/simulated discharge, observed-versus-simulated scatter, and rainfall
  drawn downwards from an upper secondary axis.
- Propose a defensible evaluation strategy, daily WRF and monthly seasonal forecasting,
  and use of calibrated models at other locations.
- Explain calibration finalization delays and how to distinguish saved calibrations.

Proposed boundaries for the first implementation: run identification, offline
evaluation, and calibration timing/reporting. Forecast execution, regionalization,
equation changes, mass recalibration, and production deployment are subsequent phases.
Do not reorganize historical notebooks or overwrite existing station data as part of
this planning review. All design choices below are recommendations, not accepted requirements.

Relevant project references:

- [Project overview](../../../README.md), [working rules](../../../AGENTS.md),
  [development notebook guide](../../../nbs/dev/README.md).
- [Model](../../../src/cn3s/model.py), [optimizer](../../../src/cn3s/optim.py),
  [station workflow](../../../src/cn3s/workflow.py),
  [metrics](../../../src/cn3s/metrics.py), [objectives](../../../src/cn3s/objectives.py).
- [Initial exploratory notebook](../../../nbs/01-Initial_Tests.ipynb),
  [seasonal forecast experiment](../../../nbs/Forecasts/01-C3S_Forecasts.ipynb),
  [older evaluation experiment](../../../nbs/Daily/04-Evaluate_Model.ipynb).
- [Station workflow outcome](../2026-09-29-station-calibration-workflow/outcome.md),
  [basin overview outcome](../2026-09-29-basin-overview-telemetric-stations/outcome.md),
  [generic notebook outcome](../2026-09-30-generic-workflow-notebooks/outcome.md).

## 2. How the project works now

```text
BHO reaches/watersheds + station catalogue
  -> station-to-Otto assignment -> upstream polygon + summed contribution area
  -> MERGE basin rainfall + Hydro discharge -> persisted station inputs
  -> CN3S + chronological split + differential evolution
  -> local polishing -> final simulations/scoring -> one saved result per frequency
  -> settings/parameters/NSE tables + observed/simulated hydrograph

Separate experiment: C3S seasonal precipitation -> basin averages/bias plots
                    (not connected to a calibrated CN3S forecast)
```

The geospatial layer already supports upstream selection by station or Otto code.
Calibration uses the sum of upstream `nuareacont` in km², not polygon-derived area.
`BasinOverview` offers a reusable station table and map. This is a foundation for
station-to-basin work, not yet a complete regional modeling or routing system.

`02-data-preparation` explicitly constructs external dependencies. Rainfall is saved
as daily annual Parquets or monthly totals; discharge is daily `Vazao`, with monthly
means calculated from available daily observations. The offline workflow loads these
inputs without authentication. Rainfall continuity is checked. Revision IDs detect
stale calibrations after preparation refreshes, but old input revisions are not archived.

CN3S combines antecedent rainfall, adjusted Curve Number direct runoff, groundwater
recharge, and recession. It uses rainfall and area; there is no explicit potential
evapotranspiration input. The six hydrological parameters are supplemented by fitted
initial storage `r0`, configurable antecedent length, and a daily lag `act`.
Monthly optimization searches seven parameters and fixes ACT to zero; daily
optimization searches eight. Monthly discharge conversion currently assumes 30 days.

Each objective evaluation simulates the entire rainfall record, joins observations,
and scores the training dates. State is propagated chronologically into the test
period, without using observed test discharge to update model state. The split is
fixed by date, although valid paired samples can change with daily ACT. Final
train/test scores use the final SciPy vector, potentially improved by polishing.

The actual `03-calibration` currently targets station 56610000 daily, with 50 generations,
population multiplier 5, `workers=-1`, `polish=True`, and `disp=False`. It contains two
calibration calls: antecedent lengths 5 and 10. Running all cells therefore fits twice;
the second successful fit replaces the first saved result. This is distinct from the
delay inside either individual call. The README's example settings are older.

Existing artifacts are `calibration/<D|M>/{summary.json,history.parquet,modeled.parquet}`.
They represent a fitted result, **not a resumable differential-evolution checkpoint**.
No population/RNG state or forecast-ready hydrological state is persisted.
The older Daily evaluation notebook recalibrates and uses legacy pickle histories;
it is not a suitable template for a new offline evaluator.

## 3. Evidence from current saved results

Seven summaries across five stations were inspected. All matched their current input
revision at review time; all reported `converged=false`. Completed and converged are
different concepts. These scores describe observed-rainfall simulation, not forecast skill.

For context, a simple baseline was computed from each persisted modeled table: mean
training discharge by calendar month, mapped onto the same held-out dates. This uses
no test observations for fitting. It is an exploratory baseline, not a full benchmark
study; daily persistence and robust day-of-year climatology remain to be evaluated.

| Station | Frequency | Train NSE | Test NSE | Seasonal baseline test NSE | Train/test pairs |
| --- | --- | ---: | ---: | ---: | --- |
| 56610000 | D | 0.6948 | 0.6954 | 0.3523 | 2918 / 731 |
| 56610000 | M | 0.8774 | 0.8317 | 0.4607 | 248 / 64 |
| 56696000 | D | -0.0600 | 0.3843 | 0.3856 | 1455 / 366 |
| 56696000 | M | 0.9400 | -0.3794 | 0.5594 | 45 / 12 |
| 56850000 | M | 0.8637 | 0.8746 | 0.5310 | 248 / 64 |
| 66010000 | M | 0.5834 | 0.7393 | 0.3667 | 249 / 63 |
| 67100000 | M | 0.0729 | -0.8206 | -1.2635 | 227 / 58 |

Interpretation: 56610000 and 56850000 justify further investigation; 56696000 shows why
training scores alone are insufficient. At 67100000 even the seasonal baseline is
weak, and CN3S still has negative NSE. Diagnose data, basin scale, regulation, forcing,
and model structure before prescribing a cause. Do not omit unsuccessful stations.

The daily and monthly fits have different periods and settings. Their NSE values
cannot establish that one frequency is better. Prepared rainfall also extends beyond
paired observations in some runs: 56610000 M pairs end in April 2026 despite rainfall
through August 2026. The evaluator must report actual evaluated coverage.

## 4. Why calibration appears slow after the final generation

### Confirmed code path

1. `CN3SOptimizer._callback()` prints once per DE generation. Its final message is
   the end of population evolution, not the end of `differential_evolution()`.
2. Workflow defaults and the current notebook enable `polish=True`. Installed SciPy
   **1.16.0** then calls L-BFGS-B, holding integer ACT fixed. The DE callback does not
   report those local optimizer evaluations. `disp=False` hides even the polishing
   start message. In this installed version each polishing evaluation passes a
   single candidate through the worker map; `workers=-1` does not make this equivalent
   to evaluating a full DE population in parallel.
3. Every evaluation runs the full rainfall history, including the test period.
   `CN3S.step()` creates a Series, transposes it, concatenates the growing DataFrame,
   and resets its index for every time step. This adds substantial allocation/copying.
4. After SciPy returns, `optimize()` runs `_persist_model()`. The workflow then calls
   `evaluate_best()`, running the identical final parameter vector again.
5. Finally, history and paired modeled data are written to Parquet and the summary
   to JSON. The data root is a host bind mount; write latency is possible, but was
   not measured and is not established as the principal cause.

The [SciPy 1.16 documentation](https://docs.scipy.org/doc/scipy-1.16.0/reference/generated/scipy.optimize.differential_evolution.html)
confirms the optional post-DE local search. Installed solver source was also inspected.

### Measurements made during this review

- One saved-parameter simulation for 56610000 D, 3,654 input days: **4.96 seconds**
  without profiling. A separately profiled run took 7.98 seconds, including 2.42
  cumulative seconds in `pandas.concat`; Series construction/transposition were also
  major costs. Profile timings include overhead and must not be added as independent totals.
- In-memory diagnostic using the first 60 daily rainfall values, seed 42, one DE
  generation, `popsize=2`, and one worker: with polishing disabled, 32 evaluations,
  1.63 seconds total, 0.05 seconds after the callback. With polishing enabled, 192
  evaluations, 9.28 seconds total, 7.78 seconds after the callback.
- Polishing improved that tiny diagnostic's objective substantially. Its speed and
  improvement are not estimates of the user's complete calibration. The experiment
  confirms a hidden work phase; it does not justify universally disabling polishing.

No long production calibration was repeated or saved. Exact time attribution for
the reported long run remains unavailable because phase timings and `nfev` were not saved.

### Proposed fixes

- Report phases: evolution, polishing, final simulation, scoring, artifact writes.
  Persist elapsed times, DE/local evaluation counts where observable, `nit`, `nfev`,
  stop message, requested/effective solver settings, and pre/post-polish objectives.
- Offer a quick diagnostic preset with `polish=False`, and an explicitly budgeted
  refinement phase. In SciPy 1.16 implement a separate controlled local minimization
  if a local budget is needed; do not assume newer callable-polish APIs are installed.
- Simulate the final vector once and score/store the same immutable result. Do not
  accidentally save the last candidate evaluated instead of the final best vector.
- After numerical reference tests exist, use scalar/array recurrence and build the
  result table once. Keep equations in `model.py`; preserve the public `step()` API.
- Consider training-period-only objective simulations after parity checks, followed
  by one full chronological final simulation. Handle ACT/cutoff boundaries explicitly.
- Fix interruption semantics: the docstring promises a best model on interruption,
  but callbacks currently store parameters only, and final persistence requires a
  returned SciPy result. Save/reconstruct callback-best results with interrupted status.

## 5. Calibration identity and persistence

Give every fit an immutable `run_id` (UTC timestamp plus UUID fragment), optional
human label, and structured metadata. A suggested display name is
`56610000-D-PlainNSE-ap05-seed42-<run_id>`; the ID remains authoritative, not the filename.
Do not encode every setting into a directory name or use test NSE as a run identifier.

```text
stations/<code>/
  calibration/<freq>/runs/<run_id>/
    manifest.json          # identity, provenance, effective config, status, timings
    summary.json           # fitted params, metrics, split, counts, stop reason
    history.parquet        # generation history + explicit final/refinement record
    modeled.parquet        # all simulated discharge dates, nullable observations
    inputs/rain.parquet    # original forcing dates, continuous through simulation
    inputs/discharge.parquet
    inputs/metadata.json   # input revision, basin/network/area provenance
  calibration/<freq>/latest.json
  calibration/<freq>/selected.json
```

Snapshot these small basin time series first; a later content-addressed input store
can deduplicate them. Preserve watershed provenance/hash and, for new forecasting
runs, access to the exact watershed geometry. A revision UUID alone cannot reproduce
inputs overwritten by refresh. Record hashes, source product and time convention,
code revision plus dirty-source fingerprint, package versions, parameter bounds,
objective configuration (including custom-objective settings), antecedent/spin-up
settings, split dates, seed/RNG policy, and solver configuration.

Distinguish three objects:

- **Calibration run:** fixed parameters, provenance, simulations, and scores.
- **Optimizer recovery snapshot:** callback-best parameters or, later, full population,
  energies and RNG state. A restart from parameters is not exact solver continuation.
- **Forecast initial state:** groundwater storage, antecedent rain, state timestamp,
  and pending delayed flow for ACT. It belongs to a run and an issue-time data history.

Write to a staging location and commit a complete manifest atomically; update
`latest` only after success. Keep `selected` explicit rather than automatically
choosing the highest test score. Failed/interrupted attempts remain identifiable and
cannot replace the selected complete run. Validate IDs as path components.

Compatibility: discover today's three-file directories as labeled legacy runs;
preserve them before the first new-style write. Never infer a missing historical
creation time, git revision, or input snapshot. Legacy evaluation can use stored
paired results even when current preparation is newer, clearly marking limitations;
replay/rainfall attachment requires a matching revision. New snapshots remain
historically evaluable after input refresh. Existing no-ID workflow calls can resolve
`latest`; new notebooks and forecast calls should select and display an explicit ID.
Quality maps must use a stated run-selection policy and validate complete artifacts.

## 6. Proposed 04-evaluation notebook

### Package design and notebook flow

Add `CalibrationStore` in `src/cn3s/artifacts.py` and `CalibrationEvaluation` in
`src/cn3s/evaluation.py`, re-exported from `cn3s`. Keep workflow methods as compatible
delegating entry points. API names are provisional:

```python
store = CalibrationStore(data_root)
store.list_runs(station_code, frequency)
evaluation = CalibrationEvaluation.from_run(
    data_root, station_code=station_code, frequency=frequency, run_id=run_id,
)
evaluation.settings()
evaluation.coverage()
evaluation.metrics(period="test")
evaluation.hydrograph(period="all", rainfall=True)
evaluation.scatter(period="test")
evaluation.residuals(period="test")
evaluation.flow_duration(period="test")
evaluation.seasonality(period="test")
evaluation.optimization_history()
```

One editable notebook configuration cell specifies root, station, frequency, run,
evaluation period, optional plot dates, and optional comparison run. Use the existing
autoreload convention. Other code cells import, instantiate classes, call methods,
and display results. Selection, file reads, validation, resampling, metrics and plot
setup belong in classes. No calibration calls, loops or external clients. The saved
run determines frequency, parameters, ACT and split; reject conflicting configuration.

Load persisted simulation first; reconstruction is an explicit optional operation.
Report the original saved metrics separately from any newly recomputed metrics.
Plot zoom must not silently redefine the headline evaluation window. A comparison
shows run IDs, differences in inputs/settings, and shared evaluated dates.

### Figures and metrics

| Output | Required behavior |
| --- | --- |
| Run/coverage tables | Show ID, label, status/convergence, input revision, parameters, actual train/test dates, excluded/missing counts and observation coverage. |
| Hydrograph + rain | Observed and simulated m³/s on the main axis; mm/day or mm/month rainfall bars downward from an inverted upper secondary axis; visible split; readable combined legend. Use an upper band if overlap obscures flow. |
| Scatter | Observed discharge on x, simulated discharge on y, 1:1 line, matched units/limits; distinguish train and test. Optional log view excludes/labels nonpositive values. |
| Residuals | Simulated minus observed against date and observed flow; zero reference; explicit sign convention. |
| Flow-duration curve | Independently sorted observed/simulated flows from the same paired dates, with defined exceedance convention; show low-flow differences. |
| Seasonality | Monthly climatology and month/year error summaries with counts; daily input aggregation is explicit. |
| Optimization history | Training objective vs generation and final polished result as distinct records; do not invent missing per-generation test metrics or auto-rerun history. |

Rain must retain its original forcing date. Today `modeled.parquet.prec` inherits
the ACT-shifted discharge index, so it is not safe to plot that column as same-day
rain without reversing the lag. Prefer the run's unshifted full rainfall snapshot;
show discharge on response dates. Preserve unpaired modeled dates and missing-observation
gaps, rather than drawing apparently continuous observations through dropped dates.

Report NSE, original KGE with correlation/variability/bias components, RMSE and MAE
(m³/s), signed bias and volume bias, and sample counts by train/test period. Define
volume bias as `100 * sum((Qsim-Qobs)*dt) / sum(Qobs*dt)` so positive means overprediction;
use actual interval seconds. Label this convention to avoid ambiguity with PBIAS
definitions of the opposite sign. Add training-fitted seasonal climatology and,
for daily records, one-step persistence using only the prior available observation.
Do not call one-step persistence a multi-day forecast baseline.

Use finite paired values and one consistent mask per comparison. Return undefined
metrics with reasons for insufficient pairs, constant observed flow, zero total flow,
or undefined correlation/KGE components; do not silently coerce these to successful
scores. Current `sklearn.r2_score` defaults can mask constant-series degeneracy.
NSE is not squared Pearson correlation; label scatter statistics accordingly.
NSE and KGE do not share an interchangeable interpretation or zero threshold; see
[Knoben et al. (2019)](https://hess.copernicus.org/articles/23/4323/2019/).

### Daily versus monthly comparison

Keep independently calibrated D and M parameters. Compare on common held-out calendar
windows, reporting native-frequency metrics separately. Additionally aggregate daily
Q to mean monthly Q and rainfall to monthly totals, using a declared completeness
policy, then compare against monthly CN3S and the same observed monthly series.
Propose complete months for the strict benchmark and show excluded months; any relaxed
coverage threshold must be configured and reported. Do not sum discharge values or
compare rainfall totals against mean-flow units. Monthly averaging suppresses timing
errors; a higher monthly NSE is not evidence of better daily flood prediction.

## 7. Scientific and data improvements before claiming usefulness

### What the supplied literature supports

- [Sobral calibration study, 2026](/data/CN3S/docs/DOC-20260702-WA0020.pdf),
  *Calibração do modelo chuva-vazão CN3S para a região de Sobral*, PDF pp. 4–5,
  8–11 and 15–16: monthly CN3S, six parameters, three antecedent months, PSO,
  and a reported best NSE around 0.895. A calibration result does not independently
  validate rainfall forecasts. The text on PDF p. 11 describes a V cap of 3;
  current code caps it at 100 while its docstring says 5. Table 1 bounds also differ
  substantially from the optimizer (e.g. CN maximum 30 versus 130).
- [Ceará regionalization study](/data/CN3S/docs/DOC-20260703-WA0032.pdf),
  *Regionalização de parâmetros do modelo hidrológico CN3S no estado do Ceará*,
  pp. 2–4: 25 stations, at least 10 years, 2/3 calibration and 1/3 validation,
  with 12 validation scores above 0.70. Regional regression is described as a next
  step. This motivates transfer experiments but does not supply a validated general
  parameter-transfer rule. Its bounds/fixed alpha differ from the Sobral study too.
- [Gonçalves, Xavier and Rotunno Filho](</data/CN3S/docs/Rotunno Filho_otimizacao funcao objetivo.pdf>),
  *Modelagem hidrológica via SMAP e TOPMODEL na bacia de Pedro do Rio — Rio Piabanha*,
  pp. 9–14 and 18: separate calibration/validation, multiple error criteria and
  residual diagnostics. This supports purpose-specific evaluation rather than one score.

The supplied references describe CN3S through SCS Curve Number relations and cite
Taborga/Freitas. They do not by themselves establish a direct derivation from SMAP;
describe that lineage as unverified until the original source is obtained. The
SMAP study includes evapotranspiration and a different state structure. Shared runoff
concepts do not make their parameters interchangeable.

Before altering equations, create a source-to-code comparison with worked examples:
antecedent formula and cap, CN adjustment, parameter ranges, recharge/recession,
initial storage, runoff threshold, and depth-to-flow conversion. The Sobral paper's
printed baseflow equation appears inconsistent with its K1/K2 prose; confirm against
the original reference and figure before treating it as ground truth. Preserve a
versioned legacy formulation; any scientific change requires new calibration and
explicit comparisons. No literature bounds should be copied indiscriminately to D.

Additional priorities:

1. Separate antecedent-memory length from state spin-up. Current first `warmup_steps`
   values establish rainfall history but do not advance groundwater storage. A new
   spin-up policy needs independent validation and changes run identity.
2. Establish daily validity independently. Time step changes recession, rainfall
   sensitivity and memory; daily parameters are not copied from monthly ones. Large
   basins may require routing and regulation information beyond one uniform ACT lag.
3. Monthly calendar convention: audit fixed-30-day Q conversion against calendar-month
   mean observations. A calendar-aware variant must be versioned and recalibrated.
   Forecast precipitation totals should still use the actual product interval length.
4. Validate finite/nonnegative rainfall and valid discharge, duplicate dates, source
   consistency, day boundaries, basin area and grid coverage. Current rainfall checks
   do not reject every invalid numeric case. Preserve source QC fields when feasible.
5. Monthly discharge currently accepts any available number of daily observations.
   The stored full discharge histories include partial months (9 for 56610000, 1 for
   56696000, 4 each for 56850000 and 66010000); these counts include dates outside fit
   windows, not necessarily problematic test months. Add period-specific coverage checks.
6. Validate monthly MERGE totals against aggregated daily MERGE on a sample period;
   quantify differences before assuming the products are equivalent. Evaluate polygon
   intersection/grid-cell area weighting: the present adapter uses a simple cell mean.
7. Complete the link between basin overview and calibration quality: telemetric
   station metadata lacks `RIO`, while the quality-map path filters by it. Use basin
   membership or an explicit station selection contract instead of assuming that field.
8. Reconcile README examples/stale monthly-ACT warning with current code. Record the
   MERGE downloader commit instead of relying only on a mutable branch; reconcile
   Python >=3.10 metadata with the >=3.11 development convention in its own change.

### Evidence needed to demonstrate value

Use three separate claims and experiments:

- **Historical simulation:** blocked/rolling temporal validation over wet and dry
  years, simple baselines, multiple seeds, and an independently calibrated comparison
  model such as SMAP where equivalent forcing (including ET) is available.
- **Forecasting:** archived issue-time rainfall forecasts, initial states using only
  observations available at issue time, and skill against persistence/climatology by
  lead time. Observed-rainfall simulation is a diagnostic reference, not an operational forecast.
- **Ungauged prediction:** withheld-station tests with target discharge excluded from
  donor choice, parameter training and model selection.

Choose hyperparameters on training/validation blocks; reserve a final untouched test
period. Repeatedly selecting runs by the current test NSE turns that period into
validation and requires a new final test. Use paired comparisons and hydrological
year/event block resampling for uncertainty, not independent-day confidence claims.
Show poor stations, seed variability, parameter-bound hits and data exclusions.

Proposed decision gate: demonstrated improvement over relevant baselines on independent
data, with acceptable bias/timing for a named use case and reasonable runtime. Agree
numeric tolerances and target coverage before running the benchmark. No universal
NSE cutoff or favorable fit alone proves operational usefulness.

## 8. Forecasts: connect the model in two stages

### Shared state and forcing contract

First implement a stateful simulation interface independent of provider. A forecast
needs fixed calibration parameters, state at the issue boundary, antecedent rainfall,
and any pending ACT-delayed discharge. Initial `r0` is not the current groundwater state.
Calling today's `run()` on future rain alone resets state and discards initial forecast
steps as warm-up. Initially, replay continuous observed history plus each forecast
member and slice future outputs; later validate a serialized-state continuation API
against that replay. Do not reconstruct state from observation-filtered modeled tables.

Represent forcing with source/system/version, initialization and availability time,
valid interval start/end, lead, member, rainfall depth (mm), basin/grid aggregation,
raw units, revision and QC. Store raw issue-specific files and normalized series.
Forecast runs reference a calibration run and state snapshot and have independent IDs.
No retrospective forecast may use observations or revised products unavailable then;
when latency archives are missing, label the experiment as idealized.

### Daily: WRF through the installed MERGE downloader

The installed `mergedownloader/inpeparser.py` contains `HOURLY_WRF` and `DAILY_WRF`.
Its daily processor requests eight noon values from one 00 UTC initialization and
differences successive cumulative fields to yield up to seven intervals. It retains
the earlier timestamp after a forward difference. The hourly class description says
hourly totals while the daily processor assumes cumulative rain: inspect actual GRIB
units, step ranges and accumulation semantics before relying on either description.
This is a code finding, not verification of current server availability or horizon.

1. Request/cache by initialization and valid time; confirm provider horizon and archive
   retention. Existing local downloads yielded no WRF filenames in the review.
2. Convert cumulative rain to interval totals only when metadata requires it; handle
   accumulation resets and missing endpoints. Reject unexplained negative increments.
3. Match MERGE training day boundaries, including any noon-to-noon convention, with
   Hydro discharge dates. Do not normalize timestamps and silently lose interval meaning.
4. Aggregate over the exact calibrated basin; maintain complete continuous forcing
   from the last observed interval to the forecast end. Explicitly handle observation
   latency with available analysis/forecast data and label that bridge.
5. Run the daily calibration from the issue-time state and evaluate each lead with
   frozen-origin persistence, climatology and observed-rainfall reference simulations.
   Estimate any bias correction from earlier paired issues by lead/season.

Treat one WRF run as deterministic unless true members are supplied. Multiple
initializations are not automatically a calibrated probabilistic ensemble. Start an
issue archive now if historical forecasts cannot be recovered; until then, hindcast
skill remains unproven.

### Monthly: Copernicus C3S seasonal precipitation

The existing notebook is a useful experiment but has fixed 30-day rate conversion,
hard-coded August 2026 requests, model/member averaging before hydrological simulation,
manual reassignment of forecast steps from today's calendar, inconsistent file paths,
and cells treating a model dictionary as a data object. Two inspected cached files
contained `tprate` in m/s and lead durations but no explicit initialization coordinate.
They cannot safely determine valid months from the lead dimension alone.

The [C3S dataset documentation](https://cds.climate.copernicus.eu/datasets/seasonal-monthly-single-levels?tab=overview)
defines total precipitation here as a rate in m/s and provides both forecasts and
hindcasts. Its seasonal products describe uncertain monthly outlooks, motivating
member-preserving hydrological forecasts.

1. Preserve request metadata, initialization, system, member and valid calendar month.
   Resolve interval bounds from product metadata, not `Timestamp.now()` or filenames alone.
2. Convert rates with `P_mm = rate_m_per_s * 1000 * interval_seconds`, using the actual
   valid month length. Already accumulated depth products require a different conversion.
3. Extract basin means consistently for forecast and hindcast. For small basins relative
   to coarse grids, report representativeness limitations rather than inventing detail.
4. Fit basin/model/initialization-month/lead-specific bias adjustment on matched earlier
   hindcasts and observations, excluding evaluation years. Compare raw and corrected
   forecasts. The notebook's additive adjustment can create negative rain; use a
   validated nonnegative method and record any clipping. A hindcast climate mean alone
   is insufficient for full distributional calibration and forecast verification.
5. Run each available member through monthly CN3S from the same supported initial
   state, then calculate discharge distributions. Simulating mean rainfall is not
   generally the mean of member discharge in this nonlinear model. If only model
   ensemble means are available, label those as scenarios, not full uncertainty.
6. Include every intervening month. Requests for leads 2–4 still require forcing/state
   evolution through lead 1. For a current partially observed month, combine observed
   and forecast portions consistently or issue from the last complete month with
   explicitly forecast intermediate months.
7. Verify discharge means/volumes, CRPS or CRPSS, reliability, interval coverage and
   drought/high-flow probabilities by lead and season against climatology/ESP.

Use independently calibrated monthly parameters. Do not divide a monthly forecast
by 30 and call it a daily forecast. If daily paths are later needed, use validated
stochastic disaggregation/analog ensembles preserving monthly totals. Introduce WRF
and seasonal products separately before attempting a seamless blended horizon.

## 9. Other discharge points and regionalization

At an existing gauged station, the first extension is gap filling or simulation
beyond its observed record, clearly labeled modeled data. For an ungauged outlet,
use Otto-based delineation and local rainfall, then estimate parameters from donors
chosen by hydroclimate, area, soils, land cover, slope and regulation similarity.
Start with donor transfer and simple specific-discharge/area-ratio baselines; assess
regression only with enough independent calibration basins.

Validate with leave-one-station-out or spatially blocked experiments. Nested basins
can share rainfall and discharge information, so holding out neighboring upstream/
downstream stations together may be necessary. Quantify donor uncertainty and flag
targets outside the training domain. Transfer storage initialization via a local
spin-up, not the donor's arbitrary fitted initial state.

Do not create a credible new point merely by changing area in one calibrated model.
Area scaling assumes unchanged runoff depth and response, which must be tested.
For network discharge, select either independent outlet simulations or a routed
incremental-catchment model. Summing complete nested upstream-basin simulations
double-counts water. Routing, reservoirs, abstractions and travel times are separate
requirements; the present fixed ACT shift is not a river-routing model.

## 10. Implementation order and acceptance criteria

| Phase | Work and affected files | Acceptance |
| --- | --- | --- |
| A: Preserve and identify runs | New `src/cn3s/artifacts.py`; adapt `workflow.py`, exports, focused artifact tests. Add legacy adapter, manifests, snapshots, atomic writes and list/select APIs. | Two same-station/frequency calibrations coexist; selected run is stable; failed writes do not replace it; legacy files remain intact; old snapshotted runs load after input refresh. |
| B: Offline evaluation | New `evaluation.py`; extend `metrics.py`; add `nbs/dev/04-evaluation.ipynb`, exports and notebook guide. Implement the figures/tables above. | A fresh kernel evaluates saved D and M runs without any optimizer/source client; metrics reproduce saved ordinary NSE within tolerance; IDs/coverage/units/split are visible; rain remains on forcing dates; corrupt and incompatible artifacts fail clearly. |
| C: Observable calibration | Update `optim.py` and `workflow.py`; expose phases and refinement policy, reuse final simulation, preserve callback-best on interruption. Restore one configured calibration call in notebook 03 after review. | Deterministic small runs retain numerical results; final output is final-best, not last-candidate; timings/counts/termination are saved; interruption leaves an accurately labeled recoverable result. |
| D: Scientific/data audit and numerical speed | Equation reference fixtures; data QC/coverage in preparation; explicit spin-up/calendar/formulation decisions; then optimize `model.py` recurrence. | Worked-example and legacy-parity tests pass; documented formulation version; D/M and ACT behavior verified; long-series runtime/memory measured; changed science triggers new runs rather than relabeling old scores. |
| E: Benchmark and state continuation | New benchmark/state APIs and thin entry point as needed. Fixed temporal splits, baselines, multiple seeds, comparison model where feasible. | Reproducible station scorecard, untouched test policy, comparison uncertainty, and exact replay-versus-continuation agreement including positive ACT. |
| F: Daily forecast pilot | Separate provider adapter and forecast orchestration module, future notebook 05. Archive issued WRF forcing and normalize intervals. | Unit/day-boundary tests and rolling issue-time replay pass; gaps/latency explicit; per-lead skill against baselines reported; no unsupported forecast-skill claim. |
| G: Seasonal pilot | C3S adapter, member-preserving bias calibration, future notebook 06. | Calendar/leap-year/lead/member tests; correction excludes verification years; state bridge complete; deterministic/probabilistic scores by lead. |
| H: Spatial transfer pilot | Regionalization module using existing hydrography APIs; future notebook 07. | Spatial holdouts, donor baselines, uncertainty, domain checks and no nested-basin double-counting. |

A and B are the recommended first delivery. C can follow closely; gather phase
measurements before larger performance work. Forecast provider exploration may proceed
after the state contract is designed, but forecast usefulness is assessed only after
independent validation. Each implementation phase should update this plan and produce
an outcome in its iteration; larger later phases may receive their own recorded plans.

Focused validation cases: missing/constant/zero flows; empty splits; duplicates and
nonfinite values; positive ACT across train/test and forecast boundaries; missing
observations without missing simulation state; incomplete months and leap years;
legacy/stale/corrupt artifacts; interrupted or colliding writes; final polish changes;
multi-member identity; cumulative-precipitation resets and issue-time leakage.
Validate plots visually with one saved D and one M run, including positive-ACT fixtures.
Notebook cells must comply with the thin-entry-point rule.

After implementation, run focused pytest, Ruff without fixes during review, strict
mypy for `src/cn3s`, and fresh-kernel evaluation execution. Do not use `make check`
for read-only review because it modifies files. No live data refresh is needed to
validate the first evaluation delivery.

## 11. Open decisions, risks, and review verification

Decisions to resolve before dependent implementation:

- Confirm the first delivery: A/B only, or A/B plus calibration phase reporting C.
- Choose the operational priority: daily timing/peaks, seasonal volumes/low flows,
  or ungauged historical series. This determines acceptance thresholds and pilot sites.
- Agree independent evaluation dates and monthly coverage policy; current test periods
  already inspected during experimentation should not be treated as permanently untouched.
- Choose the authoritative CN3S equation reference and policy for experimental daily
  formulation, bounds, spin-up, V cap and month duration.
- Confirm WRF accumulation/day-boundary semantics and accessible issue archives; select
  C3S systems/member products with sufficient overlapping hindcasts.
- Decide whether early optimizer recovery means callback-best restart or exact DE
  continuation. Proposed first scope is callback-best recovery with honest labeling.

Risks: data quality and regulation can dominate model error; short validation periods
are unstable; seasonality can inflate apparent skill; parameter sets can be nonunique;
large-basin lumping and coarse forecast grids limit transfer; source refreshes and
mutable dependencies impede reproducibility; full forecasts require state beyond
today's saved paired discharge; literature variants must not be mixed silently.

Review verification completed on 2026-09-30:

- Inspected current package, notebook code and calibration output, relevant iteration
  records, all three supplied PDFs by text extraction, installed SciPy/downloader
  implementation, seven saved summaries and their paired simulations, station
  discharge coverage, and two cached seasonal forecast files.
- Computed the explicitly defined exploratory seasonal baselines above; profiled one
  saved daily simulation and ran the small in-memory polish/no-polish comparison.
- `python -m pytest -q -p no:cacheprovider tests`: **20 passed in 12.56 seconds**.
- Consulted the official SciPy/C3S documentation and the published KGE benchmark paper
  linked beside their claims. Original 1987 equations and live WRF availability were
  not verified. No live Hydro authentication or MERGE/C3S downloads were performed.
- No implementation, notebook, runtime configuration, or persisted station artifact
  was edited by this review. The worktree already contained extensive user changes;
  they were preserved. Only this iteration plan was added. PDF extraction tooling
  and extracted text were placed under `/tmp`, outside the project.
