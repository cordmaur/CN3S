# Monthly chart calendar-year transitions

## Plan
Apply the user's revised styling: remove the January year-start line and arrow,
retain only the reference-month line, and change previous-year overlays to dashed
lines with markers. Connect December of each prior year to January of its following
source year (2024 to 2025 and 2025 to 2026 for this notebook). Preserve month-slot
mapping, current-year styling, the historical band, and optional forecast anchoring.

## Session record
Revised the same iteration after user feedback. Removed the initial January marker
and changed dash-dot styling to dashed with small markers. Added separate subtle
connector segments at each visible December/January boundary using consecutive source
years. Missing endpoint means produce no connecting segment. The connection uses the
December source year's color and legend group. Current partial means remain separate.
Updated only the monthly chart's explanatory notebook markdown; outputs were preserved.
Ruff lint and format checks passed. Temporary checks verified year/month-coded endpoint
values for both requested connectors, dashed-marker styles, only the reference-month
line/label remaining, and no bridge when the January mean is missing. No live data
access or formal test files were needed.

## Proposed method-call examples
```python
inference.plot_monthly_discharge(anchor_to_observed=True).show()
```
