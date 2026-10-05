# Basin overview from telemetric stations — plan

**Status:** implemented and verified; see [`outcome.md`](outcome.md).

## Objective and background

Start the CN3S workflow from a user-selected basin GeoParquet and the telemetric station
GeoParquet, then show which station points lie inside the basin on a labeled map and in an
inspectable station list. This is the overview stage before choosing stations for any
calibration work.

The initial exploration is in [`nbs/01-Initial_Tests.ipynb`](../../../nbs/01-Initial_Tests.ipynb).
The previous iteration implemented a one-station preparation and calibration workflow;
see [`outcome.md`](../2026-09-29-station-calibration-workflow/outcome.md). This iteration
addresses the earlier basin overview stage and provides a watershed-based way to assign
`cobacia` to stations that do not have it in their source file.

## Agreed requirements

1. The caller specifies one basin GeoParquet from
   `/data/CN3S/geoparquets/geoparquets/`, the station source
   `/data/CN3S/Estacoes_Telemetricas.parquet`, and the existing `Hydrography` object.
2. Filter the source rows to **`ESTRESPONSAVEL == 1` and `OGMORGAO == "RHN"` before
   grouping or spatial selection**. The overview includes the qualifying stations
   inside the selected basin. `ESTSTATUS` is displayed as source metadata only; no
   additional status or discharge-availability filter is applied at this stage.
3. Group the filtered rows by `ESTCODIGOADICIONAL` and use that field as the unique
   station key. Within each group, retain the record with the highest numeric
   `ESTCODIGO` so the choice is deterministic. Preserve leading zeros in
   `ESTCODIGOADICIONAL`. The map shows the basin, station markers, and that key's labels.
4. Use **GeoParquet paths as inputs** to the new workflow and `Stations`; do not require
   the caller to prepare an in-memory DataFrame.
5. Add `Stations.assign_cobacia()`. Spatially join the station points to the watershed
   polygons already held by `Hydrography` and assign the `cobacia` of the polygon that
   contains each station. Keep unmatched or ambiguous assignments explicit.
6. Treat EPSG:4674 as the workflow's common CRS. The station GeoParquet has no CRS
   metadata, so assign EPSG:4674 to those coordinates. Reproject any supplied basin
   with a declared different CRS into EPSG:4674 before spatial operations.
7. Put the new development notebook in `nbs/dev/`, named
   `01-2026-09-29-basin-overview-telemetric-stations.ipynb`. The completed notebook
   must run from a fresh kernel and be saved with its relevant tables and map outputs.

## Findings from the current repository and data

### Notebook execution

I executed every code cell in `01-Initial_Tests.ipynb` in a fresh kernel, allowing later
cells to run after earlier errors. The executed copy and generated plot images are under
`/tmp/`, outside the repository. The notebook source was not edited. The output is **not
correct end to end**:

| Cell | Observed result | Consequence |
| --- | --- | --- |
| 3–17 | The old station GeoParquet, priority workbook, join, and hydrography load completed. | These inputs are from the previous exploratory route, not the new telemetric file. |
| 18 | `KeyError: ['CÓDIGO'] not in index`. | `CÓDIGO` had already become the index. |
| 19 | `AttributeError: 'DataFrame' object has no attribute 'cx'`. | The selected columns dropped `geometry_st`, so `Stations` holds a plain DataFrame. The visible output is a numeric line chart, not a station map. |
| 20–21 | Upstream codes were selected, but plotting failed because the selection has no active geometry. | The existing notebook's station map cannot be trusted. |
| 24 | Preparation reached MERGE and failed importing `ConnectionType` from the installed `mergedownloader`. | The installed downloader API differs from the workflow's expected API; calibration did not run. The attempt wrote or retained `/data/CN3S/stations/56920000/watershed.parquet` before failing. |
| 29–37 | The historical `.xls` model section failed first because `xlrd` is not installed; it also calls `CN3S` without the now-required `freq`. | Later `NameError` outputs are downstream of those failures. |
| 39–40 | Hydro SQL initialization requested interactive Azure device authentication and timed out; the discharge cell then lacked a client. | Live Hydro data were not checked. |

The notebook was run as an analysis exercise. Fixing MERGE, Azure access, and the old
model demonstration is outside this basin-overview iteration unless scope is expanded.

### New inputs

- `Estacoes_Telemetricas.parquet` has **7,306** point records. `ESTCODIGO` is unique;
  grouping the textual `ESTCODIGOADICIONAL` values yields **6,805** station keys. The
  file has no `cobacia`, `CÓDIGO`, or declared GeoParquet CRS. Three pairs of textual
  keys differ only by leading zeros, so code strings must not be converted to integers.
