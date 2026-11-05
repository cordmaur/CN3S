# Prepare station — plan

Session: 2026-10-05, 16:53:53 America/Sao_Paulo.
Status: implemented. See output.md for validation and operational notes.
Discussion updates overwrite this plan in place; no revision copies are retained.

## Session record and agreed direction

The first notebook, `nbs/Workflow/01-Prepare_Station.ipynb`, prepares a station's
identity, cobacia, drainage area, JSON metadata, and upstream basin GeoParquet.
Each subsequent numbered notebook will perform another workflow step.

The plan incorporates the following instructions:

- Save plans and session records in descriptive, timestamped directories under
  `agents/iterations/`. Overwrite this plan during discussion without versioning
  or retaining revision copies. This convention is recorded in root `AGENTS.md`.
- Use the existing Station class, simplified so initialization requires no dates
  and no Hydrography object.
- Pass output_dir only to `station.prepare_data(hydrography, output_dir=...)`.
  Station obtains its own coordinates and Hydrography determines cobacia internally.
- Save both drainage areas in km²: `drainage_area` from Hidro inventory
  `AreaDrenagem` and `drainage_area_geo` from the assigned reach's `nuareamont`.
  No upstream contribution-area sum is needed.
- Every Station method has a consistent Google-style docstring. Comments explain
  scientific assumptions and non-obvious processing steps.
- `stations.py` and `basin_overview.py` are legacy references. Their classes must
  be removed from the package; the workflow must not instantiate or depend on them.
- Keep the implementation direct. Simplify `hydrography.py` where required for
  these operations, without replacing it with another framework.

## Responsibilities and proposed API

Station manages station identity, inventory, output paths, metadata, and saving.
Hydrography manages the loaded river network and spatial calculations.

Proposed Hydrography methods:

```python
def assign_cobacia(self, lat: float, lon: float) -> str:
    ...

def drainage_area(self, cobacia: str) -> float:
    ...

def upstream_watershed(self, cobacia: str) -> gpd.GeoDataFrame:
    ...
```

`assign_cobacia()` creates one point from longitude and latitude and finds its
contribution polygon. It returns the basin code as a string. No station file,
station collection, assignment-status table, or station-management class is needed.

`drainage_area()` finds the reach for that cobacia and returns its `nuareamont`
in km². It does not sum upstream values or derive area from geometry.

`upstream_watershed()` resolves the river code for the cobacia, uses the existing
Otto upstream selection, and dissolves the selected contribution polygons into
one basin GeoDataFrame. It returns geometry with a CRS, without saving files.

Proposed Station methods:

```python
Station(code, connector=conn)
station.prepare_data(hydrography, output_dir=stations_dir)
station.load_series(start=None, end=None)
station.get_series(source="hidro/telemetria", series_type="vazao", period=slice(None))
```

`output_dir` is supplied only when calling `prepare_data()`. It names the parent
stations directory, for example `Path("/data/stations")`. Station creates
`Path(output_dir) / str(self.code)` when saving. Each call may choose a different
parent directory. `prepare_data()` returns metadata and leaves the metadata and
basin accessible as `station.metadata` and `station.upstream_watershed`.

Remove constructor dates; optional date windows belong to explicit series loading.
Initialization reads station inventory only. Spatial dependencies should be imported
when preparing data so downloading series does not require loading Hydrography.

The body of `prepare_data()` should follow these visible steps:

```python
cobacia = hydrography.assign_cobacia(lat, lon)
area_km2 = hydrography.drainage_area(cobacia)
watershed = hydrography.upstream_watershed(cobacia)
# Read inventory AreaDrenagem, assemble both areas, and save under output_dir/code.
```

There are no cobacia overrides or version arguments on `prepare_data()`.
The Hydrography instance supplies the network used by all three calls.

## Coordinate and network assumptions

Before implementation, inspect station `13710001` to confirm the inventory's
latitude/longitude columns, numeric representation, and datum. Document the
coordinate convention expected by `assign_cobacia(lat, lon)`. Use that source CRS
for the point and transform to the network CRS as needed. Coordinates are ordered
`(lon, lat)` when creating geometry.

Use containment to identify the contribution polygon and boundary intersection
when appropriate. If no basin or multiple distinct basins match, raise a clear
error for inspection. Do not introduce automatic snapping or expanding buffers.

The existing Otto algorithm uses `dsversao` internally. Keep any necessary version
handling inside Hydrography/Otto, using the loaded dataset's unambiguous matching
reach. The notebook should load a coherent network. If the source files mix
conflicting versions, identify the input-data issue during inspection rather than
adding version options to Station. Add only the internal selection needed by the
actual dataset.

The upstream basin includes the contribution polygon for the assigned outlet.
It represents the hydrographic basin at that outlet, without cutting its local
polygon at the station's exact position along the reach. Keep the existing Otto
selection logic visible and reuse it; do not build another upstream traversal.

