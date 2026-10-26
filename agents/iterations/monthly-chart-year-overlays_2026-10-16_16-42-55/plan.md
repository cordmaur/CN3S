# Monthly chart year overlays

## Plan
Remove the reference-month shaded rectangle, retain its vertical line and label only
MM/YYYY. Style the historical median as a thin dashed gray line without markers.
Map each of the reference year and its two preceding years onto the rolling window
by calendar month. Use thin subtle green for year minus two and blue for year minus
one, with a stronger black reference-year line. Split annual overlays at the displayed
December/January boundary to avoid connecting December to January of the same source
year. Show month-only axis labels and retain actual source years in hover labels.
Keep the current-month partial mean separate and retain the existing historical band,
forecast values, centered window, and monthly aggregation conventions.

## Session record
Updated the monthly chart helper and method documentation, plus only the monthly
chart explanatory markdown in notebook 05. Removed the shaded rectangle; the single
reference line is labeled MM/YYYY. Historical median is gray, dashed, width 1 with
opacity 0.6. Previous-year lines are green (year minus two) and blue (year minus one),
width 1 with opacity 0.65; reference-year black is width 2.5. All three observation
years wrap by calendar month in separate display-year segments, with actual source
year retained in hover text and one legend entry per year. Partial current-month
observations remain separate. Forecasts and historical monthly statistics are unchanged.

Ruff lint and format checks passed. A temporary numerical check used year/month-coded
daily data to verify that January 2025 appears on the right, April–December 2025 on
the left segment, the December/January traces remain separate, 2024/2025 colors and
subtle widths/opacities are correct, current partial observations stay separate, the
axis labels contain no years, and only one shape (the reference line) remains. No
formal test files, logins, or downloads were introduced. Notebook outputs were preserved;
rerunning the existing monthly plot cell renders the updated styling.

## Proposed method-call examples
```python
inference.plot_monthly_discharge(months_each_side=6).show()
```
