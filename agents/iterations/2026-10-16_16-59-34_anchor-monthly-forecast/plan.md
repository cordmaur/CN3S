# Optional monthly forecast anchoring

## Plan
Add anchor_to_observed=False to Inference.plot_monthly_discharge and forward it to
the plotting helper. When enabled, calculate a separate constant delta Q for each
scenario: reference-month observed partial mean minus its reference-month prediction.
Apply that delta to the plotted forecast series. Require both quantities in the same
reference month; do not silently substitute an older observation or later prediction.
Retain raw model results, the historical band, and annual comparison curves. Label
anchored curves and show delta Q in their hover labels. Preserve missing values and
constant offsets without clipping negative adjusted values. Explain that the partial
mean is assumed representative and the bias assumed constant over the horizon.
Expose the optional argument in notebook 05, disabled by default.

## Session record
Implemented the optional flag in Inference.plot_monthly_discharge and the chart helper.
Notebook 05 now exposes anchor_to_observed=False in its existing monthly plot cell and
explains the assumption. Anchored traces are labeled and hover shows each delta Q.
The reference month must contain both observations and every scenario's prediction.
Raw discharge_scenarios and historical statistics are preserved. Missing values stay
missing and negative adjusted values are not clipped, preserving the requested offset.

Temporary offline checks passed: partial observed mean 100 m³/s and first scenario
predictions 130/150 produce offsets -30/-50; both first plotted predictions equal 100,
all subsequent points receive their scenario's same offset, month-to-month differences
are retained, negative values are not clipped, raw forecasts are unchanged, the default
plot is unshifted, and missing reference-month observations/predictions fail explicitly.
Ruff lint and format checks passed. No login, download, or model rerun was performed;
no formal tests or new dependencies were added.

## Proposed method-call examples
```python
inference.plot_monthly_discharge(anchor_to_observed=True).show()
inference.plot_monthly_discharge(anchor_to_observed=False).show()
```
