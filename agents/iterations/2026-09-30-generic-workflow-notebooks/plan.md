# Generic basin, preparation, and calibration notebooks — plan

**Status:** implemented; see [`outcome.md`](outcome.md). The user approved
implementation after the monthly ACT decision was recorded.

## Objective and background

Provide three reusable development notebooks that guide a reader from a basin
overview through station data preparation to one-station calibration. The
calibration notebook must operate entirely on saved station assets, so a new fit
does not construct source clients or require network access. Move validation,
data transformations, reporting, and plotting out of notebooks into package
classes. Make source ownership visible: a notebook creates `Hydrography` and,
for preparation, `Hydrology` once and passes those instances to consumers.

The current contracts are in [`BasinOverview`](../../../src/hydrography/basin_overview.py),
[`Stations`](../../../src/hydrography/stations.py), and
[`StationCalibrationWorkflow`](../../../src/cn3s/workflow.py). The prior
[station workflow outcome](../2026-09-29-station-calibration-workflow/outcome.md),
[basin overview outcome](../2026-09-29-basin-overview-telemetric-stations/outcome.md),
and [monthly calibration outcome](../2026-09-29-monthly-station-56696000-calibration/outcome.md)
record the previous iterations. [`nbs/01-Initial_Tests.ipynb`](../../../nbs/01-Initial_Tests.ipynb)
remains an exploratory sketch, not the specification for this iteration.

## Agreed requirements and boundaries

1. Replace the two dated notebooks now in [`nbs/dev`](../../../nbs/dev/)
   with three generic notebooks, one editable configuration cell each:
   `01-basin-overview.ipynb`, `02-data-preparation.ipynb`, and
   `03-calibration.ipynb`. Preserve the dated notebooks as historical records
   outside `nbs/dev`, including their saved outputs and recent user edits.
2. A dev notebook may import, set configuration, explicitly construct injected
   dependencies, call class methods, and display returned results. Put station
   selection/validation, coverage checks, artifact reading, tables, assertions,
   optimizer orchestration, and figure creation in package classes. Record this
   rule in [`AGENTS.md`](../../../AGENTS.md) for future work.
3. The preparation notebook explicitly constructs one `Hydrography`, one
   `Stations`, and one `Hydrology`; passes them by composition; prepares and
   persists watershed/area, MERGE rain, and Hydro discharge; and reports saved
   input coverage. It should neither hide an extra `Hydrology()` call nor close a
   client it does not own.
4. The calibration notebook loads only persisted station assets. It must not
   instantiate `Hydrology`, `Hydrography`, or `Stations`, or access either live
   source. It should fit, save, and show the configuration, parameters, quality,
   and observed versus modeled discharge through class methods.
5. Keep the current example configuration in the preparation and calibration
   notebooks: station `66010000`, monthly frequency, `2000-01-01` through
   `2026-08-01`. The basin overview retains the current Doce basin example.
   These are editable examples, not hard-coded class behavior.
6. Keep existing station storage and calibration artifacts readable; preserve
   current injectable fake source interfaces and public workflow calls where
   feasible. Update documentation and focused offline checks.

Out of scope: basin-wide calibration, automatically coupling every fit to
`BasinOverview`, redesigning historical notebooks outside `nbs/dev`, changing
the source data or database authentication mechanism, and an unrequested live
data refresh. The preparation notebook is allowed to request live access when
the user runs it. The calibration notebook must run from prepared data alone.

## Current behavior and gap

- `BasinOverview` already receives `Hydrography` and provides a summary,
  station table, and `plot(ax)`. Its dated notebook creates the matplotlib
  figure and axes itself; a class method should return a ready figure.
- `Stations` already receives `Hydrography`, and creating `Stations` does not
  authenticate. `StationCalibrationWorkflow.prepare_station()` fetches sources.
  Its default `HydroDischargeSource.fetch()` constructs and closes `Hydrology`,
  which triggers Azure authentication. `Hydrology.__init__()` creates the SQL
  connector eagerly. This explains why login is observed during preparation.
