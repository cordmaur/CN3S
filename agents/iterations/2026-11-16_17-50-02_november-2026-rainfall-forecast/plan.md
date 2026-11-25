# November 2026 forecast initialization

## Plan

Update notebook 03 to the November 2026 CDS initialization, retaining its nine models,
five monthly leads, precipitation/anomaly/hindcast products, existing regional domain
and conversion convention. Download and save the November files using existing CDS
credentials. Preserve all October files. Update notebook 07 to initialization month
11 and reference date 2026-11-16, retaining the Timbo_SE basin and four-month horizon.
Run notebook 07 and save fresh outputs after verifying dates, models, finite basin
results and the small-basin selection metadata. Record current-month MERGE coverage.
No model-code changes, new dependencies or formal tests.

## Verification

Validate notebook schemas, run full Ruff lint and formatting checks for both changed
notebooks, inspect cached CDS dates/leads and model availability, execute both
notebooks with real data, and inspect rendered maps. Keep request/download evidence
and any service limitations in this record. Existing notebook 03 lint findings were
unused imports (rioxarray alias/xarray) and long configuration lines; resolve the
registration import explicitly and format the touched notebook.

## Session record

Reviewed both notebooks and the existing cache/download helper. November CDS files
are not yet cached. Earthkit, CDS API, notebook tooling and credential file are present.
No credentials were printed or copied.

Completed notebook 03 with YEAR=2026 and START_MONTH=11, retaining all nine centre/system
pairs, five leads, regional domain, three products and the original conversion. The
request-loop AST is unchanged after formatting. Resolved the touched notebook's
existing unused imports by retaining an explained rioxarray accessor-registration
import and removing the unused xarray import. Saved all fresh execution outputs.

Downloaded 27 November NetCDF files (nine prec, nine anomaly, nine hindcast) beneath
/data/CN3S/forecasts, totaling 5,226,969 bytes. Existing September/October paths were
not written. CDS jobs completed successfully; the notebook's sequential download
loop required waiting for remote processing. No installation or dependency changes
were necessary.

Downloaded November MERGE daily inputs and created the normal manual monthly cache
through the existing downloader. Its metadata reports 16 days and last_day=20261116.
This is month-to-date rainfall, while climatology/forecast values are full-month totals.

Updated only configuration source cell 3 in notebook 07: START_MONTH=11 and
AS_OF_DATE=2026-11-16. Retained Timbo_SE geometry/name, all nine models, four-month
horizon, existing small-basin fallback and every chart/map option. Executed the entire
notebook in a fresh kernel and saved all original cells with fresh outputs. Temporary
verification cells were removed before saving.

Validation completed:

- All 27 expected November files open and contain nonempty spatial grids and five
  monthly leads. Lead endpoints match 30, 61, 92, 120 and 151 days after November 1,
  corresponding to the November–March accumulation periods.
- Notebook 03 schema validates and has no execution errors. AST comparison confirms
  all model/system/product requests and the processing loop remain unchanged.
- Notebook 07 metadata confirms initialization=2026-11-01, as_of=2026-11-16, all nine
  centres, four consecutive November–February months, and all_touched selection of
  one forecast cell. All prepared basin rainfall/anomaly values are finite.
- Temporary assertions verified forecast/hindcast ratio and basin correction
  arithmetic, current November observations, and the observed cache coverage.
- Median corrected basin totals are 19.08, 27.07, 48.37 and 52.70 mm for November 2026
  through February 2027, respectively.
- Notebook 07 schema validates with no saved errors; it contains five Plotly and three
  PNG figures. Inspected both refreshed November–February anomaly maps visually.
- Full Ruff check, ruff format --check, and whitespace checks pass for both notebooks.
  No Python modules were changed, so no new mypy run or formal tests were needed.
- Temporary verification scripts, source backups, progress notebooks and preview
  images were kept outside the repository and removed after review. Existing user
  changes and prior iteration work were preserved.

## Proposed method-call examples

```python
# Notebook 03
YEAR = "2026"
START_MONTH = "11"
LEADTIME_MONTHS = ["1", "2", "3", "4", "5"]
# Notebook 07
rainfall.prepare_data(start_month="11", year=2026, as_of="2026-11-16", months=4)
```
