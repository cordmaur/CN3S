# Persisted thresholds and live annual stage chart

## Problem and desired outcome

Move the notebook's climatology-plus-annual-stage chart into the hydro API. Caller-supplied horizontal threshold lines (label -> stage in cm) must be stored in `DurationCurveResult`, saved in its `meta.json`, and restored on load, so a later reload plots the same chart with recent telemetry refreshed to the latest day. Do not change `Station`.

## Findings

- `nbs/02-Station_Analysis.ipynb`: a basic chart call, then a cell with the fuller inline plot (climatology, annual telemetric stage lines, thresholds, title, date axis). Cell 8 was added by the user and calls the new method.
- `DurationCurveResult` is built only inside `DurationCurveReporter.create_duration_curve` or by its existing `DurationCurveResult.load` classmethod. `DurationCurveReporter` has no classmethod to start from a saved result.
- `Reporter` (`reporter.py`) is the batch exporter; it has no live `Station`, so it does not own the live chart. It keeps working because `Result.save`/`load` handle the new field.
- Current code state (from the first implementation, to be revised): `thresholds` field on the result and `plot_annual_stage_chart` exist; `load_results` (instance method) and the post-hoc `results.thresholds = ...` workflow are to be replaced; the chart calls `Station.load_series(start, end)` which overwrites shared station state; the notebook edit was lost (editor overwrote disk copy).
- Unrelated worktree changes (e.g. `station.py`, `04-Inference.ipynb`) must be preserved.

## Revised design

1. **`DurationCurveResult.thresholds: dict[str, float]`** (label -> cm, default empty). Saved in `meta.json`; metadata without it loads as empty. Add `update_thresholds(thresholds)` which **replaces** the whole mapping (not a merge); it does not write to disk, so call `save_results(...)` again to persist.
2. **`DurationCurveReporter.__init__(station, thresholds=None)`** stores `self.thresholds`. `create_duration_curve` keeps its signature and passes `self.thresholds` into `DurationCurveResult(...)`.
3. **`DurationCurveReporter.from_saved(path, station)` classmethod** (new): loads the result with `DurationCurveResult.load(path)`, verifies the saved station code equals `station.code`, builds `cls(station, thresholds=result.thresholds)`, and sets `reporter.results`. It takes no `thresholds` argument. **Remove the instance `load_results`**: a reporter is initialised either by its constructor or by `from_saved`, never loaded afterwards. This removes the silent "thresholds ignored on load" case, and `reporter.thresholds` already holds the saved values if `create_duration_curve` is re-run. To change thresholds of a loaded result: `reporter.results.update_thresholds({...})`, then `save_results`.
4. **`plot_annual_stage_chart(ax, ref_year=None)`** with `ax` required. Plots saved climatology, the two previous years and reference year of telemetric stage, and every saved threshold with its label. Min/max share one proxy legend entry `Min/Max`; the q10-q90 band gets a filled legend patch `Permanência 90-10%` with enough alpha to be visible. Feb 29 is excluded; the reference-year line stops at the last observation.
5. **Do not disturb shared `Station` state**: the chart does not reload or modify the station; it reads the already loaded series through `Station.get_series` (the caller runs `station.load_series()` to refresh data). `Station` itself is not edited.
6. **Revert unrelated edits** made to `plot_duration_curve` earlier (docstring, leap-day mask, error message); keep it as it was.
7. **Notebook** (edit through the notebook tool, since it is open in the editor): replace the inline plot cell by `THRESHOLDS = {...}` (empty with a commented example; station levels not specified), `DurationCurveReporter(station, thresholds=THRESHOLDS)`, `create_duration_curve(...)`, then `fig, ax = plt.subplots(...)` and `duration_curve.plot_annual_stage_chart(ax)`; keep the user's cell 8 call valid; add save + reload (`from_saved`) + plot cells.
8. **Records**: correct `session.md` after implementation (it currently claims the notebook was replaced).

## Validation

- Synthetic check: result save/load round trip with thresholds, legacy `meta.json` without thresholds, `update_thresholds` replace semantics, `from_saved` station-code mismatch error, thresholds carried into a re-run, legend entries, `Station` state unchanged after plotting (stub with `series`/`stats`).
- Re-read the notebook JSON from disk after editing and confirm the cells persist.
- Ruff on the new code; no formal test suite. A real-data check needs the caller's SQL connector.

## Todos

- Add `thresholds` to the reporter constructor and pass it into the result; add `update_thresholds` (replace) on the result.
- Replace `load_results` with the `from_saved` classmethod.
- Make `ax` required, restore `Station` state after the window reload, fix the legend patch, revert unrelated `plot_duration_curve` edits.
- Update the notebook via the notebook tool and correct `session.md`.

## Proposed method-call examples

```python
THRESHOLDS = {"<alert label>": alert_cm, "<attention label>": attention_cm}

station = Station(14710000, connector=conn)
duration_curve = DurationCurveReporter(station, thresholds=THRESHOLDS)
duration_curve.create_duration_curve(series_type="cota", source=None, method="from_discharge")

fig, ax = plt.subplots(figsize=(12, 5))
duration_curve.plot_annual_stage_chart(ax)
duration_curve.save_results(results_path)
```

Later session (same chart, telemetry refreshed to the last day):

```python
station = Station(14710000, connector=conn)
duration_curve = DurationCurveReporter.from_saved(results_path / "14710000", station)

fig, ax = plt.subplots(figsize=(12, 5))
duration_curve.plot_annual_stage_chart(ax)
```

Changing thresholds of a saved result:

```python
duration_curve.results.update_thresholds({"<new label>": new_cm})  # replaces all thresholds
duration_curve.save_results(results_path)
```
