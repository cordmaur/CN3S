# Investigate notebook 07 clipping for Açude Poxim

## Plan

Read the current notebook configuration and saved exception. Reproduce the clipping
failure using the local forecast data, quantify watershed bounds and raster spacing,
and compare the default pixel-centre mask with intersecting-cell selection. Verify
that native observed/climatology grids intersect the basin. Investigate only; leave
notebook, model code, scientific calculation choices and user changes untouched.

## Verification

Use temporary direct calculations on the installed GIS/raster APIs and actual local
data. Report the failure location, spatial cause, and the implications of possible
remedies. No formal test suite or source edits.

## Session record

Notebook 07 currently records NoDataInBounds for the forecast variable prec during
RainfallForecast.prepare_data. Confirmed the cause with actual local inputs:

- The basin consists of three polygons (union area approximately 271.17 km²) with
  EPSG:4326 bounds (-37.4086809, -10.9641577, -37.0604821, -10.8005917).
- The common forecast grid, supplied by UKMO, has 1° spacing. The whole basin falls
  inside the pixel spanning longitude -38° to -37° and latitude -11° to -10°.
  Its centre (-37.5°, -10.5°) lies outside the basin; no forecast centres fall inside.
- GISUtil.cut_cube_by_geoms calls rio.clip with the default all_touched=False.
  Direct calls reproduce NoDataInBounds for both prec and hindcast. The notebook
  fails at src/hydro/rainfall.py:247, before preparing its data dictionary.
- Temporary all_touched=True selections succeed and retain that single intersecting
  cell. All nine centres and four configured months have finite forecast/hindcast
  values there (36 values per variable). No downloaded-domain expansion is required.
- The forecast-grid climatology also fails with the default clip and succeeds with
  all_touched=True (October value approximately 22.12 mm). Any implementation must
  apply the same coarse-grid selection to forecast, hindcast and mapped climatology
  (the separate clip on line 251).
- Native October MERGE observations/climatology have 0.1° spacing and clip successfully
  with the existing centre rule: three valid cells in a 2-by-3 bounding array each.
  Basin means are 8.375 mm observed and 32.7562 mm climatology. This explains why
  notebook 08 works. CRS reprojection and downloaded coverage are not the cause.

Recommended remedy: keep existing centre-based selection where it succeeds and use
an explicitly documented intersecting-cell fallback for empty coarse-grid masks.
The same mask must select all coarse variables. Preserve fine-grid basin means.
For this basin the forecast ratio then comes from one coarse regional cell; it does
not gain basin-scale spatial information. Enlarging the polygon would alter the
analysis region unnecessarily. This was an investigation only: no source or notebook
was changed, no Python files were created, and no Ruff/type-check run is required.
No formal tests or permanent verification scripts were added.

## Proposed method-call examples

```python
forecast = load_forecast_grids(DATA_DIR / "forecasts", pd.Timestamp("2026-10-01"), ["ukmo"], None)
clipped = forecast["prec"].rio.clip(basin.to_crs(forecast.rio.crs).geometry)
intersecting = forecast["prec"].rio.clip(
    basin.to_crs(forecast.rio.crs).geometry, all_touched=True
)
```
