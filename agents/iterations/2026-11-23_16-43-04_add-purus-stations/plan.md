# Add Purus stations

## Plan

Add a `STATIONS_PURUS` dictionary to cell 16 of `nbs/02-Station_Analysis.ipynb`,
following the existing `STATIONS` mapping and preserving the supplied station codes
and names.

## Session record

Added the ten requested station IDs to `STATIONS_PURUS` in cell 16. Each station
uses the same empty-parameter dictionary shape as the existing `STATIONS` mapping,
with its supplied name retained as a comment. Verified the notebook JSON and the
dictionary entries after the edit.

## Proposed method-call examples

```python
for station_id, station_params in STATIONS_PURUS.items():
    print(station_id, station_params)
```
