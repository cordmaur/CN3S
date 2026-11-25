# CN3S web proof of concept

Session: 2026-11-24, 17:25:14 America/Sao_Paulo.
Status: implementation authorized and completed locally; deployment verification limits recorded below.
Update this file in place throughout this iteration.

## Objective and recommended scope

Make the notebook workflow available through the existing SHC Flask interface,
preserving its scientific calculations and making inputs, assumptions, and outputs
inspectable. Start with one prepared station and one verified monthly forecast
cycle, then expose preparation and calibration controls.

The first demonstrable milestone is: sign in → select Marabá (29050000) → inspect
prepared inputs and select a monthly calibration → select forecast initialization
and reference date → run rainfall preparation and CN3S → inspect rainfall and
discharge charts → download the numerical results and run settings.

The complete proposed proof of concept additionally supports preparing a station,
updating monthly inputs, and running a bounded calibration from the browser.
CDS acquisition remains notebook 03's responsibility for this iteration; the web
interface checks and consumes its files. This is an explicit scope boundary:
the PoC integrates all five notebooks' products, but does not yet execute every
notebook operation through a browser.

Use existing Flask/Jinja, JavaScript, Python APIs, file formats, authentication,
and background-thread conventions. No new frontend framework, database, queue
service, workflow engine, or generalized processing classes are proposed.

## Repository and data findings

Findings refer to the current working tree, including existing uncommitted changes.

| Source | Existing capability | Web treatment |
| --- | --- | --- |
| `01-Prepare_Station.ipynb` | `Station.prepare_station()` saves identity, both drainage areas, and upstream geometry | Load prepared stations first; add explicit preparation later |
| `02-Optimization.ipynb` | Download rainfall/discharge, load saved inputs, optimize and save parameters/history | Separate input preparation from offline calibration; enforce monthly frequency |
| `03-CDS-Forecast_Download.ipynb` | Downloads nine centres and prec/anomaly/hindcast products | Display available cycles and missing required files; acquisition stays outside the browser |
| `04-Inference.ipynb` | Original manual rainfall correction, model scenarios, and comparison figures | Scientific reference; do not duplicate its cells in route handlers |
| `05-Inference_Organized.ipynb` | `Inference` orchestrates `RainfallForecast`, CN3S, and discharge charts | Primary implementation API |

The existing web preparation is an application shell: `web/app.py` registers
login and Permanência, and `shc_home.html` has a disabled CN3S card. There is no
CN3S route in the inspected checkout. Reuse the established page structure,
Portuguese labels, CSRF checks, delegated SQL login, operation polling, and chart
delivery patterns. Keep Permanência's station catalog separate: it scans
Exceedance products, not CN3S prepared-station folders.

Concrete integration issues:

1. Notebook 02 currently sets `FREQ = "D"`, despite monthly-oriented text.
   Daily preparation now exists in `Station`; monthly-only inference does not
   accept its calibrations. The PoC uses `"M"` throughout.
2. Notebook 02 saves to `<station>/<Monthly|Daily>/optim/`, whereas `Inference`
   currently reads `<station>/optim/`. New monthly calibrations need one explicit
   path convention, with deliberate handling of existing files.
3. Notebook 02 describes ACT as a day shift even for monthly runs. Current model
   code uses calendar months for `freq="M"`; the plan follows executable code.
4. Notebook 05's introductory September description differs from its configured
   October initialization. Notebook 03 is configured for November. Show
   initialization, reference date, rainfall months, and ACT-shifted discharge
   months separately; do not inherit conflicting notebook text as defaults.
5. `Inference.load_discharge()` creates the notebook `SqlConnector` internally.
   Web calls must use `UserSqlConnector` with the initiating user's token.
6. `plot_raw_rainfall()` returns Matplotlib; the other principal inference charts
   return Plotly. Existing Plotly basic assets may not support box traces: verify
   and supply a compatible local bundle if needed.
7. The container currently mounts only `/data/CN3S/Exceedance`. Its web extra
   lacks several inference/calibration imports, and Docker does not copy
   `src/hydrography`. Development imports alone cannot establish deployability.

