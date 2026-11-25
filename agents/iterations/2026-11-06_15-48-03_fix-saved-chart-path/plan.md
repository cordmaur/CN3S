# Fix duplicated station directory when loading charts

## Plan

- Trace the web chart handler and saved-result loader.
- Keep one explicit path contract: from_saved receives the exact station directory.
- Fix affected callers and verify saved-file loading without accessing live SQL.

## Session record

- web.permanencia.load_chart already passes results_root() / str(code).
- ExceedanceAnalysis.from_saved appended the code again despite documenting an exact directory, producing Exceedance/18700000/18700000/metadata.json.
- Removed the extra path component and clarified the docstring. ExceedanceResult.load already converts string paths to Path.
- Updated the notebook's final from_saved example to pass RESULTS_DIR / str(station.code). Its earlier call and the web handler already use exact station directories.
- A temporary save/load check wrote actual metadata and Parquet files, then loaded through from_saved with both Path and string arguments. Both passed and retained the supplied station and saved data. Temporary files were removed automatically.
- Full Ruff lint and formatting checks passed for src/hydro/exceedance.py. Notebook JSON validation passed.
- No live database, deployed web server, or production result files were accessed. Existing unrelated edits were preserved.

## Method-call example

```python
analysis = ExceedanceAnalysis.from_saved(
    Path('/data/CN3S/Exceedance') / str(station.code), station
)
```