- `StationCalibrationWorkflow.load_station()` and `calibrate_station()` read
  prepared files, yet the constructor currently requires `Stations` and
  creates default source adapters. There is no clear saved-only constructor.
- The dated monthly notebook contains ad hoc coverage/quality tables, asserts,
  direct Parquet/JSON reads, optimizer experiments, and matplotlib commands.
  Those responsibilities need public class APIs.
- `/data/CN3S/stations/66010000/` currently has metadata, watershed, monthly
  rain, daily/monthly discharge, and monthly calibration artifacts. Its saved
  rain period is exactly `2000-01-01` through `2026-08-01`; the saved monthly
  summary records test NSE about 0.777, `max_act=3`, and a fitted `act=0`.
  Existing saved files can support an offline notebook execution, subject to
  integrity and coverage checks.

## Proposed design and data flow

1. **Basin overview:** notebook configuration supplies basin/station/network
   paths. It constructs `Hydrography`, passes it to `BasinOverview`, then
   displays `summary()`, `station_table()`, and a new `figure()` result.
   `figure()` owns axes creation, layout, and its call to the existing `plot()`.
2. **Preparation:** notebook configuration supplies station, dates, frequencies,
   paths, and `refresh`. It constructs `Hydrography`, `Stations`, and `Hydrology`
   once; passes the source client to `StationCalibrationWorkflow` via explicit
   `HydroDischargeSource(hydrology)` or an equally clear constructor argument.
   The adapter borrows the client and never constructs or closes one. A public
   workflow method validates station assignment and returns station details;
   `prepare_station()` persists assets; another method returns a coverage and
   saved-path report. Any connection close in the notebook is a direct method
   call on the instance it created, with no notebook branching.
3. **Calibration:** a saved-only workflow constructor, such as
   `StationCalibrationWorkflow.from_prepared(data_root)`, creates no live
   providers and requires no `Stations`. Preparation and basin quality methods
   fail clearly when their required `Stations` or source is absent. The notebook
   calls a workflow method to inspect/validate prepared coverage, calls
   `calibrate_station()` with an explicit configuration, then displays class
   methods for the saved run summary, fitted parameters, train/test quality,
   and plot. These methods verify artifact existence and input revision and
   read `summary.json`/Parquet internally. Preserve the current station folder
   layout and summary schema unless a backward compatible addition is useful.
4. **Monthly ACT:** ACT represents a concentration time in days and is only
   estimated for daily calibration. Monthly simulation and calibration fix
   `act=0`; the optimizer searches the seven remaining parameters. Reject an
   explicit nonzero monthly `max_act` with a clear error, and reject nonzero
   `act` in a directly run monthly model, so monthly results cannot be silently
   shifted off their month-start index. Retain the current daily ACT search.
   The existing 66010000 summary specifies `max_act=3` but fitted `act=0`;
   keep that historical result readable and use `max_act=0` for new monthly
   runs. This follows the user's stated intent that ACT was created for daily
   calibration.
5. **Notebook migration:** move both dated `.ipynb` files into their matching
   historical iteration folders without editing their cell content. Update
   links in historical outcomes where needed. Create the three new concise
   notebooks in `nbs/dev` and update its README and the root README to describe
   the three-step flow and explicit ownership.

Likely affected files: [`AGENTS.md`](../../../AGENTS.md),
[`src/cn3s/workflow.py`](../../../src/cn3s/workflow.py),
[`src/hydrography/basin_overview.py`](../../../src/hydrography/basin_overview.py),
possibly [`src/cn3s/model.py`](../../../src/cn3s/model.py) and
[`src/cn3s/optim.py`](../../../src/cn3s/optim.py) depending on the ACT decision,
[`tests/test_workflow.py`](../../../tests/test_workflow.py),
[`tests/test_basin_overview.py`](../../../tests/test_basin_overview.py),
[`nbs/dev/README.md`](../../../nbs/dev/README.md), and
[`README.md`](../../../README.md), plus the three new notebooks and historical
notebook locations.