Read-only inspection of `/data/CN3S/stations/29050000` found:

- Prepared metadata and basin geometry, plus monthly rain and discharge files.
- Monthly rainfall: January 2000–September 2026, 321 rows, no missing values.
  Discharge has the same extent and 20 missing values; missing discharge is not
  a reason to invent or interpolate observations.
- `optim/PlainNSE_alfa_livre.json`: monthly calibration, ACT = 1 calendar month,
  warmup = 3 steps. Recorded train NSE ≈ 0.916, test NSE ≈ 0.020, train ratio 0.99.
  This is suitable for demonstrating integration, not evidence of forecast skill.
- `optim/ExtremeFlowBlend_alfa_livre.json`: daily calibration, ACT = 19 days.
  Its folder/name alone cannot determine compatibility; exclude it from monthly
  choices using artifact metadata.
- UKMO forecast/hindcast filenames exist for September, October, and November
  2026. Completeness of all nine centres and actual lead coordinates still needs
  verification; filename presence alone does not establish a usable cycle.

Recommended first example: station 29050000, existing monthly PlainNSE artifact,
October 2026 initialization, `as_of="2026-10-13"`, and all available remaining
leads. Verify these files before fixing the demonstration configuration. A
November reference date requires extending saved rainfall through October.

## User journey and screen contents

Add `/shc/cn3s` to the home card and shared navigation. Use one module page with
four sections, each showing whether its prerequisites are ready.

### 1. Estação e dados

- Select from configured CN3S station folders; show station name/code, cobacia,
  inventory drainage area and hydrographic drainage area, both in km².
- Show the basin and outlet when coordinates are available; a simple rendered
  basin image is sufficient for the PoC. Do not add a mapping platform.
- Show monthly rainfall/discharge date ranges, missing values, and warmup needs.
  Provide a small table preview and a download of the prepared monthly inputs.
- Initially consume existing files. In the preparation milestone, add station
  code and date-window inputs with separate actions for preparing the basin,
  saving discharge, and saving rainfall. Explain the exact files being replaced.
  Reuse requires no automatic downloads or re-preparation.

### 2. Calibração

- List compatible saved calibrations, displaying frequency, objective, area,
  ACT and units, warmup, training split, solver outcome, and train/test metrics.
- Default to an existing monthly artifact. Display its quality limitations and
  distinguish objective values from NSE.
- Later expose a compact calibration form: period, chronological training ratio,
  objective (`PlainNSE` or `ExtremeFlowBlend`), seed, iteration budget, and an
  expandable parameter/bounds table. Preserve existing optimizer semantics.
- Default to one CPU worker and a small explicit demonstration budget; record
  iteration-limit termination as such, never as successful convergence.
- Show observed/simulated discharge and training/validation boundaries. Save a
  new named monthly artifact; do not silently replace the selected calibration.

### 3. Chuva prevista

- Select initialization year/month from files that actually exist, an explicit
  reference date, and a valid remaining horizon. Display the fixed nine-centre
  model set for the first implementation; no model-selection UI is necessary.
- Show required prec/hindcast availability per centre. Inference does not read
  notebook 03's anomaly files, so their absence must not block it.
- Prepare rainfall and show observed/climatological rain, raw forecast,
  percentage anomalies, corrected forecast median, and model spread.
- Mark current-month observations as potentially partial/cached; disclose the
  retrieval time and reference date. Do not describe `as_of` as a historical
  data snapshot or claim the example is a retrospective skill assessment.

### 4. Vazão prevista e resultados

- Run two scenarios: climatological rain and the median corrected forecast rain.
- Show the monthly discharge comparison by default, with the daily comparison
  as a secondary view. Use the existing historical summaries and valid-day counts.
- Display numerical rainfall and discharge tables, with units and dates.
- Keep observed anchoring off initially. If exposed later, label it as a
  constant visual adjustment; raw CN3S outputs and exports remain unchanged.
- Download CSV results and a JSON settings/provenance record. Include calibration
  identity, frequency, dates, models, input coverage, execution time, source-file
  fingerprints, code revision and dirty-tree indication. Do not export credentials.

