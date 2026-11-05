# Portuguese labels and regional anomaly maps

## Approved plan

Localize rainfall anomaly bars, boxplots and maps into Brazilian Portuguese, including
month labels and hover/median/distribution text. Display the full nine model names
from notebook 03 as a model_name coordinate, retaining originating-centre model IDs
for files and selection. Preserve numerical values, model order/colours and controls.

Extend the loader to accept basin=None and load the downloaded domain once. Derive
unchanged basin-clipped products separately. Initialize data["map"] with unmasked
native-grid percentage/mm anomalies. MM anomalies use MERGE climatology averaged onto
the regional forecast grid. Keep all original basin rainfall and discharge calculations.

Extend plot_rainfall_anomaly_map with optional states, extent_scale=1.2 and
resample_factor=2. Extent scale multiplies basin width/height (1.2 adds 10% per side).
Select model or native cellwise median, crop with a native-cell halo, then optionally
interpolate only the display array to factor times rows/columns using bilinear
interpolation. Factor 1 retains native cells. Preserve stored data and genuine missing
values; do not extrapolate. Use bwr_r for deficits red/surpluses blue, shared symmetric
normalization, Portuguese labels and an interpolation caption.

Overlay subtle state boundaries, prominent basin outline and UF labels within visible
state portions. Explicitly load BR_UF_2022.shp in notebook 07 using existing PyShp and
construct a GeoDataFrame (installed Pyogrio cannot import). Add no dependency or
environment repair. Update notebooks 05/07 and refresh relevant outputs; preserve
Rio Branco settings/exploration and existing uncommitted work. Notebooks 01–04/06 stay
unchanged. No classes, exports, persistence methods or formal tests.

## Verification plan

Capture current actual numerical results and raw inputs before editing. Temporary
checks will verify Portuguese labels/full model names, exact basin/discharge parity,
real surrounding pixels, colour direction, extent scales 1/1.1/1.2 and clear invalid
argument errors. Verify stored arrays remain unchanged after display interpolation,
correct CRS/UF labels/viewports and single/multiple-month rendering. Execute notebook
07, inspect maps, refresh notebook 05 anomaly output, check untouched hashes/notebook
schemas, Ruff and strict typing. Remove temporary artifacts after validation.

## Session record

Implemented Brazilian Portuguese anomaly chart/map titles, axes, hover templates,
median/distribution names and locale-independent month abbreviations. Numeric chart
formatting uses decimal commas. The full nine notebook-03 model names are stored in a
model_name coordinate; originating-centre IDs, model order, colours and selections
remain intact. English scientific metadata and unrelated chart APIs were not changed.

The forecast loader now accepts basin=None for the complete downloaded domain while
retaining its prior basin-clipping behavior for other callers. Rainfall preparation
loads the domain once, computes native regional percentage/mm anomalies into data["map"],
and derives the existing basin products with the original rasterization and basin
correction arithmetic. No statistics are calculated from interpolated map values.

Maps use bwr_r, a shared symmetric colour scale and extent_scale (default 1.2, ten
percent added per side). They select the native model/cellwise median, crop with a
one-cell halo and optionally bilinearly interpolate a temporary view to twice the
rows/columns. Factor 1 displays native cells. Real surrounding pixels are visible;
missing values are preserved without extrapolation. Optional state boundaries are
reprojected to the raster CRS; UF label points are inside visible state portions.
Edge text is aligned inward to keep labels readable. Basin boundaries remain prominent.

Notebook 07 retains the user's Rio Branco configuration and exploration, adds explicit
state loading with existing PyShp and exposes map controls. The BR_UF_2022 source has
27 valid EPSG:4674 geometries and SIGLA_UF labels. No Pyogrio repair was needed. Both
notebooks' affected figures were refreshed. Notebook 07 was executed in a fresh kernel
against real geometry/CDS/MERGE/state files; final outputs contain five interactive
figures and four PNG figures. After the visual edge-label adjustment, both map cells
were rerun in a fresh kernel on the verified prepared real data.

Validation completed:

- Captured the previous station/Rio Branco datasets and raw MERGE inputs before
  editing, preserving all earlier working-tree changes. Replayed identical real
  inputs for comparison. Observed/climatology datasets, raw basin grids, ratios,
  basin percentage/mm anomalies, corrected rainfall, medians, rainfall scenarios
  and discharge scenarios are numerically identical.
- Verified preparation calls the domain loader once, unmasked regional cells exist
  outside the original basin mask, and the model_name coordinate matches all nine
  full names without changing model IDs/order.
- Checked both units and median settings for bars and boxplots: per-model values,
  medians, Portuguese month/axis/legend/hover text and full names are correct.
- Verified red deficits/blue surpluses, shared symmetric normalization, raster CRS,
  state/UF overlays and label positions, extent scales 1/1.1/1.2, native and 2x
  rendering, doubled dimensions, native coordinate limits and preserved missing cells.
  Stored datasets remain identical after plotting. Invalid scale/factor arguments
  fail clearly; single-month maps render correctly.
- Visually inspected the regional median-percentage and ECMWF-mm maps, then inspected
  the final notebook map after correcting edge-label alignment. Each map cell emits
  exactly one image in a fresh kernel.
- Notebook schemas/lint, Ruff formatting, new rainfall-code lint, strict mypy for
  rainfall/inference and git diff --check pass. Loader-file lint passes when its
  pre-existing RUF034 finding is explicitly excluded for verification.
- Full checks of forecast.py expose existing discharge-renderer findings: one RUF034
  redundant conditional and seven strict-mypy errors (unreachable branches, pandas
  Index year/month typing and set_axis axis typing). The captured pre-change source
  produces the same findings. They are outside this task and were not changed.
  Existing mypy strict_equality_for_none and Ruff COM812 config warnings also remain.
- SHA-256 confirms notebooks 01–04 and 06 remain unchanged. Inference.py is also
  byte-for-byte unchanged from this iteration's starting state.
- No dependencies, classes, exports, persistence methods or formal tests were added.
  Temporary verification/input snapshots were kept outside the repository and removed
  after validation. The previous iteration folder and existing changes were preserved.

### Follow-up: explicit notebook state loading

Inspection of the current notebook found that its PyShp import, states path/loading
cell and states arguments were missing. Restored these locally without changing the
current Rio Branco settings, anomaly/boxplot median choices, or extent_scale=5.0.
The loading cell explicitly constructs a GeoDataFrame from the supplied shapefile
and its .prj CRS, and displays SIGLA_UF/NM_UF for inspection. Both map calls pass
states=states. Executed the complete current notebook in a fresh kernel and verified
27 geometries, EPSG:4674, SIGLA_UF, and RR/AM labels on both resulting map figures.
No dependency or environment changes were made. Notebook schema/lint and diff checks
pass; refreshed outputs are saved in notebook 07.

## Proposed method-call examples

```python
rainfall.plot_rainfall_anomaly(unit="%", show_median=True).show()
rainfall.plot_rainfall_anomaly_boxplot(unit="mm", show_median=True).show()
median_maps = rainfall.plot_rainfall_anomaly_map(
    unit="%", model="median", states=states, extent_scale=1.2, resample_factor=2,
)
native_maps = rainfall.plot_rainfall_anomaly_map(
    unit="mm", model="ecmwf", states=states, extent_scale=1.1, resample_factor=1,
)
```
