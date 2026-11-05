# Organize the inference workflow

## Objective and current authorization

Implement a simpler demonstration in **nbs/Workflow/05-Inference_Organized.ipynb**.
Keep **04-Inference.ipynb byte-for-byte unchanged**, including its existing user edits.
Use station 29050000, calibration ExtremeFlowBlend_alfa_livre.json, September 2026
CDS initialization, October 2026–January 2027 future rainfall, and the original
March 2026–February 2027 discharge display window. Preserve the original numerical
calculations and chart content. Do not edit any existing Python module.

The user authorized implementation after reviewing the earlier detailed plan.
This document replaces that proposal in the same iteration folder.

## Data ownership

- Calibration rainfall/discharge files remain unchanged. Use their discharge only
  for the independent calibration confirmation.
- Recent rainfall, climatology, and daily discharge are retrieved with the existing
  online APIs and kept in memory. No new snapshots, refresh switches, or persistence.
  The existing MERGE downloader cache remains as in notebook 04.
- Prepared station, calibrated parameters, and CDS grids remain existing artifacts.
- Exact discharge parity depends on the historical rainfall prefix. Notebook 04
  uses saved calibration rainfall for inference, while its online recent rainfall
  is only plotted. To satisfy the latest explicit same-output requirement, the new
  notebook reads a separate copy of `Monthly/rain.parquet`, independently of the
  optional calibration check. No stored discharge is used for inference. This
  choice is documented in notebook section 7 and was communicated to the user;
  replacing it with only recent online history would change numerical results.

## Minimal implementation

Add only the new notebook and **src/hydro/forecast.py**. No new classes, framework,
package exports, dependencies, or formal test suite.

Use three helpers, fewer than the earlier proposal:

1. `load_forecast_grids`: existing NetCDF/interpolation/clipping mechanics; return
   a Dataset with `prec` and `hindcast`, retaining model/grid dimensions.
2. `plot_rainfall_comparison`: the existing corrected rainfall chart, returning Figure.
3. `plot_discharge_comparison`: the final chart mechanics, returning Figure.

Keep historical statistics in a short explicit notebook block; a separate
`prepare_discharge_history` helper is unnecessary. Keep online requests,
bias correction, scenario construction, and CN3S calls visible in the notebook.

## Notebook sequence

1. Purpose and imports, autoreload, and uppercase configuration. Pin AS_OF_DATE
   to 2026-10-09, matching the saved original chart. Retain all nine forecast centres.
2. Load station and parameters. Optional calibration check uses `calibration_data`
   and `calibration_model`, with stored discharge used only in that block.
3. Load CDS forecast and hindcast. Their stored timedelta leads mark period ends;
   verify dates from the September initialization and label the preceding monthly
   accumulation periods. Select October–January by explicit full dates.
4. Download recent observed rainfall over the same September 2025–October 2026
   range and climatology through January 2027. Use the same downloader and basin
   arithmetic mean. Its monthly manual processor requests daily dependencies for
   the entire selected month; current-month values can be partial and cached.
   Document this without changing downloader behavior in a parity refactor.
5. Retain raw rainfall comparison, model anomaly bars, and corrected rainfall chart.
   Show forecast/hindcast grid ratio, basin mean, and climatology multiplication
   explicitly. Preserve the mean-of-grid-ratios method and median across models.
6. Construct two rainfall scenarios with stable pandas names, identical history,
   and explicit future suffixes. Display the handover. Use the independent read-only
   rainfall copy described above. Never use saved discharge as inference data.
7. Run CN3S in a short loop, copying each discharge series. Preserve ACT and
   model dates. Apply original +14-day chart positioning only inside the plot.
8. Query daily historical/recent discharge online with Station and SqlConnector,
   keeping existing source precedence and all-record baseline. Keep values in memory.
9. Calculate daily median/P10/P90 and pooled-daily monthly median visibly. Call
   the final plot with the same 2024/2025/2026 colors, rolling 12-month window,
   month markers, historical traces, and last five modeled values as notebook 04.

## Numerical and display compatibility

Preserve all original comparison conventions for this task, including calendar-year
segments and December–January connectors. Do not introduce continuous-season
labels or change the pooled-daily monthly statistic. These were methodological
suggestions in the previous plan, not compatible with the latest same-output scope.
Retain fixed 30-day conversion assumptions, unweighted spatial means, ensemble
median rainfall before CN3S, and the original forecast display extent.