Changing a station, calibration, initialization, reference date, or horizon
invalidates dependent results. Disable run buttons with an actionable explanation
when prerequisites are missing. Retain a successful numerical simulation if the
optional online discharge comparison fails; report that chart as unavailable.

## Scientific contract

1. Frequency is monthly, with month-start input labels, rainfall in mm/month,
   discharge in m³/s, and area in km². Read frequency/ACT units from calibration
   metadata before constructing inference; reject daily or ambiguous artifacts.
2. Use the calibrated area and expose differences from current station metadata.
   New calibrations use the inventory area, matching notebook 02, unless an
   explicit scientific decision changes it. No silent area substitution.
3. Preserve the complete saved rainfall prefix and calibrated initial storage
   for both scenarios. Require consecutive finite monthly rainfall through the
   month before forecast start. Warmup comes from parameters, not a fixed UI value.
4. Keep missing discharge as missing; report available pairs and their dates.
   Respect chronological training/validation and the existing objective function.
5. Preserve the basin correction order: calculate forecast/hindcast grid-cell
   ratios, average those ratios over the basin, multiply by observed basin
   climatology, then take the median across model rainfall scenarios. Do not
   replace it with a ratio of basin means or a median of simulated discharge.
6. Notebook 03 stores raw forecasts as 30-day-equivalent totals. Preserve this
   convention and label raw charts accordingly; its common factor cancels in
   forecast/hindcast ratios. Do not silently change unit conversion in the PoC.
7. Keep the existing basin cell-selection and interpolation rules, including
   the small-basin intersecting-cell fallback. Record its metadata.
8. CN3S applies monthly ACT shifts once. Moving chart markers toward midmonth
   must not alter numerical result timestamps or add a second ACT shift.
9. Historical P10–P90 bands describe historical variability; rainfall-model
   spread is not calibrated discharge uncertainty. Do not label either as a
   forecast confidence interval.
10. Monthly statistics use historical monthly means; daily comparison retains
    its different pooled-daily references. Clearly identify both conventions.
    For a pinned reference date, trim daily observations before computing either
    comparison; the existing daily plotting path does not do that itself.

## Implementation sequence and completion gates

### Step 1 — Establish a reproducible local baseline

Inspect the nine-centre files and their lead coordinates; verify October input
continuity and calibration metadata. Run notebook 05's API sequence outside the
UI using the chosen configuration, without modifying original station files.
Record numerical rainfall/scenario tables and runtime/memory observations for
comparison during implementation. Capture the actual forcing and observation
values used by the check: live sources can change even with a pinned date.

Gate: one documented configuration executes successfully, with finite results,
known forecast/discharge dates, and visible calibration limitations. No claim of
scientific validation is based only on a successful run.

### Step 2 — Add module shell and readiness inspection

Create a small `web/cn3s.py` blueprint and a CN3S template/JavaScript file. Register
the blueprint, enable the home card, and reuse shared styling. Add server-side
data-root settings and scan only the configured station/calibration directories.
Provide station, calibration, cycle, and readiness metadata without expensive
downloads. Return JSON session-expiry responses for the new API endpoints, as
the existing special handling currently targets Permanência only.

Gate: an authenticated user can identify exactly what is ready and what is
missing; incompatible calibrations cannot be selected.

### Step 3 — Execute and display the existing inference workflow

Run `Inference.prepare_data()` and `run_model()` in a background operation using
one fresh inference instance per run. Retrieve daily observations using
`UserSqlConnector`, load a temporary `Station` with that connector, and assign
the resulting public `discharge_daily` series before plotting. This avoids a
new abstraction and avoids changing notebook SQL authentication.

Render Plotly figures as JSON using Plotly's supported serializer. Deliver raw
rainfall as a PNG using the existing render-lock convention and close the
Matplotlib figure. Verify that the local Plotly build supports the forecast box
traces; add a compatible vendored build and license only if needed.

Gate: the browser produces the same numeric outputs as the captured baseline,
displays both forecast scenarios and correct date/unit labels, and can still
show/download model results when SQL comparison data is unavailable.

### Step 4 — Add result downloads and review the first demonstration

