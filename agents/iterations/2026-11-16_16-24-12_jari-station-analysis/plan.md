# Jari station analysis

- Include per-source station statistics in saved JSON metadata, retaining the existing Parquet table and compatibility with saved results.
- Configure the notebook batch for the nine Jari stations and select discharge-derived stages when available, otherwise observed stages; report failures without stopping the batch.
- Execute the batch and inspect saved outputs, method selections, and source availability. Record outcomes here.

## Session record

- Ran the batch for all nine stations. Seven saved direct-stage results and annual charts: 19095000, 19150800, 19151500, 19150900, 19090000, 19151000, and 19152500. Five lacked rating curves and two lacked discharge observations.
- Stations 19150840 and 19150500 had no usable observations from either source; saved their source statistics separately for inspection.
- Checked saved JSON source statistics, reloaded all seven results, verified charts, and ran Ruff format and full lint checks on the modified Python and notebook.

## Method-call examples

```python
station.load_series(source="hidro/telemetria")
result = ExceedanceAnalysis(station).calculate(source="hidro/telemetria")
result.stage_variable("from_discharge")
analysis.save_results(RESULTS_DIR)
```
