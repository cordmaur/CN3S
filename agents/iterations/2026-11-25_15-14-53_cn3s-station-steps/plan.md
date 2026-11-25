# CN3S station workflow steps

Split the existing proof of concept into Estação, Calibrar Estação and Previsão pages, keeping the visual design and numerical workflow.

1. Extract page templates and retain shared navigation, station selection and operation results. Preserve selection across pages.
2. Make Criar Estação independent of existing selection. Prepare basin and metadata and load original station.stats with the authenticated SQL connection. Save a statistics snapshot; allow existing stations to refresh it without rebuilding basins.
3. Show station identity, coordinates, inventory/geographic areas, source-separated stage/discharge statistics, and a basin map over Brazilian state boundaries (EPSG:4326).
4. Keep monthly input preparation and calibration on Calibrar Estação; preserve forecast controls/results on Previsão.
5. Verify rendered routes, browser interactions and representative data/map serialization; run Ruff and strict mypy on modified Python files. Do not add formal tests.

## Session record
Implemented three routed pages using separate Estação, Calibrar Estação and Previsão templates and a shared navigation/selection shell. New creation is independent of selection and rejects existing station folders. Creation stages geometry, metadata and full source-separated station.stats before publishing; existing stations refresh overview.json without rebuilding their basins. The saved overview contains inventory coordinates and a timestamp. Monthly inputs remain explicit operations on the calibration page. Forecast algorithms and inputs are unchanged.

Added configurable IBGE state boundaries, clipped state labels and a station marker in EPSG:4326. Map rendering does not hold the operation lock, so loading a map cannot prevent selecting another station. Missing state files and failed map loads produce visible messages. Documented SHC_STATES_PATH and the read-only SHC_STATES_HOST_DIR Compose mount.

Browser verification exposed a favicon request outside the /shc cookie path replacing the login session. The request now returns 204 before creating a session. This small app change is necessary to keep authenticated actions working.

Validation completed:
- Full Ruff check and format check passed on web/cn3s.py and web/app.py; strict mypy passed on both. JavaScript syntax check passed.
- Chromium desktop/mobile verification passed for isolated page controls, creation with no selected station, source-separated cota/vazao statistics, the real basin/state map, duplicate rejection without overwriting, statistics refresh, preserved station selection, calibration and forecast readiness, and no browser exceptions or mobile document overflow.
- A simulated SQL failure left no published station folder. Creation verification substituted only external SQL/BHO providers while exercising actual Station.prepare_station, Station.load_series, Station.calc_stats, file persistence and authenticated HTTP operations. No real station data was changed.
- Final browser evidence: /tmp/cn3s-steps/acceptance.log and station.png, calibration.png, forecast.png, mobile.png. Temporary verification scripts were removed; no formal tests added.

Limits: live institutional SQL and Docker/IIS deployment were not exercised. The default development Python has a pre-existing mismatched Pyogrio binary (MULTI_EXTENSIONS import failure); the full map/browser check passed in the clean installed web-dependency environment at /tmp/cn3s-poc-check/clean-packages. A local launch using the broken global GIS environment needs that installation repaired or a clean web environment. No project dependency was added. Existing monthly numerical computations were not changed or rerun.

## Proposed method-call examples
```python
station.prepare_station(hydrography, output_dir=temporary)
station.load_series()
station.stats
Station.from_folder(station_folder(code))
```