Generate numerical CSVs and a small JSON run record. Keep finished results in
the existing bounded/expiring operation cache for the PoC, with a documented
lifetime. Use downloads for durable user records; no general run archive is
needed. Allow users to inspect and export prepared forcing, including the
historical prefix, so the model calculation can be reproduced after live data
changes. Capture observed series/statistics used in comparison exports too.

Gate: complete the first demonstration from sign-in to downloadable results,
without executing a notebook during the demonstration. Notebook 03 files and
the prepared station are explicit prerequisites, not hidden web capabilities.

### Step 5 — Expose station and monthly-input preparation

Add direct calls to `Station.prepare_station`, `download_discharge`, and
`download_rain`, using configured hydrography paths and the web user's SQL
connector. Reuse `Hydrography` without creating another basin-preparation layer.
Keep long rainfall acquisition separate from calibration; saved-input calibration
must not trigger SQL or download activity.

Run the PoC against a dedicated copy of the station data. Serialize conflicting
writes and inference reads for the same station; block a second operation with
a clear busy message. Complete downloads/calculations before replacing saved
artifacts where practical, and invalidate dependent browser results after writes.

Gate: a station can be prepared and monthly inputs refreshed from the browser;
saved files load through the unchanged notebook APIs, and a missing historical
rainfall month prevents inference rather than being silently filled.

### Step 6 — Expose bounded monthly calibration

Use `CN3SOptimizer` directly with monthly saved inputs. Save new outputs to
`<station>/Monthly/optim/`. Make a narrow change to inference calibration
resolution so this canonical directory is supported while retaining explicitly
identified legacy `<station>/optim/` choices. Avoid ambiguous filename fallback:
the catalog must retain which actual file the user selected. Check frequency in
both locations; do not move or rewrite existing artifacts as part of discovery.

Use the optimizer's built-in history and saved metadata. Initially report the
phase and elapsed time; do not invent percent completion or expose thread-unsafe
live history. No cancellation/resume promise is needed for a bounded first run.
Measure responsiveness before offering longer calibration budgets.

Gate: one browser calibration saves a reloadable monthly artifact, its reported
training/test metrics match the artifact, and a subsequent inference can select
it. The existing saved calibration remains available for the reference demo.

### Step 7 — Verify the deployed PoC

Extend the existing web dependencies with the libraries already used by the
workflow (inspect exact imports, including SciPy, Plotly, xarray, rioxarray,
NetCDF backend, and the installed MERGE downloader distribution). Establish a
reproducible install source/version for the downloader; do not copy a notebook
environment's ad hoc installation recipe. Earthkit/CDS credentials are not
required in this container while CDS acquisition stays external.

Copy the existing hydrography package if preparation is enabled. Configure the
CN3S station, forecast, downloads, and hydrography mounts and permissions; keep
forecast/hydrography sources read-only and use a writable PoC station/cache root.
Update `web/README.md` and compose settings; extend Makefile settings only where
the actual deployment path requires it. Verify both the devcontainer and the
standalone image, then smoke-check the `/shc` prefix through IIS.

Gate: container inference and one bounded calibration work with documented
mounts; current Permanência functionality and navigation still work.

## Minimal execution design

Proposed routes (names may follow existing conventions during implementation):

| Method/path | Purpose |
| --- | --- |
| `GET /shc/cn3s` | Module page |
| `GET /shc/cn3s/stations/<code>` | Prepared inputs, calibrations, readiness |
| `GET /shc/cn3s/cycles` | Available initialization cycles and required files |
| `POST /shc/cn3s/stations/<code>/prepare` | Prepare station context, later milestone |
| `POST /shc/cn3s/stations/<code>/inputs` | Prepare selected monthly inputs |
| `POST /shc/cn3s/stations/<code>/calibrate` | Start bounded monthly calibration |
| `POST /shc/cn3s/stations/<code>/forecast` | Prepare rainfall and run inference |
| `GET /shc/cn3s/operations/<id>` | Current phase, result, or actionable error |
| `GET /shc/cn3s/operations/<id>/download/<kind>` | Owner-checked result download |

