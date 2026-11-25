# Unified hydrological reference calculations

Status: implemented and verified.
Created: 2026-11-05, America/Sao_Paulo.

## Objective and confirmed decisions

Calculate and persist the historical references needed by the supplied annual stage chart in one operation. Later, load those references and overlay recent observations without recomputing the historical statistics.

The user confirmed:

- Both result tables contain all three variables as additional flat columns: observed stage, discharge, and stage derived from discharge. This supersedes the earlier single-variable choice.
- Save under `/data/CN3S/Exceedance/<station_code>/`, preserving existing result directories.
- Always calculate all agreed statistics for all available variables. Horizontal-reference selection affects plotting only.
- Use uppercase `Q90` for 90% discharge exceedance and `C90` for 90% stage exceedance; both denote low values.
- Manual stage thresholds remain supported. `metadata.json` always includes `Cota de Alerta` and `Cota de Inundação`, with JSON null for unset values; null entries are never plotted.
- Historical reference curves stay fixed when recent observations are refreshed. Updating the reference period requires an explicit recalculation.

The design replaces the existing reporter/result classes with one analysis class and one result dataclass. It introduces no framework, new dependency, or additional class hierarchy.

## Terminology and literature

The current names obscure two different statistical objects:

| Object | Recommended descriptive name | Portuguese chart/documentation label |
| --- | --- | --- |
| Statistics grouped by month and day across years | Calendar-day statistics / daily climatology | Estatísticas históricas por dia do ano |
| Values versus exceedance percentage, using the full selected record | Period-of-record exceedance curve; flow-duration curve for discharge | Curva de permanência de cotas ou vazões |
| Calendar-day references with recent annual traces | Annual stage chart | Cotagrama anual com referências históricas |

