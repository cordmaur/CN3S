# Historical basin rainfall and climatology notebook

## Plan

Create `nbs/Workflow/08-Rainfall_History_Climatology.ipynb` using notebook 07 as
reference. Keep its basin polygon/path/name conventions and existing MERGE downloader
cache. Use direct notebook processing rather than introducing a new class or changing
forecast code. Configure an inclusive historical month range and show native clipped
observations, a twelve-month product climatology, basin means, monthly comparisons,
mm/percentage anomalies, and a selected-month spatial comparison. No CDS inputs,
station metadata, SQL connection, or new dependencies.

Explain the supplied product climatology, arithmetic grid-cell basin means, missing
values, completed-month selection and cache freshness. Keep processing steps visible
and outputs initially clear. Preserve all existing user changes.

## Verification

Validate notebook schema, run full repository-configured Ruff lint and formatting on
the new notebook, and execute with locally available MERGE data and basin geometry.
Use temporary representative arithmetic/coordinate/plot checks, without adding a test
suite. Record any unavailable data or execution limitations here.

## Session record

Reviewed notebook 07, `hydro.rainfall`, and installed MERGE parser/downloader code.
The historical and climatology products can be loaded independently of forecasts.
Only the new notebook and this iteration record were added. No package code,
existing notebooks, dependency files, or other user changes were edited.

Implemented 19 cells with editable basin/date/cache constants, geometry inspection,
explicit independent observation and twelve-month climatology loading, native-grid
clipping, a chronological basin comparison table, observed/climatology rainfall chart,
mm and percentage anomaly charts, climatological annual cycle/table and annual total,
and native-grid side-by-side maps. Map limits include the complete polygon outline.
The defaults retain notebook 07's Açude Poxim geometry and cover September 2025 through
October 2026. Confirmed all selected local monthly cache files report the full number
of calendar days and the expected last day. Documented the manual accumulation cache
completeness caveat, product-defined 2000–2023 reference period, missing values,
arithmetic grid-cell means, zero-baseline percentage handling and CRS assumptions.

Validation completed:

- Notebook schema validates; source has no saved execution counts or outputs.
- Executed the final notebook in a fresh Python kernel with actual local geometry and
  cached MERGE inputs. All cells passed; produced two PNG and four Plotly figures.
- Temporary assertions verified all 14 requested months, twelve climatological months,
  basin anomaly arithmetic, finite comparison values, EPSG:4326 rasters, mm units and
  plot bounds containing the full basin. Inspected the rendered comparison maps.
- Repository-configured full Ruff check and `ruff format --check` pass on the new
  notebook. The new notebook also passes whitespace checks. No Python modules were
  created or modified; no formal tests or dependencies were introduced.
- Whole-worktree `git diff --check` reports pre-existing trailing whitespace on line 45
  of the user-modified `pyproject.toml`; left that unrelated file untouched.
- Kept executed notebooks, numerical assertions and preview images outside the
  repository and removed temporary verification artifacts after review.

## Proposed method-call examples

```python
basin = gpd.read_parquet(BASIN_PATH)
observed_grid = downloader.create_cube(
    months[0].to_pydatetime(), months[-1].to_pydatetime(), InpeTypes.MONTHLY_ACCUM_MANUAL
)
observed = GISUtil.cut_cube_by_geoms(observed_grid, basin.geometry)
climatology_grid = downloader.create_cube(
    pd.Timestamp("2001-01-01"), pd.Timestamp("2001-12-01"), InpeTypes.MONTHLY_ACCUM
)
```