Reuse the single-Gunicorn-worker deployment assumption and existing daemon-thread
operation pattern, with owner checks, CSRF, run identifiers, and expiration.
Use a distinct CN3S operation namespace; keep operation state out of browser
cookies. Limit expensive CN3S execution to one operation at a time initially and
use optimizer `workers=1`. Polling is lightweight; data retrieval and optimization
must not run synchronously in HTTP request handlers.

Threads do not survive reload/restart. A changed process run identifier should
report interrupted work, not poll indefinitely or pretend it can resume. A
thread is not a CPU isolation mechanism: benchmark calibration responsiveness
before accepting this deployment. If it cannot remain usable, narrow the PoC to
saved calibration while discussing a separate-process design; do not introduce
a queue framework automatically.

All SQL work uses the initiating login token, with connections closed in
`finally`. Never invoke terminal device login from a web operation. Station codes,
calibration identifiers, and download kinds resolve through server-side catalogs,
not arbitrary client file paths. Do not share user-owned result artifacts between
sessions. These follow the existing app's access model.

## Expected files and scope boundaries

New files: `web/cn3s.py`, `web/templates/cn3s.html`, `web/static/cn3s.js`.
Modify existing app registration/navigation and shared CSS only where necessary.
Make the narrow calibration-path change in `src/hydro/inference.py` when new
calibration is exposed. Avoid changes to model equations and optimizer behavior.
Update deployment dependencies, Docker/compose, and web documentation as above.
Keep any additional helper function local until a second real caller needs it.

Outside this iteration: daily inference, browser CDS downloads and credential
management, multi-station batch jobs, automated monthly scheduling, retrospective
skill analysis, probabilistic discharge ensembles, regional rainfall maps,
general model registries, durable job queues, and production scaling. Notebooks
06–08 may inform future work but are not additional deliverables here.

## Verification and acceptance checklist

Use temporary scripts/assertions and browser smoke checks; do not create or
expand a formal test suite.

- Compare baseline and web forcing/scenario values with identical captured
  inputs, exact date/index agreement, and a stated numerical tolerance (initial
  target `rtol=1e-9`, `atol=1e-8`; investigate differences before relaxing it).
- Confirm ACT = 1 shifts monthly discharge one month, warmup is excluded, and
  plotting leaves numeric exports unchanged.
- Verify browser calibration save/reload and truthful solver outcome/metrics.
- Exercise missing forecast file, missing rainfall month, incompatible daily
  calibration, expired SQL login, and empty comparison observations.
- Confirm changing configuration cannot display an old result as current; a
  browser refresh can recover a running operation while its session is valid.
- Check ownership on operation polling/downloads, CSRF on writes, conflicting
  station operations, and interrupted status after a process restart.
- Verify no original calibration/history file changes during inference; use
  before/after hashes for the representative station.
- Check raw-rainfall PNG, Plotly box traces, monthly/day views, Portuguese labels,
  partial-observation labels, downloads, and use behind `/shc`.
- Run `ruff format --check` and full `ruff check` on every modified/created Python
  file with repository configuration. Run appropriate strict mypy checks and
  report pre-existing blockers. This planning-only iteration changes no Python.
- Record representative elapsed times and peak memory for rainfall preparation,
  simulation, observation loading, and bounded calibration. Establish practical
  budgets from those measurements, rather than promising unmeasured performance.

## Planning session record

Completed in this planning session: reviewed notebooks 01–05, current scientific
APIs, Flask/authentication/operation patterns, packaging and container setup;
inspected the sample station's saved inputs/calibration metadata and UKMO file
names. No SQL queries, CDS/MERGE downloads, model runs, or application changes
were performed. Existing unrelated working-tree changes were left intact.

The user approved implementation of the plan, including browser preparation and
calibration. The existing iteration directory is retained; no plan revision copy
or new iteration folder was created.

## Implementation session record — 2026-11-24

Implemented `/shc/cn3s` using the existing Flask application, authentication,
Jinja/JavaScript UI and one-worker background-thread pattern. New code lives in
`web/cn3s.py`, `web/templates/cn3s.html`, and `web/static/cn3s.js`. Navigation and
shared styling expose the module. No changes were made to model equations,
optimizer algorithms, notebooks, or original station files.