- Its point coordinates match the numeric latitude/longitude fields and look like
  geographic coordinates. Per the agreed assumption, assign EPSG:4674 (SIRGAS 2000)
  to this known source. One record is at `(0, 0)` and must not be presented as a
  Brazilian basin station.
- The basin files are nested under `geoparquets/geoparquets/`, not directly under
  `geoparquets/`. Most use EPSG:4674, but some use other projected or geographic CRSs.
  Five inspected basin files contain invalid polygon geometry; their source files
  should not be silently rewritten.
- Before the new filter, a read-only spatial overlay of `bacia_Doce.parquet` finds
  **244 raw point records**, which become **234 stations** after grouping. Those counts
  are superseded for this iteration by the required source filter.
- `ESTRESPONSAVEL` is stored as a decimal-like numeric value; 1,539 source rows have
  numeric value `1`. `OGMORGAO` is textual; 1,996 rows equal `RHN`. Applying both
  filters yields **852 raw rows** across the full file and **849 unique
  `ESTCODIGOADICIONAL` keys** after grouping. The Doce basin contains **22 filtered
  rows and 22 grouped stations**. All 22 match exactly one BHO 5k watershed. There
  are no boundary-only Doce points in this snapshot.
- A read-only `within` spatial join against the BHO 2017 5k watershed GeoParquet
  assigned exactly one watershed to each of the 22 filtered Doce stations. Before the
  new source filter, 11 of 6,805 grouped stations had no watershed match. The method
  still needs to handle unmatched and multiple matches explicitly.
- The current `Stations` constructor requires `CÓDIGO` and `cobacia`, and its upstream
  methods depend on `cobacia`. It cannot directly consume the telemetric file. The
  current `StationCalibrationWorkflow` also expects Otto-referenced station fields;
  the new watershed assignment should supply `cobacia`, while later calibration data
  and source-ID compatibility still need separate review.

## Proposed design

### File-based station loading and key selection

Make the new `Stations` entry point accept a GeoParquet path and load the telemetric
source itself. Validate the required `ESTRESPONSAVEL`, `OGMORGAO`, `ESTCODIGO`,
`ESTCODIGOADICIONAL`, and point geometry fields. First keep only rows with numeric
`ESTRESPONSAVEL == 1` and textual `OGMORGAO == "RHN"`. Then normalize
`ESTCODIGOADICIONAL` as trimmed text, preserving leading zeros; reject missing or
blank keys. Within each key, sort by numeric `ESTCODIGO` and keep the highest value.
The resulting unique `ESTCODIGOADICIONAL` values become the station index and map
label. Retain the chosen source row's `ESTCODIGO`, `ESTNOME`, `ESTSTATUS`, coordinates,
and other useful metadata. Perform filtering and grouping **before** spatial basin
selection so the same key always identifies the same qualifying source record.

Assign EPSG:4674 to the telemetric points, whose GeoParquet metadata has no CRS, and
validate coordinates against the file's latitude/longitude fields. Existing tests and
call sites that construct `Stations` from an in-memory frame will need conversion to
temporary or existing GeoParquet paths. Continue to recognize the existing
`CÓDIGO`/`cobacia` schema when it arrives from a file, so the prior calibration
workflow can still be used. Preserve upstream-selection behavior once `cobacia` is
assigned.

### `Stations.assign_cobacia()`

Use `Hydrography.watersheds` as the spatial source of Otto codes. Normalize its CRS
to EPSG:4674, then spatially join each grouped station point to the watershed polygon
that contains it. Carry both `cobacia` and `dsversao` into the station data. For a
point exactly on a polygon boundary, inspect intersecting polygons. If that gives one
unambiguous watershed, assign it. Leave zero matches or multiple distinct matches
unassigned and expose their status for inspection; never select an arbitrary code.
Check that assigned codes and versions are compatible with the reach network before
calling existing upstream methods. Keep the join reproducible and avoid changing the
source GeoParquet.

### Basin overview

Add a `BasinOverview` class in `src/hydrography/` and export it from
`hydrography/__init__.py`. Its proposed inputs are a basin GeoParquet path, the
telemetric station GeoParquet path, and a `Hydrography` instance. It constructs the
file-backed `Stations` object and calls `assign_cobacia()`. The class should:

1. Load the selected basin polygon into the EPSG:4674 working CRS. Basin files with a
   declared different CRS must be transformed to 4674 using that metadata. For invalid
   polygon input, attempt an **in-memory** `make_valid` repair and report an error if
   the result cannot represent the basin; never rewrite the source GeoParquet.
2. Select all filtered, grouped station points covered by the basin, including boundary points,
   without duplicating a station when a basin file contains multiple polygons. Expose
   the selected GeoDataFrame plus a concise table with `ESTCODIGOADICIONAL`, chosen
   `ESTCODIGO`, name, source status, assigned `cobacia`, assignment status, and
   coordinates. Show the count after source filtering and the final grouped basin count.
