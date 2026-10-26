# Daily rainfall cache implementation

## Plan

Implement the approved daily-rainfall memory analysis plan locally in
src/hydro/station.py. Keep the public download_rain signature, existing
unweighted polygon-clipped basin mean, and Daily/rain.parquet format. Process
one GRIB at a time and persist finite scalar means so interrupted extraction
can resume. Verify with temporary scripts using existing local raw files and
station 13710001; do not create a formal test suite.

## Implementation and session record

- Added _download_daily_rain as a small private Station helper. For each date,
  it reads a finite text cache or uses get_file and a context-managed
  xr.open_dataset(cache=False), followed by the downloader parser's existing
  coordinate/CRS postprocessing, variable selection, polygon clipping, and
  arithmetic spatial mean. Spatial intermediates are released each iteration.
- Avoided open_file and create_cube for daily data because the installed
  downloader retains spatial arrays and cubes in LRU caches.
- Daily means, in mm, are saved atomically through a temporary file and rename
  under Daily/rain_cache/<fingerprint>/YYYY-MM-DD.txt. The fingerprint includes
  the source identifier, units, method tag, CRS, and basin geometry WKB. This
  extends the originally suggested cache layout to prevent reuse across basin
  changes without deleting existing cache entries.
- A zero rainfall mean is valid. Nonfinite cache/computed values raise an error;
  unavailable daily files fail explicitly, without caching that day or replacing
  the previous final Parquet output. Successful earlier dates remain reusable.
- Cached scalar means take precedence over downloader raw-file update settings.
  Remove the derived rain_cache folder when intentionally refreshing rainfall
  source data. Change the method tag when changing scientific processing.
- download_rain preserves the monthly cube calculation, validates date bounds,
  requires a finite mean for each requested date, and saves the same date-indexed
  prec_mm table used by get_optim_data. Updated rainfall docstrings accordingly.
- Preserved preexisting user edits in station.py and elsewhere. No new dependency
  or formal test suite was introduced. All temporary output folders were removed.

## Verification

Temporary checks used only locally cached raw files and an existing watershed.

- Two-day comparison against the original cube calculation passed with relative
  tolerance 1e-6. Daily means: 14.284682273864746 and 11.312138557434082 mm.
- A repeated request made zero get_file calls.
- Simulated missing 2000-01-04 after successful earlier days: failed explicitly,
  did not cache the missing day, and left previous rain.parquet intact. Resume
  processed only 2000-01-04 and 2000-01-05.
- 2000-02-28 through 2000-03-01 retained the leap day and correct daily labels.
- NaN text cache was rejected; a finite zero cache was accepted.
- Changing watershed geometry caused a separate cache and fresh calculation.
- A 31-day run completed; RSS samples were approximately 389.2 to 390.2 MiB.
  Both downloader LRU cache sizes remained zero during the daily path. This is
  a representative memory check, not a full 20-year memory profile.
- Monthly September/October 2000 regression and invalid-date checks passed.
- ruff check and ruff format --check passed for src/hydro/station.py.
- Repository-configured mypy failed on the existing src/cn3s/model.py:374
  DateOffset/Timedelta assignment error and warned that strict_equality_for_none
  is unrecognized. That file/configuration was not modified in this iteration.
- git diff --check passed.

## Proposed method-call examples

```python
station.download_rain(
    downloader,
    freq="D",
    start="2000-01-01",
    end="2019-12-31",
)

# Repeat after an interruption, or extend the end date; cached means are reused.
station.download_rain(
    downloader,
    freq="D",
    start="2000-01-01",
    end="2020-12-31",
)
data = station.get_optim_data(freq="D")

# Monthly processing retains its existing scientific calculation.
station.download_rain(
    downloader,
    freq="M",
    start="2000-01-01",
    end="2019-12-31",
)
```