Delivered station/basin inspection and prepared-input export; explicit station,
rainfall and discharge preparation; monthly calibration with named artifacts;
nine-centre forecast readiness; inference, raw/anomaly/corrected rainfall charts;
monthly/daily discharge comparison; numerical CSVs and provenance downloads;
owner checks, CSRF, conflicting-job protection, interrupted-job detection,
session restoration and configuration-dependent result invalidation. Preparation
stages completed files before replacement. Calibration uses exclusive creation.
A SQL comparison failure retains forecast numerical outputs and rainfall charts.

`Inference` now accepts an explicit station-relative calibration path while
preserving the legacy filename API. The web catalog rejects daily/ambiguous
calibrations. It selects the actual artifact path rather than guessing a folder.
The public `discharge_daily` input is populated through `UserSqlConnector`; web
operations never invoke the notebook's default SQL login.

Implementation decisions based on inspection and measured execution:

- Calibration preserves the saved rainfall origin and permits choosing the end
  month. This keeps the calibrated r0 tied to the same storage history used by
  inference. Arbitrary new starting dates require preparing a new input snapshot.
- Default calibration budget: 5 generations, population multiplier 5, maximum
  20 generations, one worker, no polish. Solver metadata distinguishes reaching
  the limit from convergence. The original illustrative 20/100 UI budgets were
  reduced after runtime checks; core optimizer defaults remain unchanged.
- A full local Plotly 4.1.1 bundle (and gzip copy) supports box traces. Existing
  Permanência assets remain in use by that module.
- CN3S container mounts are an optional `web/compose.cn3s.yaml` overlay so the
  existing Permanência-only deployment remains usable. Forecast/hydrography
  mounts are read-only; station and download mounts use a writable working copy.
- Web dependencies include the existing scientific libraries and the same MERGE
  downloader commit used locally, fetched as a SHA-256-checked source archive.
  Docker copies the hydrography package. No Earthkit/CDS service was added.
- Run records identify calibration/forcing files, timing, actual rainfall/date
  metadata, source revision when available, and Python source hashes. Downloaded
  numerical forcing preserves the rainfall history and both future scenarios.

### Verification evidence

Temporary verification files and browser tools were kept outside the repository,
under `/tmp/cn3s-poc-check`; no formal tests or fixtures were added.

- Real October/Marabá baseline: all 18 prec/hindcast files present; rainfall
  preparation approximately 162 seconds, total approximately 163 seconds.
  All five rainfall leads and ACT-shifted discharge months were verified.
- Real web operation: approximately 24.5 seconds with the warm download cache.
  Full rainfall and both discharge scenarios match the notebook baseline at
  `rtol=1e-9`, `atol=1e-8`, with identical indexes. Original monthly inputs and
  calibrations retained their hashes. The verification process peaked near
  719 MiB RSS; this is an observed sample, not a general memory guarantee.
- Calibration saved, reported `stopped` at its requested limit, and reloaded
  through the new canonical path. A final single-generation run with population
  multiplier 5 took approximately 121 seconds during concurrent local checks.
  Observed timing motivated the smaller demonstration budget.
- Actual MERGE monthly preparation wrote a staged September rainfall file in the
  temporary station copy; the full copied history was restored afterwards.
- Monthly and daily comparison figures were exercised with existing saved daily
  observations. Rendering preserved numerical scenario dates and values.
- Chromium verified the module, compatible calibration selection, boxplot support,
  results, completed-operation reload, invalidation on changed configuration,
  blocking November when October history is missing, and desktop/390px layouts.
  Monthly/daily comparison figures also rendered without JavaScript errors.
- API checks covered CSRF, unauthenticated/expired sessions, other-owner status
  and download rejection, duplicate concurrent operation, incompatible daily
  calibration, path traversal rejection, rainfall gaps, absent forecast cycle,
  overwrite confirmation, calibration-name collision, and restart interruption.
  Failures release the operation lock. The SQL failure path was deliberately
  exercised without an institutional token.
