# Retrospective monthly forecast comparison

## Plan
Create Workflow/06-Retrospective_Forecast.ipynb for April/May 2024 and 2025 issues,
evaluating June–September monthly discharge with the trained model from notebook 05.
Reuse CN3S, CN3SParams, Station and load_forecast_grids. Keep the analysis visible in
the notebook; add only a small cached CDS download helper in hydro/retrospective.py.
Download six monthly leads (initialization month counts as lead 1), forecast ensemble
means and matched hindcast climate means. Select the archived systems for each issue;
use the same eight centres across all four cases, excluding BOM because it joined in
May 2025. Use GEM-NEMO ECCC component as notebook 05 does, with historical versions.
Use issue dates on the 11th, after the documented multi-system release on the 10th.

Limit model antecedent rain to months strictly before initialization. Use a fixed
2000–2023 basin rainfall climatology computed from the local saved monthly observations,
not today's climatology grid. Preserve notebook 05's basin mean of forecast/hindcast
ratios and median-across-centres rainfall. Run corrected forecast rain, climatological
rain, and actual future rain as a clearly labeled hindsight diagnostic. Keep ACT's
calendar-month output shift and retain the antecedent storage prefix in every run.
Compare against observed daily-to-monthly means, expose monthly observation coverage,
and compute MAE/RMSE/bias by issue/scenario plus month/lead detail. Draw issue panels
and inter-issue/year summaries; no forecast anchoring or automatic recalibration.

The existing model's training cutoff is June 2026: explicitly label this as a
retrospective diagnostic with calibration overlap, not independent forecast skill.
CDS initialization and release dates, model version changes, and latest revised local
observations limit exact reconstruction of an operational historical run.

## Session record
Implemented nbs/Workflow/06-Retrospective_Forecast.ipynb (18 cells) and the small
hydro.retrospective.download_issue_forecasts helper. Notebook 05 and calibration files
were not modified. The helper records full CDS request metadata, reuses only matching
cached files, supports offline cache-only runs, and publishes completed NetCDF files
atomically. New caches live under /data/CN3S/forecasts/retrospective/YYYYMM/. The notebook
exports comparison CSVs, issue/lead scores, rainfall inputs, interactive HTML figures,
and a manifest including calibration parameters to the station's retrospective folder.

Verified the saved daily discharge has complete coverage for all eight June–September
2024/2025 target months. The default scoring threshold is 100% daily coverage and is
configurable. Rainfall climatology is fixed at 2000–2023; discharge bands likewise use
pre-2024 monthly means. The same eight centres are selected for all four issues; their
archived versions follow the official ECMWF table. Six leads include initialization,
and CN3S ACT=1 shifts forcing to the subsequent discharge month without manual relabeling.

Validation:
- Downloaded and retained the real April 2024 ECMWF system 51 forecast/hindcast pair
  for basin bbox [-3, -57, -20, -44]. The CDS service transiently returned HTTP 502 on
  the hindcast submission, and the existing client recovered on retry.
- Executed every notebook analysis/chart/export cell using that actual single-centre
  pair and real saved station observations. Re-running reused both cache files.
- Single-centre validation RMSEs for June–September 2024 (m³/s): forecast 2312.144,
  climatology 1986.398, actual-rain hindsight 1637.487. These are validation-case
  numbers, not results of the default eight-centre/four-issue analysis.
- Executed all four cases with synthetic CDS grids and real local observations;
  verified 48 comparison rows, 12 score groups, four observed targets per case,
  figure construction and CSV/HTML/manifest exports.
- Perturbed all observed rainfall from April 2024 onward for the April 2024 issue.
  Forecast and climatological-rain discharge were exactly unchanged; the actual-rain
  diagnostic changed. This verifies exclusion of future observed rain from forecasts.
- Verified ACT source-month/lead alignment and rejection of mismatched cache requests.
- Notebook schema/syntax checks, Ruff lint/format, and strict mypy on the new helper
  passed. Mypy reports the repository's existing unrecognized strict_equality_for_none
  configuration option but no helper typing errors.

The full default eight-centre experiment was not executed: its remaining 62 requests
run when the user executes notebook 06 and can resume from completed downloads. No
synthetic results or single-centre results were inserted as default notebook outputs.
Temporary verification scripts and exports were removed; no formal tests or new
third-party dependencies were added. Microsoft login is unnecessary for this notebook's
saved observation snapshots. Calibration overlap and revised-data limitations are
explicit in the notebook, issue metadata, and result manifest.

## Sources
- https://confluence.ecmwf.int/spaces/CKB/pages/104239050/Summary+of+available+data
- https://cds.climate.copernicus.eu/datasets/seasonal-monthly-single-levels

## Proposed method-call examples
```python
download_issue_forecasts(CACHE_DIR, initialization, systems, leads=LEADTIME_MONTHS, area=AREA)
grids = load_forecast_grids(CACHE_DIR, initialization, list(systems), station.upstream_watershed)
model = CN3S(params, freq="M")
model.run(rain_scenarios["forecast"], pbar=False)
```
