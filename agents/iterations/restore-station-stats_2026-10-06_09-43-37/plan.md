# Restore station series and statistics

Status: implemented and verified.

## Plan and session record

Restore the original station-code-keyed `Station.series`: the Hidro code holds
historical stage/discharge; internal telemetric codes hold their own observations.
Retain caller-owned SQL connectivity, inventory-only initialization, explicit
`load_series(start=..., end=...)`, and the current DataFrame return of `get_series`.
Update retrieval and record counts to use this mapping. Restore `get_source`, import
`HydroStats`, and calculate `station.stats` after loading, using the original
`EstacaoCodigo` index and `Fonte`, `cota`, `vazao` column groups. Historical
consistency level 2 counts as consolidated; telemetry has no consolidated records.
Keep the existing statistics equations and zero-valued empty-series summary.

Verify with temporary representative SQL input and assertions for separate codes,
missing days, consistency percentages, absent telemetry, empty observations,
reloading, and historical/origin precedence. Run lint/format checks on station.py.
No formal test suite, dependencies, or unrelated refactoring are planned.

## Completed work and validation

Updated station.py to use one code-keyed series mapping, restored source labels,
and repaired calc_stats. load_series automatically refreshes the quality summary.
Fixed the load guard and retained historical/origin precedence, sanitization,
and DataFrame retrieval. Updated the two inspection cells in the optimization
notebook to show station.series.keys() and station.stats; cleared their stale
outputs only.

Temporary representative SQL-reader checks passed through the actual Hidro and
Telemetria providers. Verified 33.3% missing days and 50% consolidated records for
a historical sample, telemetry origin labels and zero consolidation, daily means,
source precedence, period selection, sanitization without changing stored data,
manual recalculation, reloads without stale telemetry, and empty measurements.
Ruff lint and format checks passed. These checks used synthetic SQL results;
no live database validation was performed. No temporary tests remain in the repo.

## Proposed method-call examples

```python
station = Station(13710001, connector=conn)
station.load_series()
display(station.series[station.code]["vazao"])
display(station.stats)
station.calc_stats()  # Recalculate after manually adjusting stored observations.
display(station.get_series(source="hidro/telemetria", series_type="vazao"))
station.load_series(start="2000-01-01", end="2020-12-31")
display(station.stats["vazao"])
```