## Implementation sequence

1. Add explicit client injection and saved-only workflow construction; retain
   compatibility for existing callers where doing so does not recreate hidden
   live clients. Define clear errors for preparation without required sources.
2. Add class-owned station/coverage/calibration reporting, saved artifact
   validation, and figures. Add a `BasinOverview.figure()` convenience method.
3. Fix monthly ACT at zero in model and optimizer while preserving daily ACT.
   Use `max_act=0` in the calibration notebook and saved effective settings.
4. Add focused tests for source ownership, offline calibration access,
   prepared coverage/artifact validation, figure/report methods, and the chosen
   ACT behavior. Use fake providers and temporary files for offline tests.
5. Archive the dated notebooks; create the three generic notebooks with one
   configuration cell each and no logic outside class calls. Preserve the
   chosen 66010000 settings and the existing autoreload convention.
6. Update `AGENTS.md`, READMEs, and historical links. Run focused pytest,
   targeted Ruff, strict mypy for affected `src/cn3s`, and notebook structure
   checks. Execute the saved-only calibration notebook from a fresh kernel on
   existing station assets and inspect its outputs. Execute the basin notebook
   if the local source files remain available. A fresh preparation run requires
   live authentication and should be performed when the user supplies it.
7. Record actual changes, check results, notebook outputs, and remaining
   limitations in `outcome.md`.

## Validation and acceptance criteria

- Exactly three generic `.ipynb` files are in `nbs/dev`, with one editable
  configuration cell per notebook and no direct data transformation, assert,
  file read, conditional/loop, optimizer experiment, or matplotlib setup.
- Preparation creates one explicit Hydro client and one explicit Hydrography
  object in its notebook. No package path used by preparation constructs a
  second Hydro client, and workflow methods do not close the borrowed client.
- Calibration from prepared 66010000 data runs without constructing source
  clients or contacting Azure/MERGE. It saves a summary, history, and modeled
  series; its report shows configuration, fitted parameters, train/test quality,
  and a plot based on those saved artifacts.
- Class methods surface missing or stale inputs and insufficient usable
  observations with actionable errors. Existing valid station folders remain
  usable; the historical notebook files remain intact.
- Focused tests and static checks pass, and any executed notebook result is
  saved and inspected. Report only checks that actually run.

## Open decisions, assumptions, and risks

- **Monthly ACT:** decision recorded above. Historical summaries with nonzero
  `max_act` remain readable; rerunning them under the new monthly policy needs
  `max_act=0` and will produce a new calibration result.
- **Live preparation:** `Hydrology()` authenticates immediately; its notebook
  cannot be executed unattended without the user's Azure login. Existing saved
  66010000 data allow an offline calibration run, but do not establish that a
  newly refreshed Hydro record or MERGE download succeeds.
- **Existing workspace edits:** many repository files are already modified or
  untracked. Preserve those changes and move dated notebooks without losing
  their current user-edited content or outputs.
- **Optimization cost:** the current example uses multiprocessing and a larger
  budget. A fresh notebook fit may take time and produce a different optimum;
  report the actual seed, convergence flag, and quality instead of promising a
  particular score.

## Implementation decisions

- The generic monthly example uses seed 42, 10 generations, population size 5,
  polishing, and one worker. This makes the notebook practical to execute from
  a fresh kernel. It is a bounded example, not a claim of optimizer convergence.
- The saved-only calibration notebook and basin notebook were executed. The
  preparation notebook was left unexecuted because its deliberately explicit
  `Hydrology()` construction requests the user's Azure authentication.
- The model rejects nonzero ACT in monthly `run()`. The optimizer uses a seven
  parameter monthly search and an eight parameter daily search; historical
  summaries remain readable without migration.
