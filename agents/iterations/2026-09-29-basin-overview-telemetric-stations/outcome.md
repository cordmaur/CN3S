# Basin overview from telemetric stations — outcome

## Implemented

- `Stations` now loads a GeoParquet path. For the telemetric schema it filters
  `ESTRESPONSAVEL == 1` and `OGMORGAO == "RHN"` before grouping, retains the highest
  numeric `ESTCODIGO` per textual `ESTCODIGOADICIONAL`, and preserves leading zeros in
  that unique key. The established `CÓDIGO`/`cobacia` file schema is also supported.
- `Stations.assign_cobacia()` joins grouped station points to the watersheds held by
  `Hydrography`, records `cobacia` and `dsversao`, and distinguishes assigned,
  unmatched, ambiguous, and reach-missing outcomes. Upstream operations reject a
  station without a usable assignment.
- `BasinOverview` loads a basin GeoParquet, works in EPSG:4674, repairs invalid
  polygon geometry in memory, selects qualifying stations, returns a station table,
  and draws a labeled map using `Hydrography.plot_reaches()`. This preserves
  river-size line widths and limits reaches to the axes with `.cx` without cutting
  them at the basin boundary. It is exported from
  `hydrography`.
- The file-backed example in
  [`01-2026-09-29-basin-overview-telemetric-stations.ipynb`](01-2026-09-29-basin-overview-telemetric-stations.ipynb)
  was executed from a fresh kernel and saved with its summary table, station table,
  and map output. The original `01-Initial_Tests.ipynb` was left as historical
  exploration. `README.md` now documents the overview. Shapely 2 is declared as a
  direct dependency.

## Verified results

The current telemetric source contains 7,306 rows. The two source filters retain
852 rows; grouping leaves 849 unique station keys. The Doce basin overview contains
**22 stations**, each assigned to exactly one BHO 2017 5k watershed. The saved notebook
has no error outputs and all five code cells have execution counts. Its map and table
were inspected after the final fresh-kernel run.

The supplied `bacia_Paranaiba.parquet` and `Sistema_Cantareira.parquet` also loaded
and normalized to EPSG:4674. They produced 24 and 3 stations respectively, all with
an assigned watershed. This exercises a projected invalid polygon and a custom
projected CRS in addition to the Doce basin.

The follow-up plotting adjustment reuses `Hydrography.plot_reaches()` with its `.cx`
viewport selection and river-size line widths. A focused plot test confirms that a
reach outside the basin but inside the axes is drawn, a reach beyond the axes is
excluded, and visible reaches have different widths. The development notebook was
rerun from a fresh kernel and its updated map was inspected.

The notebook's five-count summary now comes from `BasinOverview.summary()`, which
returns a `measure`/`count` table. The notebook calls the method directly and contains
no summary calculation.

At this rerun, the existing `Stations` loader also requires `ESTSTATUS == 0`.
Consequently, the saved notebook now reports 7,306 source rows, 661 after all three
filters, 659 grouped keys, and 16 Doce stations with watershed assignments. The
earlier 852/849/22 figures above describe the prior two-filter run and remain as
historical results.

Verification completed:

| Check | Result |
| --- | --- |
| Full pytest suite | 15 passed |
| Ruff on changed Python files and tests | Passed |
| Ruff format check on changed Python files and tests | Passed |
| mypy on `src/cn3s` | Passed, 6 source files |
| Strict mypy on `stations.py` and `basin_overview.py` | Passed, 2 source files |
| Wheel build | Passed; includes `basin_overview.py` and `shapely>=2.0` metadata |
| Fresh-kernel development notebook | Passed; saved table and map outputs |

## Limits and next steps

- The telemetric file has no CRS metadata; its coordinates are assigned the agreed
  EPSG:4674. Basin files with declared other CRSs are transformed into that working
  CRS. Source GeoParquets are never rewritten by the overview.
- This iteration defines **geographic availability**. It does not check Hydro
  discharge records, MERGE rainfall, or whether a station has enough data to
  calibrate CN3S. The telemetric file also lacks the `RIO` and `AreaDrenagem` fields
  used by parts of the existing calibration workflow.
- Static labels can overlap in denser basins; `BasinOverview.plot(labels=False)` and
  the station table remain available for inspection.
- The older notebook's MERGE import and Hydro authentication problems identified in
  the plan were outside this iteration.