3. Plot the basin boundary, grouped station markers, all requested ANA-style labels,
   and hydrographic reaches within the current axes extent using
   `Hydrography.plot_reaches()`. Keep reaches outside the basin polygon when they fall
   inside that extent, and preserve the network's width scaling. Return the Matplotlib
   axes so notebook callers can adjust size, extent, and styling. Preserve an option
   to suppress labels for dense overview figures while retaining the fully labeled
   default and full table.
4. Use the basin geometry for membership rather than matching a `RIO` text field. The
   current notebook's `RIO DOCE` filter describes a named river and finds only five
   priority-workbook rows; it is not equivalent to all telemetric points in the Doce
   basin polygon.

The watershed-derived `cobacia` supports the existing Otto methods. Actual discharge
availability and any later calibration handoff remain separate from this overview.

### Development notebook and documentation

Create `nbs/dev/01-2026-09-29-basin-overview-telemetric-stations.ipynb` during
implementation. It should use the supplied Doce basin and telemetric station files,
show the applied source filters, display the 22 grouped stations and their assigned
`cobacia`, and render the labeled basin map. Execute it from a fresh kernel and save
the resulting table and map outputs in the notebook for review. Keep
`nbs/01-Initial_Tests.ipynb` as the historical exploration; its unrelated MERGE/Hydro
and legacy model failures are not part of the new notebook. Document the new entry
point, required data columns, CRS assumption, filter, and label-density limit in
`README.md`.

## Implementation sequence — after explicit user request

1. Make `Stations` file-based, with telemetric and existing Otto-referenced GeoParquet
   schema support. Validate geometry, coordinates, identifiers, the required source
   filter, and the deterministic `ESTCODIGOADICIONAL` grouping rule.
2. Add `Stations.assign_cobacia()` using watershed point-in-polygon matching,
   boundary handling, assignment status, and code/version consistency checks.
3. Add `BasinOverview` with basin loading, EPSG:4674 harmonization, optional in-memory
   geometry repair, spatial selection, station summary, and map rendering.
4. Update package exports, README, and the new `nbs/dev/` notebook to use the API.
   Keep external file paths as notebook inputs rather than package constants.
5. Add focused file-backed synthetic tests for filter order, both filter predicates,
   duplicate-key selection, leading zeros, missing or invalid geometry, watershed
   matches and non-matches, boundary ambiguity, projected basin input, existing Otto
   behavior, selection, and plotting.
6. Run the test suite and targeted lint/type checks; execute the development notebook
   from a fresh kernel, save its outputs, and manually inspect the Doce map and table.
   Record implementation results and any deviations in this folder's `outcome.md`.

## Acceptance criteria

- A fresh call using `bacia_Doce.parquet`, `Estacoes_Telemetricas.parquet`, and an
  existing `Hydrography` object applies `ESTRESPONSAVEL == 1` and `OGMORGAO == "RHN"`
  before grouping, then returns **22 stations** for the current Doce data.
  `ESTCODIGOADICIONAL` is unique in the returned station table; counts can change if
  source data change.
- Each of the 22 grouped Doce stations receives one watershed-derived `cobacia` and
  `dsversao` with the current BHO 5k data. Stations without an unambiguous watershed
  match elsewhere remain visible with an explicit assignment status.
- Every selected point is within or on the chosen basin geometry after CRS alignment.
  No external data file is changed by loading or plotting.
- The map shows a basin polygon, station points, and `ESTCODIGOADICIONAL` labels; the
  accompanying table lets users inspect every unique station and its Otto assignment.
- Existing tests for Otto-referenced `Stations` and `StationCalibrationWorkflow` still
  pass after their inputs are migrated to temporary GeoParquet files.
- Offline tests cover filtering, grouping, selection, watershed assignment, and
  plotting. The new development notebook runs from a fresh kernel without MERGE or
  Hydro login and is saved with its table and map outputs.

## Implementation notes and limits

- **CRS:** EPSG:4674 is the agreed working CRS. Some supplied basin files declare
  projected or other geographic CRSs, so they need a coordinate transformation into
  4674. The telemetric file has no CRS metadata and receives the agreed 4674 label.
- **Labels:** all 22 filtered Doce stations will be labeled. The proposal also
  includes a complete table and a label toggle for larger basins; an interactive or
  decluttered map can be considered separately.
- **Hydrography load cost:** the existing national BHO 5k reach and watershed
  GeoParquets are about 596 MB and 1.1 GB on disk. The overview should limit reaches
  to the axes extent with `.cx`, but constructing `Hydrography` still loads the national layers.
  A lightweight, basin-only loading route can be considered separately.
