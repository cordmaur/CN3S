# Anomaly boxplot height and Y-axis controls

## Plan

Add keyword-only height=700 and yaxis_range=None arguments to
plot_rainfall_anomaly_boxplot. Keep automatic scaling by default; an explicit tuple
sets exact lower/upper bounds in the selected unit, including symmetric (-60, 60).
Document that bounds hide values outside the displayed range. Preserve chart values,
model labels and median behavior. Validate a positive height and increasing limits.

Update notebook 07 examples to show the controls, use a symmetric (-100, 100) percentage
range because real current values extend below -60%, and retain automatic mm scaling.
Disable saved output scrolling for the two boxplot cells. Refresh their outputs using
the exact actual model values already present in the notebook; no data download or
scientific recomputation is necessary. Preserve other cells and settings.

## Verification

Temporary checks will compare all trace values before/after, check default/custom
height and automatic/custom Y ranges in both units, validate bad arguments, and run
Ruff/strict typing plus notebook schema checks. No formal test suite or dependency.

## Session record

Implemented height=700 and yaxis_range=None as keyword-only boxplot arguments, with
Google-style documentation and simple positive-height/increasing-range checks.
Automatic Y scaling is retained unless explicit limits are supplied. Explicit limits
only change the viewport, never the anomaly values or boxplot statistics.

Updated both notebook 07 boxplot examples and refreshed their figure payloads from
exact actual model values already in the saved notebook. The percentage example uses
(-100, 100): current anomalies span -92.05877681162052% to +1.653475160360629%, so
(-60, 60) would hide some forecasts. Documentation demonstrates that option explicitly.
The mm example retains automatic limits. Both saved boxplot cells have scrolled=False;
other cells, map settings and outputs were preserved.

Temporary verification confirmed default 700/custom 850 pixel heights, automatic and
explicit (-60, 60) limits in both units, median overlays, zero lines, invalid argument
errors, and exact equality of all old/new trace payloads when the median is disabled.
Ruff formatting/lint, strict mypy for rainfall.py, notebook schema checks and git diff
--check pass. No dependency or formal test suite was added. Temporary verification
artifacts were removed after validation.

## Proposed method-call examples

```python
rainfall.plot_rainfall_anomaly_boxplot(
    unit="%", height=700, yaxis_range=(-60, 60),
).show()
rainfall.plot_rainfall_anomaly_boxplot(unit="mm", height=800).show()
```
