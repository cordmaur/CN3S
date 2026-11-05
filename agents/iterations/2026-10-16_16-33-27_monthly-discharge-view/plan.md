# Monthly discharge comparison

## Plan
Add Inference.plot_monthly_discharge(months_each_side=6) and a chart helper in
hydro.forecast. Aggregate observed daily discharge to calendar-month means (m³/s),
then calculate historical median/P10/P90 across the monthly means for each calendar
month. Use only observations through as_of and months before its calendar month for
historical statistics. Monthly means use available daily observations without gap
filling or a minimum coverage cutoff; expose valid-day counts in hover/data. Keep the
partial current month separate from completed-month observations and full-month forecasts.
Use 13 equally spaced month slots centered on the as-of month by default. Preserve
model month labels and missing values; do not connect observations to forecasts or
shift forecasts by 14 days. Historical bands describe variability, not forecast uncertainty.
Add the new chart after the existing daily comparison in notebook 05, keeping both.
Validate with representative synthetic data and inspect available saved results without
triggering login or downloads. Preserve unrelated notebook content and outputs.

## Session record
The existing saved figure has daily calendar-year overlays and a daily percentile band.
Its monthly model markers run October 2026–March 2027, and the current notebook pins
AS_OF_DATE to October 13, 2026. The old monthly reference pools daily samples. These
are incompatible sampling/summary conventions for a wholly monthly comparison.

## Implementation and validation
Implemented the monthly aggregation/statistics in Inference.plot_monthly_discharge
and rendering in hydro.forecast.plot_monthly_discharge_comparison. Added a documented
monthly chart after the daily chart in notebook 05. Existing cells and outputs were
preserved. No extra network queries, logins, dependencies, or formal tests were added.

Temporary numerical checks passed: monthly means with unequal daily coverage yield
equally weighted year-month quantiles (January means 10 and 90 produce median 50,
P10 18, P90 82), post-as-of observations are excluded, the current mean is separately
marked partial, the current month stays centered across December/January, and a missing
forecast month remains a gap. An actual saved station Daily/discharge.parquet snapshot
and model forecast values extracted from the existing notebook figure successfully
produced an interactive HTML figure. The snapshot's September 2026 mean is 1364.447
m³/s; its historical October monthly means have median 2695.139, P10 1553.949 and P90
3184.891 m³/s (25 months). These sample statistics use the local snapshot and can differ
from the full online series loaded in the live notebook. Model forecast timestamps
remain October 2026 through March 2027; the default view is April 2026–April 2027.
The notebook's October forecast is 2389.378 m³/s. Monthly aggregation makes the sampling
consistent but does not force model forecasts to match observed monthly means.

Ruff lint/format and Python syntax checks passed. PNG visual inspection was unavailable
because the environment has neither Kaleido nor a browser renderer; no dependency was
installed solely for this. The temporary HTML was removed after serialization checks.
The new notebook cell is ready to run with its existing inference object; its output
was not fabricated from the separate saved snapshot.

## Proposed method-call examples
```python
monthly_discharge_figure = inference.plot_monthly_discharge(months_each_side=6)
monthly_discharge_figure.show()
inference.discharge_monthly
inference.discharge_monthly_stats
```
