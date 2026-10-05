# Development notebooks

Edit the single configuration cell in each notebook and run from a fresh kernel.

1. [01-basin-overview.ipynb](01-basin-overview.ipynb) shows basin geometry, stations
   and their Otto assignments.
2. [02-data-preparation.ipynb](02-data-preparation.ipynb) constructs the external
   clients and saves rainfall/discharge inputs. Azure sign-in and MERGE downloads
   may be needed for missing or refreshed inputs.
3. [03-calibration.ipynb](03-calibration.ipynb) fits once from saved inputs. Each fit
   receives a unique run ID and immutable input snapshots. Progress reports evolution,
   optional budgeted polishing, final simulation, scoring and artifact writes.
4. [04-evaluation.ipynb](04-evaluation.ipynb) opens a saved calibration offline,
   displays metrics and diagnostic plots, and provides a parameter playground.

The preparation, calibration and evaluation examples currently use station 56610000
at daily frequency. Change station/frequency in the configuration to inspect another
prepared run. Monthly ACT must be zero. `run_id="latest"` resolves the newest complete
calibration (or the existing legacy fit); copy an ID from the run table to pin it.

In notebook 04, edit parameter fields and press **Run simulation**. This runs one
simulation, not calibration, then compares the trial against the saved reference on
common dates. **Reset to saved** discards the trial. Enter a label and press **Save
experiment** to save a manual child run; this does not move the latest or selected
calibration. Trial edits do not change the saved reference. Daily simulations can
still take several seconds; numerical-kernel optimization belongs to a later phase.

Install notebook dependencies with `pip install -e ".[notebook]"`. The plain Python
`ModelPlayground.run({...})` API also works without widgets. Widget callbacks require
an active Python kernel and a frontend with ipywidgets support. The saved notebook
contains evaluation outputs; rerun it to activate the controls.

Use `CalibrationStore.select(station_code, frequency, run_id)` to explicitly select a
completed calibration. Quality maps use selected when present, otherwise latest, and
require the current input revision. Historical evaluation uses its own snapshots;
a stale legacy fit can be inspected but cannot be replayed with mismatched inputs.

The original notebook 03, including its two calibration calls and outputs, is
preserved in [Group 1](../../agents/iterations/2026-09-30-evaluation-and-forecast-roadmap/group-1/03-calibration-before-group1.ipynb).
Other historical notebooks remain in their original iteration folders. Notebook
implementation rules are in [AGENTS.md](../../AGENTS.md).

5. [05-hydro-station.ipynb](05-hydro-station.ipynb) reads station inventory and
   historical/telemetric daily observations directly from `syndb_hidro` using one
   shared SQL connector. It shows raw/validated historical records, available
   sources, merged discharge and stage, and a time-series plot. Configure the station
   and date window, then authenticate with Azure when prompted. It needs the
   `workflow` extra and ODBC Driver 18. Statistics and report generation are deferred.
