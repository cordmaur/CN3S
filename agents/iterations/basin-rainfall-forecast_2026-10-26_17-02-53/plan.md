# Basin-only rainfall forecasting

## Approved plan

Extract `RainfallForecast(basin, data_dir, *, name="Basin")` into `hydro/rainfall.py`.
It owns monthly preparation, bias correction, rainfall arrays, and the three existing
rainfall charts. Accept a GeoDataFrame with CRS, treating all selected polygon rows
as one region. Reuse existing clipping, loader, and chart helpers.

Use composition: `Inference.rainfall` owns this component. Keep the Inference
constructor, calibration and discharge methods, with `prepare_data` delegating to
rainfall and invalidating previous simulation results. Move rainfall attributes and
plot calls to the component without forwarding aliases. Update notebook 05 accordingly.
Add notebook 07 for GeoParquet configuration, preparation, and the two requested charts.
Keep notebooks 01–04 and 06 unchanged.

Add optional `months` to preparation: a positive explicit X selects consecutive months
starting in the as-of month and must be fully available. None preserves all remaining
leads. Missing forecast files must point to notebook 03; CDS downloads remain there.
MERGE observations/climatology retain the existing downloader cache and recent window.

Preserve basin mean of cellwise forecast/hindcast ratios, percentage anomalies,
climatology correction, model median and inter-model boxplots, spatial interpolation,
CRS handling, lead labeling, saved model rainfall history and discharge results.
Current-month observed rainfall may be partial; as_of is not a historical snapshot.
No new dependency, formal test suite or inference-data persistence.

## Verification plan

Use temporary checks to compare old/new rainfall arrays, plot traces and discharge
results on identical inputs. Compare standalone and composed preparation. Exercise
one/full/unavailable horizons and December–January dates. Validate notebook structure,
run lint and strict typing on changed modules, execute the standalone notebook with
available real data, and verify untouched notebook hashes.

## Session record

Implemented `hydro/rainfall.py` and composed it into `Inference`. All rainfall state
and plots now live on `inference.rainfall`, with no compatibility aliases. The
station preparation wrapper accepts the same optional horizon and resets CN3S results.
Notebook 05 uses the new access path; its existing outputs remain intact. Notebook 07
reads a GeoParquet directly and includes both requested interactive charts. Its default
geometry is the available example basin file; no other station artifacts are needed.

Forecast downloads remain explicitly in notebook 03. Missing files name the missing
path and direct the caller there. Missing requested leads report available calendar
months. Geometry CRS is required and the existing helper handles reprojection.
No forecast loader, chart renderer, CN3S code, calibration file, or station code changed.

Validation completed:

- Captured the old implementation's actual October 2026 CDS/MERGE preparation and both
  discharge scenarios before extraction. At the same inputs, the composed workflow
  matches all rainfall arrays, forecast median, both full Plotly rainfall figures,
  rainfall scenarios and discharge results exactly (not just within a tolerance).
- Executed notebook 07 in a fresh kernel against real GeoParquet/CDS/MERGE data, with
  four forecast months, October 2026–January 2027. Both interactive figures are saved
  (nine anomaly traces and seven comparison traces). Standalone arrays match the
  equivalent subset of the composed/reference preparation exactly. The current-month
  observation reflects the existing cache, as documented; as_of is not a snapshot.
- Compared all raw-rainfall Matplotlib bars/lines and daily/monthly discharge chart
  JSON against the old implementation using the saved daily observation snapshot.
  Anchored monthly figures also match exactly over an actual observed/model overlap
  month. No live SQL sign-in or SQL retrieval was required or rerun.
- Temporary calendar checks replayed actual prepared products for one/full horizons,
  and inspected December–January selections before requesting future observations.
  Verified unavailable/expired horizons, zero/negative counts, missing forecast files,
  missing CRS and clearing previous simulations after successful re-preparation.
- Ruff formatting and lint pass for both modules; notebook lint and schema validation
  pass. Strict mypy passes for both changed modules. Existing configuration warnings
  about strict_equality_for_none and the COM812 formatter conflict remain unchanged.
- SHA-256 confirms notebooks 01–04 and 06 remain byte-for-byte unchanged.
- No dependencies or formal tests were added. Temporary verification artifacts were
  kept outside the repository and removed after validation.

## Proposed method-call examples

```python
basin = gpd.read_parquet(BASIN_PATH)
rainfall = RainfallForecast(basin, DATA_DIR, name="My basin")
rainfall.prepare_data(start_month="10", year=2026, as_of="2026-10-26", months=4)
rainfall.plot_rainfall_anomaly().show()
rainfall.plot_forecast_rainfall().show()

inference = Inference(station, DATA_DIR, FREQ, OPTIMIZATION)
inference.prepare_data(start_month=START_MONTH, year=FORECAST_YEAR, as_of=AS_OF_DATE)
inference.rainfall.plot_rainfall_anomaly().show()
inference.rainfall.plot_forecast_rainfall().show()
inference.run_model()
```
