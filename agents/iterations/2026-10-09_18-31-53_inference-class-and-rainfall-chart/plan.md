# Inference class and rainfall chart

## Request and scope
Create the user-proposed Inference class to simplify the organized notebook, and fix
the missing bars in the raw rainfall chart. A stateful class is explicitly authorized:
it owns the station context, prepared rainfall, and simulation results. Keep notebook
04 untouched and keep the agreed read-only saved rainfall history for discharge parity.

## Implementation plan
1. Reproduce the missing-bar problem and check actual date coordinates.
2. Add src/hydro/inference.py with one class. Reuse the existing forecast.py loading
   and rendering helpers; do not modify CN3S, Station, or calibration artifacts.
3. Expose prepare_data, correct_rainfall, plot_raw_rainfall,
   plot_rainfall_anomaly, plot_forecast_rainfall, run_model, load_discharge,
   and plot_discharge. Keep ordinary public pandas/xarray attributes for inspection.
4. Constructor accepts station, data_dir, freq, and optimization filename. Preparation
   accepts start_month plus explicit year/as_of overrides so the demonstrated station
   29050000 and September 2026 forecast retain the same period and numerical outputs.
5. Replace notebook 05 processing blocks with these method calls. Keep optional saved
   calibration confirmation separate, using the already-loaded inference parameters.
6. Convert xarray times to pandas DatetimeIndex and rainfall to numpy arrays before
   Matplotlib calls. Check bar geometry and visually inspect a rendered actual-data plot.
7. Run fresh-kernel rainfall/model cells, compare original discharge traces, and run
   lint/strict typing for new code. Verify final plot on representative daily data if
   live Azure sign-in is unavailable. No formal test suite.

## Scientific conventions preserved
Mean of grid-cell forecast/hindcast ratios, basin arithmetic means, median corrected
rainfall before CN3S, read-only full historical rainfall prefix, calibrated initial
storage and ACT, online rainfall and daily discharge APIs without new persistence,
current-month rainfall shown as possibly partial, and existing historical chart
statistics/year overlays. Constructor is monthly-only because the workflow and saved
CDS products are monthly; do not suggest daily inference is supported.

## Session record
The supplied image shows the climatology line but no observed/forecast bars. Reproduced
with xarray DataArray date arguments to Matplotlib: width=20 collapses to zero width
on the day-based date axis, consistent with nanosecond arithmetic in the width
conversion. Explicit DatetimeIndex conversion produces the intended 20-day width. Implemented src/hydro/inference.py and rewrote notebook 05 around the class.
The class is explicitly authorized by the user's proposed API; it retains prepared
state without introducing managers, interfaces, or extra data containers. The existing
forecast helpers are reused unchanged. Notebook 04, CN3S, Station, and calibration
files were not edited. SHA-256 confirms notebook 04 is byte-for-byte unchanged.

Validation completed:
- Notebook 05 now contains 33 code lines, versus 177 before this iteration.
- Fresh-kernel execution passed through calibration confirmation, actual grid/rainfall
  preparation, all rainfall plots, and both model runs; outputs are saved in notebook 05.
- Both scenarios' five displayed discharge values match notebook 04's saved traces
  at rtol=1e-12. The approved separate read-only rainfall prefix is retained.
- All 18 raw-rainfall bars have 20-day widths and date coordinates inside the axes.
  Inspected a rendered actual-data PNG: observed and forecast bars are visible, and
  the September 2025–January 2027 rainfall period matches the previous notebook.
- Rainfall anomaly and corrected-rainfall methods produce nine and seven traces.
- The discharge method matches all 15 traces from the existing renderer on the same
  representative daily inputs. Synthetic values were used only in temporary checks,
  never in the delivered notebook.
- Ruff formatting/lint and strict mypy pass for the new class; notebook lint and
  notebook schema validation pass. Mypy continues to warn about the existing
  unsupported strict_equality_for_none setting; no unrelated config was changed.
- Live SQL retrieval remains unexecuted here because it requires interactive Azure
  sign-in. The notebook exposes it as inference.load_discharge(), explicitly before
  inference.plot_discharge(), and closes its connection after retrieval.
- No new dependency, formal test suite, or inference-data persistence was added.
  Temporary verification files were removed after completion.

## Proposed method-call examples

```python
inference = Inference(station, DATA_ROOT, FREQ, OPTIMIZATION)
inference.prepare_data(start_month="09", year=2026, as_of="2026-10-09")
inference.plot_raw_rainfall()
inference.plot_rainfall_anomaly().show()
inference.plot_forecast_rainfall().show()
inference.run_model()
inference.load_discharge()
inference.plot_discharge().show()
```