## Metadata and output files

```text
<data_root>/stations/13710001/
    metadata.json
    upstream_watershed.parquet
```

| Metadata field | Value |
| --- | --- |
| `station_code` | Station identifier, stored as a string |
| `station_name` | Inventory `Nome` |
| `cobacia` | Code returned by Hydrography, stored as a string |
| `drainage_area` | Hidro inventory `AreaDrenagem` in km²; float or null if missing |
| `drainage_area_geo` | Assigned reach's `nuareamont` in km², stored as a float |

Keep the two sources distinct. Confirm their km² convention when inspecting inputs. Missing or invalid `nuareamont`
should be reported clearly rather than saved as a fabricated area.

Save one dissolved basin row as GeoParquet, preserving its CRS and including
station code, cobacia, and drainage area as attributes. No contribution-area sum,
second watershed artifact or geometric area calculation is needed. The metadata
preserves the inventory area for comparison with the geographic area. Write readable UTF-8 JSON with station-name accents preserved.

Station creates `<output_dir>/<station_code>/` when saving, including missing
parent directories. Calculate the outputs before writing them. Rerunning preparation regenerates the
same two files. Let file-write failures propagate; avoid cache machinery and
additional persistence abstractions.

## Implementation steps

1. Inspect representative station inventory and hydrography inputs. Confirm
   coordinate fields/datum, a coherent network, and the outlet's `nuareamont`.
2. Add the three direct Hydrography methods above. Legacy files may be read to
   understand matching and dissolving, but must not be called or wrapped. Reuse
   `Otto` where it already performs upstream selection. Keep helpers small and
   introduce them only if they make the processing easier to read.
3. Remove `Stations` and `BasinOverview`: remove the legacy modules and their
   imports/exports from `src/hydrography/__init__.py`. Inspect their references and
   remove any dependency in the active workflow. Historical notebook references
   can be identified as obsolete without rewriting unrelated notebooks.
4. Refactor Station so `prepare_data(hydrography, output_dir)` owns output paths
   and saving, while initialization reads inventory only. Preserve independent
   series loading with optional date windows. Give every method a Google-style
   docstring and comment scientific assumptions and non-obvious processing steps.
5. Complete the preparation notebook with cells for imports/autoreload, paths and
   station code, station inventory inspection, Hydrography loading, preparation,
   metadata display, and basin/station map inspection.
6. Run a representative sanity check for station `13710001`: read both saved files,
   verify cobacia consistency, compare the saved area directly with the matched
   reach's `nuareamont`, and check a non-empty basin with CRS. Check rerunning and
   independent series loading. Use temporary assertions, without a formal test suite.

Expected implementation edits: `src/hydro/station.py`,
`src/hydrography/hydrography.py`, `src/hydrography/__init__.py`, and
`nbs/Workflow/01-Prepare_Station.ipynb`, plus removal of the two legacy modules.
No new classes or dependencies are proposed. Leave unrelated Hydrography plotting
and selection methods alone unless they obstruct the requested simplification.

The current package build includes only `src/cn3s`. Use the notebook's existing
import setup for this phase; packaging changes and later workflow stages are outside
this plan. Implementation should remain a short, traceable sequence from station
coordinates to saved basin and metadata.

## Example method calls — proposed API

These calls describe the implemented interface.
Replace the illustrative input paths with actual dataset locations.

First notebook cell:

```python
%load_ext autoreload
%autoreload 2

from pathlib import Path

from hydro.station import Station
from hydrography import Hydrography
from utils.sql_connector import SqlConnector
```

Prepare and save the station:

```python
DATA_ROOT = Path("/data")
STATION_CODE = 13710001
conn = SqlConnector()

station = Station(
    code=STATION_CODE,
    connector=conn,
)
display(station.info)

hydrography = Hydrography(
    watersheds_path=DATA_ROOT / "hydrography" / "watersheds.parquet",
    reaches_path=DATA_ROOT / "hydrography" / "reaches.parquet",
)

metadata = station.prepare_data(hydrography, output_dir=DATA_ROOT / "stations")
display(metadata)
# Station creates /data/stations/13710001/ and saves both files there.
station.upstream_watershed.plot()
```

Inspect the individual spatial operations if useful during research:

```python
# lat and lon are numeric coordinates read from the inspected station inventory.
cobacia = hydrography.assign_cobacia(lat, lon)
area_km2 = hydrography.drainage_area(cobacia)
watershed = hydrography.upstream_watershed(cobacia)
```

Load hydrological observations independently:

```python
station = Station(code=13710001, connector=conn)
station.load_series(start="2000-01-01", end="2020-12-31")
discharge = station.get_series(series_type="vazao")
display(discharge)

# Dates can be omitted to load the complete available record.
station.load_series()
```