Live inputs may change as upstream data are updated. Pinning AS_OF_DATE sets the
comparison calendar but does not reconstruct a historical online data snapshot.
The original saved model traces provide a numerical regression reference.

## Validation

- Hash notebook 04 before and after; confirm no existing Python module changes.
- Format/lint new files and validate notebook structure and code-cell syntax.
- Compare loading/correction calculations against the original cells using actual
  available station and forecast files and the existing MERGE downloader.
- Compare scenario discharge to the original saved Plotly traces if the parity
  rainfall history is selected; otherwise quantify and disclose differences.
- Compare extracted plotting functions against the original plotting cells using
  identical representative inputs, checking trace coordinates and values.
- Run new notebook cells in order through all accessible data steps. The online
  SQL connector uses interactive Azure DeviceCodeCredential; if authentication
  is unavailable, report the remaining live step and use synthetic discharge only
  in a temporary plotting verification, never as shipped notebook data.
- No persistent test suite or verification outputs in the repository.

## Session record

Reviewed all four Workflow notebooks and relevant CN3S/Station APIs. Original
notebook has a saved DataFrame/.sel error from variable reuse. Inspected local CDS
files: five timedelta leads (30, 61, 91, 122, 153 days) from September 2026.
Original saved final chart covers 2026-03-01 through exclusive 2027-03-01 and uses
October 2026–February 2027 discharge points. Original model ACT is one month.

Implemented the new notebook (177 code lines versus 699 in notebook 04) and one
new helper module containing three functions. No existing Python module was edited.
The original notebook's SHA-256 before/after matches, preserving its pre-existing
user changes byte-for-byte.

Validation completed:

- Fresh-kernel execution succeeded through configuration, optional calibration,
  real forecast loading, online rainfall API calls, all three rainfall diagnostics,
  scenario assembly, and both CN3S runs. Executed outputs are saved in the new notebook.
- The October–January corrected rainfall matches the original printed reference
  (85.775435, 128.751833, 176.027218, 196.445255 mm; absolute tolerance 1e-6 for
  those rounded printed values).
- Both scenarios' five displayed discharge values match the original saved Plotly
  values at relative tolerance 1e-12. The final model timestamp is 2027-02-01;
  plotting retains the original February 15 placement.
- Temporary representative-data comparisons ran the original plotting cells and
  new functions: all 15 discharge traces and 7 corrected-rainfall traces matched
  names, dates, values, and selected display attributes. Plot inputs were unchanged.
- Ruff formatting/lint passed for both new files. Strict mypy passed for the new
  module; the installed mypy also reports an existing unsupported configuration
  option (`strict_equality_for_none`), which was left untouched.
- Notebook schema validation passed. No formal tests or new dependencies were added.

The live SQL cell and final chart cell are intentionally unexecuted in the saved
notebook: SqlConnector requires interactive Azure DeviceCodeCredential sign-in.
Their code is complete; the final rendering function was checked separately as
above. No synthetic discharge is embedded in the delivered notebook. Online daily
discharge and resulting historical statistics were not claimed to match a frozen
historical snapshot. All temporary verification scripts are outside the repository
and removed at completion.

## Proposed method-call examples

```python
forecast = load_forecast_grids(FORECAST_DIR, FORECAST_INIT, MODELS, station.upstream_watershed)
ratio = (forecast["prec"] / forecast["hindcast"]).mean(["latitude", "longitude"])
rain_corrected = rain_climatology.sel(time=ratio.time) * ratio
rain_forecast = rain_corrected.median("model").to_pandas()

model = CN3S(params, freq=FREQ)
discharge = {}
for scenario in rain_scenarios:
    model.run(rain_scenarios[scenario], pbar=False)
    discharge[scenario] = model.results["q_m3s"].copy()
discharge_scenarios = pd.DataFrame(discharge)

plot_rainfall_comparison(rain_observed, rain_climatology, rain_corrected, title=TITLE).show()
plot_discharge_comparison(
    discharge_daily, discharge_scenarios, daily_stats, monthly_median,
    colors=COMPARISON_COLORS, forecast_steps=len(rain_forecast), act=params.act,
    as_of=AS_OF_DATE,
).show()
```