Searcy defines a flow-duration curve using the frequency with which discharge levels are equaled or exceeded, irrespective of temporal sequence. This describes the current whole-series result, not the January–December chart. Source: [Searcy, 1959, Flow-duration curves](https://pubs.usgs.gov/publication/wsp1542A).

USGS distinguishes statistics grouped by calendar day and defines percentiles as nonexceedance values. “Daily climatology” is our descriptive name for this product, not a claim that the repository implements a standardized 30-year climatological normal. Source: [USGS Statistics Service Details](https://waterservices.usgs.gov/docs/statistics/statistics-details/).

A 5% exceedance corresponds to a high level; 95% corresponds to a low level. Source: [USGS, Estimating Flow-Duration and Low-Flow Frequency Statistics for Unregulated Streams in Oregon](https://pubs.usgs.gov/sir/2008/5126/section3.html).

These are empirical historical references. They are not annual flood exceedance probabilities or return periods. Daily climatology conditions on calendar day; the whole-record curve pools all available days, so a daily 95% reference and a whole-record 95% reference answer different questions.

## Proposed public names

| Current API | Proposed API |
| --- | --- |
| `hydro.duration_curve` | `hydro.exceedance` |
| `DurationCurveReporter` | `ExceedanceAnalysis` |
| `DurationCurveResult` and `ExceedanceCurveResult` | `ExceedanceResult` |
| Separate `create_duration_curve()` and `create_exceedance_curves()` | `calculate(...) -> ExceedanceResult` |
| `results.df` | `results.daily_curve` |
| Separate `exceedance_results.df` | `results.exceedance_curve` |
| `save_results(base_path)` | Retain, now saving the complete result |
| `from_saved(path, station)` | Retain, loading the complete result |
| `plot_annual_stage_chart(...)` | Retain its already descriptive name |
| `plot_duration_curve(...)` | `plot_daily_climatology(...)` |

`ExceedanceAnalysis.calculate()` avoids repeating “exceedance” in the method name. `ExceedanceResult.save(path)` and `.load(path)` handle an exact station directory; the analysis `save_results(base_path)` adds the station-code subdirectory, as today. Calculation returns the result and also sets `analysis.results`.

`daily_curve` is retained as a practical table/file name, but documented as calendar-day statistics. It must not be described as a flow-duration curve.

## Numerical contract

### Three observation series, one calculation

1. Obtain observed discharge and observed stage through `Station.get_series`, preserving source precedence, requested period, and researcher corrections.
2. Use one requested source policy for both observed variables. Recommend `source="hidro/telemetria"` as the explicit default, matching Station's historical-first merging. Do not use stage-versus-discharge preference heuristics to discard a variable now that both are required.
3. Convert individual discharge observations to stage with the station's rating curves.
4. Independently calculate daily climatology, whole-record exceedances, summary, coverage statistics, and descriptions for each of the three series.
5. Preserve each variable's available dates; do not restrict all three to their common intersection. Record coverage separately so different sampling periods remain visible.

`calculate(source=..., period=...)` always produces all available variables. It no longer accepts a target `series_type` or `method`; those choices belong to plotting, if needed. The annual stage chart can retain `method="from_discharge"` as its default and allow `method="direct"` to show observed-stage references.

This makes the two tables internally consistent for each variable. The current daily path transforms already-computed statistics, whereas the whole-record path transforms observations first. For a nonlinear conversion `h = sqrt(q)`, observations `[1, 9]` give mean stage `2`, but converting mean discharge gives `sqrt(5)`. Interpolated quantiles can also differ under nonlinear transformations. Convert observations first for both products; this may change existing chart values, especially MLT.

Retain the existing rating-curve equation/range/overlap policy and current centimetre rounding behavior. Revising rating-curve physics or historical validity periods is a separate task.

If rating-curve conversion fails, keep observed discharge and stage results, leave derived-stage statistics missing, and record the failure reason. Do not put observed stage into columns labeled as derived stage. Keep a stable column schema when one variable has no data, with missing values and count zero. If neither observed variable has usable data, fail clearly. Do not silently drop unsupported discharge values to produce a partial derived-stage record.

For a requested derived-stage chart whose derived result is unavailable, recommend a clear error asking the caller to choose `method="direct"`. This avoids silently changing the chart's scientific meaning. Calculation remains usable for the other variables.

### Exceedance convention and flat columns

Use `E(p) = quantile(x, 1 - p / 100)` everywhere, with pandas linear interpolation explicitly selected, preserving the current whole-record estimator. Literature also uses ranked plotting positions; this update does not silently switch to a Weibull estimator.

Always calculate `min`, `max`, `mean`, and exceedances at 5, 10, 25, 50, 75, 90, and 95 percent for each variable, plus sample count. The public frames use the user's Q/C notation rather than generic `e` names:

| Statistic | Discharge (m³/s) | Observed stage (cm) | Stage from discharge (cm) |
| --- | --- | --- | --- |
| Minimum | `Q_min` | `C_min` | `C_min_from_Q` |
| Maximum | `Q_max` | `C_max` | `C_max_from_Q` |
| Mean | `Q_mean` | `C_mean` | `C_mean_from_Q` |
| 5% exceedance | `Q5` | `C5` | `C5_from_Q` |
| 10% exceedance | `Q10` | `C10` | `C10_from_Q` |
| 25% exceedance | `Q25` | `C25` | `C25_from_Q` |
| 50% exceedance | `Q50` | `C50` | `C50_from_Q` |
| 75% exceedance | `Q75` | `C75` | `C75_from_Q` |
| 90% exceedance | `Q90` | `C90` | `C90_from_Q` |
| 95% exceedance | `Q95` | `C95` | `C95_from_Q` |
| Sample count | `Q_count` | `C_count` | `C_count_from_Q` |

This gives 33 ordinary columns, with no MultiIndex columns or nested objects. `Q95`/`C95` are low levels; `Q5`/`C5` are high levels. The same naming applies to daily statistics and the whole-record summary. `C95_from_Q` is the 95% exceedance of the converted stage observations, not a discharge value in centimetres and not a promise of exact equality with converting interpolated Q95 afterward.

### `daily_curve`

- Exactly 365 rows, MultiIndex `(month, day)`, sorted by calendar order, with the 33 flat columns above.
- Group observations by month/day, not ordinal day-of-year, so leap years do not shift March onward.
- Exclude February 29 from this calendar representation. Reindex missing calendar days to missing statistics and count zero; do not interpolate or fill gaps.
- Compute statistics from available nonmissing observations independently for each variable. Sample counts expose sparse estimates; no invented minimum-record threshold.
- For derived stage, the shaded band lies between `C90_from_Q` and `C10_from_Q`; for observed stage, between `C90` and `C10`.
- The plot can retain the familiar MLT legend while the data column is the corresponding `*_mean` column.
- No repeated station metadata columns; identity, units, and descriptions live in metadata.

The existing stored daily table is not necessarily 365 rows: leap day is currently removed only while plotting, and entirely missing calendar days are not added.

### `exceedance_curve` and `summary`

- `exceedance_curve`: index `exceedance_pct`, integer percentages 1 through 100, with three flat columns `Q`, `C`, and `C_from_Q`. This retains the full curve rather than only seven selected levels.
- `summary`: one row indexed by station code, with exactly the same 33 statistic column names as `daily_curve`, but calculated over each variable's full selected record.
- Thus `summary.loc[station_code, "Q95"]` equals `exceedance_curve.loc[95, "Q"]`, and similarly for `C95` and `C95_from_Q`.
- Q95/C95 names belong to the summary columns; the full curve already encodes the percentage in its index. Do not duplicate the entire curve into columns named for single probabilities.
- Whole-record calculations retain February 29 observations. Its exclusion is a display-calendar decision only.
- Each observation has equal weight. Missing days are not imputed; gaps and unequal seasonal coverage are exposed by per-variable statistics.
- Minimum, maximum, and mean are always computed from the observations and saved in `summary`; never estimate the mean by averaging curve ordinates.

## Combined result and persistence

`ExceedanceResult` holds `daily_curve`, `exceedance_curve`, a compact whole-record `summary`, per-variable `stats`, the existing station inventory `station_stats`, and metadata. It replaces both existing result dataclasses rather than adding a third public result type.

Confirmed station directory:

```text
/data/CN3S/Exceedance/18700000/
    daily_curve.parquet
    exceedance_curve.parquet
    stats.parquet
    summary.parquet
    station_stats.parquet
    metadata.json
```

- `stats.parquet`: one row per variable (`Q`, `C`, `C_from_Q`), with coverage, valid observation count, duration, gaps, and input consistency metrics. Derived-stage consistency describes its input discharge record, not independently observed stage quality. Statistics and descriptions must agree.
- `summary.parquet`: the one-row, 33-column whole-record table described above. Named exceedance levels come from the stored curve.
- `station_stats.parquet`: the current inventory/loaded-station statistics snapshot, explicitly distinguished from the selected-period statistics.
- `metadata.json`: station code/name, requested source and period, per-variable units, actual coverage/source composition, descriptions and availability/conversion status, calculation timestamp, sanitization, quantile convention, leap-day policy, and saved chart choices. Variable identifiers encode direct versus derived stage, so a single result-wide method is no longer appropriate.
- Include a small `schema_version` field to identify this changed file contract; this is not plan versioning and does not imply a migration framework.
- Store `thresholds` for manually entered stage levels separately from chart-only `reference_exceedances`. Never infer a probability by parsing a user-written threshold label. All reference statistics are saved regardless of the plotting choices.
- Keep save/load symmetric and exercise every file in a round trip. The current exceedance loader reads a different statistics filename from the saver and omits required fields; replacing both result types must remove this mismatch.
- Scientific persistence should not require an Excel-writing dependency. If the current human-readable workbook remains needed, provide an explicit export operation using the same tables rather than making it mandatory for save.
- PNG/PDF images remain exports generated from the loaded references and current observations. They cannot replace the stored numerical data. Chart defaults are saved; rendered recent traces are refreshed.

Raw historical observations remain the responsibility of Station/existing data storage. Saving summary curves alone permits exact reuse of those references, but cannot reproduce a later recalculation against revised source data. Full recalculation needs the original observations and rating-curve inputs; do not claim the small result folder is a complete raw-data archive.

## Plotting and refreshing

The annual chart keeps its current visual structure: daily min/max, calendar-day mean, the 90–10% daily exceedance band, annual observation traces, and a separate legend for horizontal references.

`reference_exceedances` is strictly a plotting option, never a calculation filter. Every calculation includes all eleven statistics for all three variables. The default chart shows no whole-record horizontal lines; `[95]` selects the low reference, `[5]` the high reference, and `[95, 5]` both. This update only needs 5% and 95% line selection, even though all other statistics are stored. A saved chart default may be included in metadata; an explicit plotting argument overrides it without changing or recalculating tables.

The user calls these Q95/Q5 references. Preserve physical units in the chart:

- A discharge chart would use `Q95`/`Q5` (m³/s).
- The annual observed-stage chart uses `C95`/`C5` (cm).
- The annual derived-stage chart uses `C95_from_Q`/`C5_from_Q` (cm).

Do not draw raw discharge magnitudes on a stage axis. On the supplied stage chart, label the lines `C95 — Permanência 95%` and `C5 — Permanência 5%`, adding “cota a partir da vazão” to the title or reference provenance when appropriate. The probability selector remains `[95, 5]`; the selected chart method determines the matching stage columns.

The daily min/max, mean, and 90–10% band are always part of the chart. Only the additional horizontal lines are toggled by `reference_exceedances`. Matplotlib and Plotly obtain those lines from the whole-record table, never by summarizing the daily table. Manual stage thresholds remain independent.

The existing annual plot remains stage-specific, with `method="from_discharge"` by default and `method="direct"` available. The whole-record curves are directly accessible as a DataFrame; a new specialized plotting framework is unnecessary.

Refreshing consists of loading only the needed recent stage observations into Station and redrawing. It does not call `calculate`, change the baseline period, rewrite scientific files, or require rating-curve access. Result load must work without a database. `from_saved(..., station=...)` attaches the live station only for recent observations and retains the station-code check.

Explicit recalculation requires loading the full intended historical window again before `calculate`. This matters because `Station.load_series` replaces its loaded window: recalculating with a Station containing only recent telemetry would otherwise produce an unintentionally short baseline. The API documents that `period` slices the loaded record, and the saved requested and actual coverage makes this visible. Recent observations cannot be merged exactly into old quantiles from the two summary tables alone.

## Existing files and callers

This is a coordinated API/file-format change. Update repository callers together and direct newly calculated results to `/data/CN3S/Exceedance/<station_code>/`. Keep existing result folders untouched. No permanent alias or compatibility framework is proposed.

Existing `curve.parquet` files cannot yield exact whole-record exceedances: calendar-day quantiles discard sample information. Do not manufacture a whole-record E95 by averaging daily E95 values. A legacy folder must produce a clear recalculation-needed message rather than a generic missing-file error. Preserve old files until the new results have been inspected.

Implementation touches only direct consumers:

1. Rename/rework `src/hydro/duration_curve.py` as `src/hydro/exceedance.py`, with the combined calculation and result.
2. Adapt only needed statistical helpers in `src/hydro/hydro_stats.py`; inspect their other callers before changing a shared column contract.
3. Update `src/hydro/reporter.py` batch calculation, result access, saving/loading, summaries, and chart exports. Rename its batch calculation to `calculate_exceedances`.
4. Update the relevant cells/imports in `nbs/02-Station_Analysis.ipynb` while preserving unrelated user edits.
5. Update `web/permanencia.py`: imports, result fields, chart column mappings, computed references, edit/recalculate operations, catalog/loading, and scientific file lists used for revision checks and publish/rollback. Update result-root defaults and relevant container mounts/documentation to `/data/CN3S/Exceedance`, preserving configurable overrides. Existing web persistence protection must cover both curves and auxiliary tables.
6. Update only directly affected web form handling/templates and documentation if necessary to preserve/edit computed reference selections. No web redesign.

If external scripts or deployed folders need gradual compatibility, agree on a narrowly scoped transition before implementation. Recalculation or replacement of existing saved scientific results is a separate deliberate operation; planning does not authorize overwriting them.

## Implementation sequence after plan agreement

1. Settle names and approve the numerical contract, especially conversion-before-statistics.
2. Implement observed-series selection and derived-stage conversion, then all three variable groups in both tables and the summary.
3. Implement the combined result and symmetric persistence.
4. Update the annual chart and computed reference selection.
5. Update batch/notebook/web consumers as one coordinated API migration.
6. Run representative scientific checks and compare a selected station's old/new chart, explaining changed values.

Temporary verification only, following repository policy:

- Known-value data: Q95/C95 are low, Q5/C5 are high; each curve is nonincreasing; all 33 daily/summary columns and selected chart lines agree with their source series.
- Multi-year/leap-year data: exactly 365 calendar rows, no March shift, missing days retain NaN/count zero, leap-day values remain in the whole-record calculation.
- Nonlinear rating curve: both tables use converted observations and mean stage is computed after conversion.
- Missing observed data or rating-curve failure preserves a stable schema and other valid variables. Derived columns never silently contain direct-stage fallback values.
- Save/load round trip preserves numerical tables and saved plot choices; changing recent telemetry does not change either historical table.
- Matplotlib/Plotly use the same stage C95/C5 values (observed or derived), including after reloading without rating-curve queries. Selecting no lines, one line, or both never changes any calculated table.
- Legacy folders fail clearly; the web publishes/checks/reverts the complete new file set.
- Run repository-configured full Ruff checks and formatting on every modified Python file. Run applicable type checks and report pre-existing blockers. Do not introduce a formal test suite.

## Session record

- Inspected current calculation, storage, batch, notebook, and web consumers.
- Reviewed primary USGS terminology and percentile definitions.
- The user revised the initial single-variable choice: calculate observed stage, discharge, and derived stage together in flat columns. Confirmed fixed historical references, Q/C exceedance notation, and `/data/CN3S/Exceedance/<station_code>/`.
- Clarified that all statistics are always calculated; the 95%/5% selector controls horizontal plot lines only. Documented stage-versus-discharge units and naming.
- Identified reversed percentile/exceedance naming, conversion-order differences, leap-day storage behavior, asymmetric exceedance save/load, and hard-coded web file lists.
- User approved implementation and requested notebook station 18700000, preserving manual thresholds with blank defaults. Implementation now follows this same plan; verification results will be appended below.
- Implementation completed in `src/hydro/exceedance.py`; the old `duration_curve.py` module was removed after migrating repository callers. Existing HydroStats helpers were left intact because the new joint table calculation is local to the new module.
- Updated the batch reporter and web Matplotlib/Plotly consumers, full-file publish/revision lists, chart reference selectors, nullable manual limits, result-root defaults, and related documentation.
- Executed all cells of `nbs/02-Station_Analysis.ipynb` successfully against live data for station 18700000 (PEDRA DO Ó). Saved 365 × 33 daily statistics, 100 × 3 exceedance values, summaries, statistics, metadata, and chart images under `/data/CN3S/Exceedance/18700000`. Existing `/data/CN3S/duration_curves` data were not changed.
- All three variables have status Ok. Derived-stage whole-record references: C95 = 303.5 cm and C5 = 960.333333 cm. Both standard external limits are JSON null. Visually inspected the annual chart with 2023–2026 observations and both horizontal references.
- Temporary numerical checks passed for exceedance orientation, independently sampled variables, missing days, leap-day treatment, nonlinear conversion before averaging, missing rating curves, all table round trips, and fixed historical references when plotting.
- Temporary batch PDF/HTML exports and web checks passed, including equality of plotted references, nullable threshold parsing, complete publication, injected publication failure/rollback, and metadata-only threshold/reference edits preserving every scientific table.
- Full repository-configured Ruff lint and formatting checks passed on all changed Python files and notebook cells; JavaScript syntax validation and `git diff --check` passed. No formal tests were added.
- Strict mypy checks passed for both new/migrated hydro modules using `--no-incremental --cache-dir=/dev/null --follow-imports=skip`. The installed mypy warns that the repository's `strict_equality_for_none` setting is unsupported; its normal cache-writing mode also hit an existing tool/stub internal error. Two narrowly documented argument-type ignores cover installed Matplotlib stubs that incorrectly reject supported y arrays.
- Notebook defaults to reusing saved references (`FORCE_RECALCULATE = False`). Recent telemetry refresh is independent; the optional manual-limit edit commands are shown in Markdown so reopening does not erase saved limits.
- Continue any further discussion by editing this same plan in place.

## Proposed method-call examples

These illustrate the proposed API; they do not run against the current implementation.

```python
from pathlib import Path

import matplotlib.pyplot as plt

from hydro.exceedance import ExceedanceAnalysis, ExceedanceResult

RESULTS_DIR = Path("/data/CN3S/Exceedance")
REFERENCE_PERIOD = slice("1976-01-01", "2025-12-31")
THRESHOLDS = {}  # Optional named operational stage limits in centimetres.

# station already contains the full intended historical stage/discharge records.
analysis = ExceedanceAnalysis(station, thresholds=THRESHOLDS)
result = analysis.calculate(source="hidro/telemetria", period=REFERENCE_PERIOD)
analysis.save_results(RESULTS_DIR)

# All three variables and all statistics are present regardless of plot choices.
result.daily_curve[["Q95", "C95", "C95_from_Q"]]
result.summary[["Q5", "Q95", "C5", "C95", "C5_from_Q", "C95_from_Q"]]
result.exceedance_curve.loc[[5, 95], ["Q", "C", "C_from_Q"]]

# Numerical references can be loaded without a live database connection.
station_dir = RESULTS_DIR / str(station.code)
saved = ExceedanceResult.load(station_dir)

# Later, refresh only the observations used by the annual chart.
REF_YEAR = 2026
LOOKBACK = 3
station.load_series(
    start=f"{REF_YEAR - LOOKBACK}-01-01",
    end=f"{REF_YEAR}-12-31",
    source="telemetria",
    series_type="cota",
)
analysis = ExceedanceAnalysis.from_saved(station_dir, station=station)
fig, ax = plt.subplots(figsize=(14, 7))
analysis.plot_annual_stage_chart(
    ax,
    ref_year=REF_YEAR,
    lookback=LOOKBACK,
    reference_exceedances=[95, 5],  # C95_from_Q and C5_from_Q on the stage axis.
)

# Only the selected horizontal references change; all daily bands remain.
fig, ax = plt.subplots(figsize=(14, 7))
analysis.plot_annual_stage_chart(
    ax,
    ref_year=REF_YEAR,
    lookback=LOOKBACK,
    reference_exceedances=[95],
)

# Optional: use observed-stage climatology and its C95 instead of derived stage.
fig, ax = plt.subplots(figsize=(14, 7))
analysis.plot_annual_stage_chart(
    ax,
    ref_year=REF_YEAR,
    method="direct",
    reference_exceedances=[95],
)

# Only when intentionally updating the historical baseline:
station.load_series(source="hidro/telemetria")
result = analysis.calculate(
    source="hidro/telemetria",
    period=slice("1976-01-01", "2026-12-31"),
)
# Save deliberately after reviewing this new baseline.
```
