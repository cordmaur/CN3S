# Rainfall anomaly charts, maps, and organized data

## Approved plan

Keep RainfallForecast and Inference composition. Initialize data in the constructor
with three empty xarray Datasets: forecast, observed and climatology. Retain native
clipped grids and basin summaries, with independent coordinates/resolutions/timestamps.
Use the dictionary as the only public processed-data API; migrate Inference and
notebooks 05/07, retaining the user's Rio Branco configuration and exploration.
Store dates/model settings in forecast metadata rather than dynamic class attributes.
Publish a complete new data dictionary only after successful preparation.

Forecast variables: prec, hindcast, ratio, climatology, corrected, anomaly_pct,
anomaly_mm, basin_corrected, basin_forecast, basin_anomaly_pct, basin_anomaly_mm.
Observed and climatology variables: rainfall and basin_mean. Attach correct units,
descriptions and spatial CRS. CDS raw values use fixed 30-day-equivalent mm; corrected
products and observed climatology use calendar-month mm. No download changes.

Add unit="%"/"mm" and show_median=True to the bar chart. Subdue individual bars when
highlighting a black diamond median line. Add a separate monthly boxplot method with
individual model points and the same unit/median controls. Box medians remain intrinsic.
Both charts summarize per-model basin anomalies and retain a zero reference line.

Add static monthly anomaly map panels (up to two columns), model="median" or a selected
centre, with basin outlines, masks and a shared symmetric zero-centered colour scale.
Average the original MERGE climatology onto the forecast grid before local spatial
correction. Percentage maps are 100*(ratio-1); mm maps are gridded climatology*(ratio-1).
Keep native climatology independently. Preserve existing basin correction, which uses
basin climatology times the basin mean of ratios; do not replace it with map averages.
Label median maps as cellwise model medians, which differ from medians of basin means.

No dependencies, exports, persistence methods, formal tests or changes to notebooks
01–04/06. Keep all prepared data in memory.

## Verification plan

Capture baseline basin rainfall, anomaly and discharge outputs on actual data before
editing. Use temporary checks for numerical parity, mm definitions, both chart types,
median toggles, grids/CRS/masks, individual/median maps, single-month maps and clear
errors for unprepared data/invalid units/unknown models. Execute notebook 07, inspect
rendered maps/charts, validate notebook schemas and untouched hashes, run Ruff and
strict mypy on changed code. Remove temporary verification artifacts when finished.

## Session record

Implemented the three-dataset dictionary as the only processed-data API. All four
class attributes (basin, data_dir, name, data) are initialized by the constructor.
Preparation retains clipped native observed/climatology grids and their basin means,
then computes forecast-grid climatology from the original uncut MERGE grid using
rasterio average resampling. Native timestamps, resolutions, masks and CRS remain
separate. Metadata contains preparation dates, initialization and selected models.
A complete replacement dictionary is published only after successful computation.

Added percentage/mm bar controls, subdued bars plus a prominent median, monthly
anomaly boxplots with named model points, and two-column monthly anomaly maps for
individual centres or cellwise medians. The shared map colour scale is symmetric about
zero. Median bars/boxplots use basin values; map medians are cellwise. Infinite/no-finite
anomalies and invalid units/model selection receive clear errors where applicable.
Plotting or correction before preparation points to prepare_data. show_median is
keyword-only, matching the repository lint convention for boolean options.

Preserved correct_rainfall as an explicit recalculation method. Scientific arithmetic
is centralized in a small helper reused by preparation and recalculation; existing
basin correction retains the exact percentage round trip used before this iteration.
Spatial correction remains a separate product and does not alter CN3S forcing.

Migrated Inference and notebooks 05/07 to the dictionary. Notebook 07 preserves the
Rio Branco geometry path, name, initialization, reference date, four-month horizon,
basin/hindcast plotting and object inspection. It now demonstrates dataset inspection,
both anomaly units, median toggles, both chart styles and both spatial map selections.
Executed it in a fresh kernel using actual local CDS/MERGE data. Final outputs contain
five interactive Plotly figures and four PNG figures (basin, two maps, hindcast).
Map examples use assignment only so the inline backend displays each figure once;
this was checked separately in a fresh kernel. Notebook 05's anomaly output was
refreshed from the verified actual inputs to show its new median overlay.

Validation completed:

- Captured old station and Rio Branco rainfall results, raw MERGE inputs and station
  discharge scenarios before editing. Replayed the same real inputs for comparison.
  Percentage basin anomalies, corrected rainfall, forecast medians, model rainfall
  scenarios and both discharge scenarios match exactly, not only within tolerance.
- Original anomaly bars with show_median=False and the corrected rainfall comparison
  figure match the original complete Plotly JSON exactly.
- Daily/monthly discharge charts, including observed anchoring within a genuine
  observation/model overlap month, match the previous figure JSON exactly. These
  checks used the saved daily discharge snapshot; no live SQL request was needed.
- Verified all named variables, units/descriptions, native resolutions, EPSG:4326,
  unchanged forecast masks, both mm definitions and ratio-based spatial correction.
- Verified all nine bar/point values, each monthly box's input values, median toggles,
  zero lines and unit labels. Map checks cover percentage/mm, median/ecmwf, shared
  symmetric normalization, outlines, raster values/masks and a single-month figure.
  Inspected the rendered percentage-median and mm-ECMWF map panels. Coarse edge gaps
  reflect the existing forecast-grid clipping mask; no artificial filling was added.
- Verified errors before preparation, invalid units, unknown models, unchanged data
  after failed preparation and identical results after explicit correction recalculation.
- Ruff formatting/lint, strict mypy for both changed modules, notebook lint/schema
  validation and git diff --check pass. Existing mypy strict_equality_for_none and
  Ruff COM812 formatter configuration warnings remain unchanged.
- SHA-256 confirms notebooks 01–04 and 06 are byte-for-byte unchanged.
- No dependencies, formal test suite, exports or persistence methods were added.
  Temporary baseline/input snapshots and verification artifacts were outside the
  repository and removed after validation.

## Proposed method-call examples

```python
rainfall.prepare_data(start_month=START_MONTH, year=FORECAST_YEAR,
                     as_of=AS_OF_DATE, months=FORECAST_MONTHS)
rainfall.data["forecast"]
rainfall.data["observed"]["basin_mean"]
rainfall.data["forecast"]["basin_forecast"].to_pandas()
rainfall.plot_rainfall_anomaly(unit="%", show_median=True).show()
rainfall.plot_rainfall_anomaly(unit="mm", show_median=False).show()
rainfall.plot_rainfall_anomaly_boxplot(unit="mm", show_median=True).show()
median_maps = rainfall.plot_rainfall_anomaly_map(unit="%", model="median")
ecmwf_maps = rainfall.plot_rainfall_anomaly_map(unit="mm", model="ecmwf")
```
