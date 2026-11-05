# Station preparation — current notes

- Construct `Station(code, connector=conn)` and save with
  `station.prepare_data(hydrography, output_dir="/data/CN3S/stations")`.
  Station creates `<output_dir>/<code>/`. Each call can choose a different parent;
  rerunning overwrites `metadata.json` and `upstream_watershed.parquet`.
- Metadata contains `drainage_area` from Hidro inventory `AreaDrenagem` and
  `drainage_area_geo` from geographic `nuareamont`, both in km². These replace the
  previous `drainage_area_km2` key. Missing inventory area is saved as JSON null.
- Every Station method now has a consistent Google-style docstring. Comments
  explain coordinate assumptions, area sources, connector ownership, and series
  precedence. Both requirements are recorded in AGENTS.md.
- The notebook uses EPSG:4326 inventory coordinates and mounted BHO 2017 5k files.
  Database execution requires interactive SqlConnector sign-in.
- Verified both metadata areas and call-time directories with temporary checks,
  using station 13710001's local inventory area (105000 km²) and a small synthetic
  network. Earlier full-BHO verification found cobacia 492599 and geographic area
  104514.93103159193 km². No permanent test files were added.
- Station lint/format checks pass. Previously noted type issues in older code
  remain outside this refactor; live SQL/notebook execution was not performed.
