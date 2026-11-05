# Organize optimization workflow — plan and session record

Session started: 2026-10-06 10:16:04 America/Sao_Paulo.
Latest discussion: 2026-10-06 14:54:09 America/Sao_Paulo.
Status: implemented and simplified following the user's correction.
Update this record in place throughout the same iteration.

## Decisions and session record

The objective is to keep notebooks short while making data creation and loading
separate, explicit operations. Use the existing Station class; no new workflow
class, preparation module, or persistence layer.

The user corrected the initial implementation's overlapping preparation names,
extra JSON artifact, and discharge coverage rule. The final responsibilities are:

- `Station.prepare_station(hydrography, output_dir)` assigns the basin and saves
  only station metadata and upstream watershed. It replaces the previous spatial
  `prepare_data` name. Metadata is written directly with `json.dump()` into an
  opened UTF-8 file; folder loading uses `json.load()`.
- `Station.download_rain(downloader, freq, start, end)` downloads/loads MERGE rain,
  clips to the saved basin, normalizes monthly labels, and saves rain.parquet.
  It does not access SQL or hydrological observations and returns None.
- `Station.download_discharge(conn, freq, start, end)` loads hydrological data using
  the supplied caller-owned connector, averages discharge by month, and saves
  discharge.parquet. It does not download rain and returns None. Daily is
  recognized but remains unimplemented in both methods.
- `Station.get_optim_data(freq)` reads the two saved Parquet files and left-joins
  discharge onto the rainfall calendar without SQL, downloading, or recalculating.
- `Station.from_folder(station_dir, connector=None)` loads saved station identity,
  metadata, and basin without live inventory access. Pass a caller-owned connector
  only when downloading hydrological series or preparing spatial context again.

Removed `src/hydro/preparation.py` and the current station's generated
`Monthly/preparation.json`. Removed preparation metadata writing, `q_valid_days`,
complete-month discharge filtering, and unnecessary date/label validation.
No compatibility aliases or automatic snapshot migrations were added.

## Saved data and scientific processing

```text
stations/<station_code>/
    metadata.json
    upstream_watershed.parquet
    Monthly/
        rain.parquet
        discharge.parquet
    Daily/                     # Empty until daily downloading is implemented
```

The saved DataFrame has a month-start DatetimeIndex named `date` and exactly:

- `prec_mm`: arithmetic mean of monthly MERGE accumulated rainfall over clipped
  raster cells, in mm. Preserve the existing clipping and unweighted spatial mean.
- `q_m3s`: `discharge.resample("MS").mean()`, in m³/s. Ignore NaN and absent daily
  values. A month with no valid discharge remains NaN. No coverage counts or
  minimum-day thresholds.

MERGE already supplies monthly totals. Normalize their labels to month start;
do not sum or average them again over time. Use the full requested monthly
calendar and reject missing rainfall so gaps do not become consecutive model steps.
Discharge uses Station's existing Hidro/Telemetria precedence and sanitization.

Each download method creates both frequency directories, writes only its own
monthly Parquet file, and returns None. Either series may be regenerated separately.
Both files are required by get_optim_data(). Discharge outside the rainfall calendar
is excluded; unavailable matching discharge remains NaN. `freq="D"` raises NotImplementedError before live
queries, downloads, or file writes. Unsupported codes raise ValueError.

Drainage area and basin geometry remain distinct: polygon clipping needs geometry;
model conversion to m³/s needs area. Preserve both saved area sources. The notebook
continues using inventory `drainage_area` and `max_act=5`. ACT implementation and
its known positive-ACT/month-start exact-date matching limitation are unchanged.

## Implementation scope and verification

Changed `src/hydro/station.py` and both workflow notebooks. Removed
`src/hydro/preparation.py`. The first notebook calls `prepare_station()`; the
second has separate conditional calls to `download_rain()` and
`download_discharge()`, then loads joined data with `get_optim_data()`. The shared
SQL connection stays caller-owned and uses the notebook's existing conn reuse pattern.
Preserve the user's current notebook configuration, including PREPARE_INPUTS=True.
Remove stale outputs affected by the changed saved schema; retain unrelated work.

Temporary sample calculations passed; no formal test suite was added:

- Cached September/October 2000 MERGE data clipped to station 13710001's actual
  basin preserve their monthly totals and acquire month-start labels.
- Daily sample discharge with an explicit NaN and an absent date produces the
  pandas monthly means, with exactly the two requested columns.
- Parquet round-trip and `from_folder()`/`get_optim_data()` work without a connector.
- Both directories exist, Daily remains empty, and each download writes only its
  own Parquet file. Rain downloading on a folder-loaded station leaves the SQL
  connector unset and no observations loaded.
- Sample rows supplied through the existing SQL reader interface verify connector
  injection into both providers and the real Station daily merging/aggregation path.
  Re-downloading rainfall leaves discharge bytes and SQL query counts unchanged.
- Different rainfall/discharge windows are combined on the rainfall calendar;
  loading fails clearly if either saved file is absent.
- `prepare_station()` independently creates metadata and basin files; JSON and
  station names with accents round-trip through the json module.
- Daily/unsupported requests fail before live data access. Both notebook schemas
  and code-cell syntax are valid; old preparation-module and coverage references
  are removed and ACT configuration remains unchanged.

Ruff lint/format checks pass on Station and both notebooks. Targeted mypy uses
`--cache-dir=/dev/null` to avoid the installed checker's cache serialization issue.
The final mypy run reports four existing unrelated Station diagnostics: missing
close() in the live constructor error path, two Any returns in get_series(), and
the HydroStats call under skipped import analysis. The unrecognized configuration
option strict_equality_for_none also remains. No new reported type errors were
introduced; these unrelated diagnostics were left unchanged.

No live SQL queries, new downloads, calibration, or regeneration of the user's
monthly snapshot are performed during these checks. Regenerate existing saved
monthly inputs by running both download methods to create the separate files. The
older optim_data.parquet snapshot is no longer read; no automatic file migration
or cleanup of existing datasets is introduced.

## Method-call examples

Create station context:

```python
station = Station(code=STATION_CODE, connector=conn)
metadata = station.prepare_station(hydrography, output_dir=STATIONS_DIR)
```

Save rain and discharge independently:

```python
station = Station.from_folder(STATION_DIR)
station.download_rain(
    downloader, freq="M", start=START_DATE, end=END_DATE,
)
station.download_discharge(
    conn, freq="M", start=START_DATE, end=END_DATE,
)
```

Load joined inputs separately for calibration, without SQL or downloads:

```python
station = Station.from_folder(STATION_DIR)
inputs = station.get_optim_data("M")
params = CN3SParams(
    name=station.name,
    area=station.metadata["drainage_area"],
    warmup_steps=3,
)
model = CN3S(params, freq="M")
optim = CN3SOptimizer(
    prec=inputs["prec_mm"],
    observed_q=inputs["q_m3s"],
    model=model,
    train_ratio=0.8,
    max_act=5,
    objective=Objectives.PlainNSE,
)
```

Daily downloading remains deliberately unimplemented:

```python
station.download_rain(
    downloader, freq="D", start=START_DATE, end=END_DATE,
)  # Raises NotImplementedError.
station.download_discharge(
    conn, freq="D", start=START_DATE, end=END_DATE,
)  # Raises NotImplementedError.
```