- Ruff formatting and full lint pass on every modified/new Python file. Strict
  mypy passes for those three files using an isolated current checker. The
  installed older mypy crashes while resolving the environment; the broader
  package check with the current checker reports the pre-existing
  `src/cn3s/model.py:374` DateOffset/Timedelta assignment mismatch. It was left
  untouched under the scope-discipline rule.
- JavaScript syntax, TOML/YAML parsing, and whitespace checks pass. Dependency
  resolution and source-wheel builds succeed. A complete isolated install of
  `.[web]` (without system site packages) imports the app, reproduces the
  forecast baseline, saves a bounded monthly calibration, and renders both
  CN3S and the existing Permanência page. Forecast parity also holds with the
  freshly resolved dependency versions (approximately 9.4 seconds with cache).

### External verification limits

Docker and the Windows/IIS host are unavailable in this workspace, so the image
was not built or launched here and IIS routing was not exercised. Live SQL and
new-station preparation require an authenticated institutional web session; no
such token was used for verification. The UI/API integration and offline/data
paths were checked, but these external operations remain deployment smoke checks.
`web/README.md` documents configuration, the optional Compose overlay, run
limitations and demonstration steps. The implementation was not published or
started on the existing shared server.

## Proposed method-call examples

Examples illustrate the intended direct API flow, not code executed in this
session. Paths refer to a dedicated PoC data root in implementation.

```python
from pathlib import Path

from cn3s import CN3S, CN3SOptimizer, CN3SParams
from cn3s.objectives import Objectives
from hydro.inference import Inference
from hydro.station import Station

DATA_ROOT = Path("/data/CN3S")
STATION_CODE = 29050000
STATION_DIR = DATA_ROOT / "stations" / str(STATION_CODE)
FREQ = "M"

# First milestone: this existing artifact is verified as monthly in its metadata.
station = Station.from_folder(STATION_DIR)
inference = Inference(station, DATA_ROOT, FREQ, "PlainNSE_alfa_livre.json")
inference.prepare_data(start_month="10", year=2026, as_of="2026-10-13")
discharge = inference.run_model()
rainfall_figure = inference.rainfall.plot_forecast_rainfall()
anomaly_figure = inference.rainfall.plot_rainfall_anomaly(unit="%", show_median=True)
```

Web-authenticated observation loading, keeping notebook login out of the request:

```python
from utils.user_sql_connector import UserSqlConnector

# access_token is supplied internally by the authenticated operation handler.
conn = UserSqlConnector(access_token)
try:
    live_station = Station.from_folder(STATION_DIR, connector=conn)
    live_station.load_series()
    daily = live_station.get_series("hidro/telemetria", "vazao")["val"]
    inference.discharge_daily = daily.loc[:"2026-10-13"].copy()
finally:
    conn.close()

monthly_figure = inference.plot_monthly_discharge(
    months_each_side=6, anchor_to_observed=False,
)
daily_figure = inference.plot_discharge()
```

Later preparation/calibration milestone (hydrography and downloader are existing
objects configured from server-side paths; `conn` is a fresh web-user connector):

```python
station = Station(STATION_CODE, connector=conn)
station.prepare_station(hydrography, output_dir=DATA_ROOT / "stations")
station.download_discharge(conn, freq="M", start="2000-01-01", end="2026-09-01")
station.download_rain(downloader, freq="M", start="2000-01-01", end="2026-09-01")

inputs = station.get_optim_data("M")
params = CN3SParams(name=station.name, area=station.metadata["drainage_area"])
model = CN3S(params, freq="M")
optim = CN3SOptimizer(
    prec=inputs["prec_mm"],
    observed_q=inputs["q_m3s"],
    model=model,
    train_ratio=0.9,
    optimize_params=["r0", "cn_i", "beta", "alfa", "k0", "k1", "k2", "act"],
    objective=Objectives.PlainNSE,
)
# Illustrative short budget: a stopped run is not a converged calibration.
optim.optimize(maxiter=5, popsize=5, tol=1e-4, workers=1, seed=42, disp=False, polish=False)
optim.save(STATION_DIR / "Monthly" / "optim" / "poc_monthly.json")
# Selecting this file for inference requires the planned path-resolution change.
```
