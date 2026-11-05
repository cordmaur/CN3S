# Daily rainfall memory analysis

## Scope and plan

Analyze Station.download_rain for long daily windows and recommend a simple,
resumable processing workflow. Do not implement source changes in this iteration.

1. Inspect the current station method, notebook downloader configuration, and
   installed mergedownloader implementation.
2. Inspect one existing GRIB's metadata without loading a multi-year cube.
3. Recommend bounded-memory processing, persistent basin rainfall caching, and
   small representative verification for a later implementation.

## Findings and session record

- src/hydro/station.py calls create_cube for the entire window, then polygon
  clipping, spatial averaging, date normalization, and rain.parquet export.
- The installed downloader concatenates a list of full spatial DataArrays using
  xr.concat without explicitly configuring Dask chunks. It retains up to eight
  cubes and 128 opened DataArrays through functools.lru_cache.
- Existing daily notebook configuration uses DownloadMode.NO_UPDATE, so raw GRIB
  downloads already have a disk cache. This does not cache the derived basin mean.
- Existing local sample: downloads/DAILY/2000/01/MERGE_CPTEC_20000101.grib2.
  Rainfall rdp is float32 on a 924 x 1001 grid: 3,699,696 bytes per day,
  approximately 25.17 GiB for 7,305 days before clipping temporaries and overhead.
  A second variable exists, but the downloader selects rdp; it is not included
  in this rainfall-only estimate. Rainfall units are kg m**-2, equivalent to mm
  of water; sample time and valid_time are 2000-01-01 at 12:00.
- The code supports D despite stale docstrings claiming it is unimplemented.
  reindex currently permits missing precipitation values without rejecting them.
- Kernel out-of-memory is strongly plausible but was not verified from process
  memory profiling or operating-system kill logs. No long download was run.
- Xarray documentation was consulted for NumPy conversion and Dask chunking.

## Recommended follow-up implementation

Keep changes local to Station.download_rain and preserve its public signature
and final Daily/rain.parquet format.

For each requested day, read an existing valid station-specific text cache of
that day's basin-average precipitation in mm. If absent, obtain the raw file
through the existing downloader disk cache, open only that dataset, apply the
existing parser's coordinate/CRS postprocessing, select rdp, polygon-clip it,
compute the existing unweighted spatial mean, save the finite scalar, and close
and release the dataset before continuing. Do not accumulate raster arrays.

Prefer explicit dataset ownership using get_file plus a context-managed
xr.open_dataset and the parser's public postprocessing/variable information;
open_file retains arrays in the installed downloader's LRU cache. Reuse the
same scientific processing as the current implementation.

Suggested cache layout: <station_dir>/Daily/rain_cache/YYYY-MM-DD.txt, storing
only the derived scalar. Keep the shared raw GRIB cache in downloads. Write
cache entries through a temporary file and rename after successful validation.
A date is cached only when a valid finite basin mean was computed. Do not cache
failed downloads, empty clips, or NaN values as successful results. Zero rainfall
is valid. Keep units, source, geometry, and averaging method documented, and
invalidate derived entries if the basin or scientific method changes.

Assemble requested scalar values into the existing date-indexed prec_mm table,
check date completeness, and save Daily/rain.parquet. This keeps downstream
get_optim_data unchanged and makes an interrupted first extraction resumable.
One date-indexed Parquet cache with periodic checkpoints is a reasonable
alternative if file counts later become inconvenient; no new storage framework
or dependency is needed now.

## Proposed verification

Compare per-day extraction with the current cube method over a short period
using the same basin and precision tolerance. Repeat the call to confirm no
GRIB loading for cached dates. Interrupt/resume a short extraction, and check
that only unfinished days are processed. Confirm leap-day inclusion, date
labels, and explicit handling of a missing daily source. Observe memory over a
representative run to confirm it does not grow with the number of processed
raster days. Use temporary checks; do not add a formal test suite.

## Proposed method-call examples

Public method signature remains unchanged after the proposed implementation:

```python
station.download_rain(
    downloader,
    freq="D",
    start="2000-01-01",
    end="2019-12-31",
)

# Repeating or extending the window would reuse successful daily basin caches.
station.download_rain(
    downloader,
    freq="D",
    start="2000-01-01",
    end="2020-12-31",
)
data = station.get_optim_data(freq="D")
```
