"""End-to-end workflow checks using in-memory geodata and fake data providers."""

from __future__ import annotations

import json
import logging
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING

import geopandas as gpd
import matplotlib as mpl

mpl.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
import rioxarray  # noqa: F401
import xarray as xr
from scipy.optimize import OptimizeResult
from shapely.geometry import LineString, Point, box

from cn3s import CN3S, CalibrationStore, CN3SOptimizer, CN3SParams, StationCalibrationWorkflow
from cn3s.workflow import HydroDischargeSource, MergeRainSource
from hydrography import Hydrography, Stations
from hydrography.columns import HydrographyColumns

if TYPE_CHECKING:
    from pathlib import Path


class FakeRain:
    """Return dated rainfall without reading external MERGE files."""

    def __init__(self) -> None:
        """Track source calls."""
        self.calls: list[tuple[str, pd.Timestamp, pd.Timestamp]] = []

    def fetch(
        self,
        area: gpd.GeoDataFrame,
        start: pd.Timestamp,
        end: pd.Timestamp,
        frequency: str,
    ) -> pd.Series:
        """Return daily or monthly rain with the source's monthly noon time."""
        assert len(area) == 1
        self.calls.append((frequency, start, end))
        if frequency == "D":
            index = pd.date_range(start, end, freq="D")
        else:
            index = pd.date_range(start, end, freq="MS") + pd.Timedelta(hours=12)
        return pd.Series([50.0 + i % 12 for i in range(len(index))], index=index, name="prec")


class FakeDischarge:
    """Return a varying daily Hydro discharge series."""

    def __init__(self) -> None:
        """Track source calls."""
        self.calls: list[int] = []
        self.offset = 0.0

    def fetch(self, station_code: int) -> pd.Series:
        """Return daily values suitable for monthly averaging."""
        self.calls.append(station_code)
        index = pd.date_range("2000-01-01", "2001-12-31", freq="D")
        return pd.Series(
            [100.0 + i % 30 + self.offset for i in range(len(index))],
            index=index,
            name="Vazao",
        )


def test_merge_source_uses_installed_downloader_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fetch daily rain with the current downloader constructor and cube shape."""
    modules = {
        name: ModuleType(name)
        for name in (
            "mergedownloader",
            "mergedownloader.downloader",
            "mergedownloader.file_downloader",
            "mergedownloader.inpeparser",
            "mergedownloader.utils",
        )
    }
    settings: dict[str, object] = {}
    calls: list[pd.Timestamp] = []

    class FakeFileDownloader:
        def __init__(self, *, download_mode: str, log_level: int) -> None:
            settings.update(download_mode=download_mode, log_level=log_level)

    class FakeDownloader:
        def __init__(
            self, *, file_downloader: object, local_folder: str, parsers: object, log_level: int
        ) -> None:
            settings.update(
                folder=local_folder,
                parsers=parsers,
                file_downloader=file_downloader,
                downloader_log_level=log_level,
            )

        def open_file(self, date: pd.Timestamp, datatype: str) -> xr.DataArray:
            settings.update(datatype=datatype)
            calls.append(date)
            return xr.DataArray(
                [[1.0, 3.0], [1.0, 3.0]],
                dims=("latitude", "longitude"),
                coords={"latitude": [0.0, 1.0], "longitude": [0.0, 1.0]},
                name="rdp" if datatype == "daily" else "pacum",
            ).rio.write_crs("EPSG:4674")

    modules["mergedownloader.downloader"].Downloader = FakeDownloader  # type: ignore[attr-defined]
    modules["mergedownloader.file_downloader"].FileDownloader = FakeFileDownloader  # type: ignore[attr-defined]
    modules["mergedownloader.file_downloader"].DownloadMode = SimpleNamespace(NO_UPDATE="no")  # type: ignore[attr-defined]
    modules["mergedownloader.inpeparser"].InpeParsers = {}  # type: ignore[attr-defined]
    modules["mergedownloader.inpeparser"].InpeTypes = SimpleNamespace(  # type: ignore[attr-defined]
        DAILY_RAIN="daily", MONTHLY_ACCUM_YEARLY="monthly"
    )

    def cut_cube_by_geoms(cube: xr.DataArray, geometry: gpd.GeoSeries) -> xr.DataArray:
        assert len(geometry) == 1
        return cube

    modules["mergedownloader.utils"].GISUtil = SimpleNamespace(  # type: ignore[attr-defined]
        cut_cube_by_geoms=cut_cube_by_geoms
    )
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    area = gpd.GeoDataFrame(geometry=[box(0, 0, 1, 1)], crs="EPSG:4674")
    source = MergeRainSource(tmp_path / "cache")
    start = pd.Timestamp("2021-01-01")
    end = pd.Timestamp("2021-01-08")
    result = source.fetch(area, start, end, "D")
    assert len(result) == len(pd.date_range(start, end, freq="D"))
    assert result.eq(2.0).all()
    assert calls == list(pd.date_range(start, end, freq="D"))
    assert settings["download_mode"] == "no"
    assert settings["log_level"] == logging.WARNING
    assert settings["datatype"] == "daily"
    assert (tmp_path / "cache").is_dir()
    monthly_start = pd.Timestamp("2021-01-01")
    monthly_end = pd.Timestamp("2021-03-01")
    monthly = source.fetch(area, monthly_start, monthly_end, "M")
    assert monthly.index.equals(pd.date_range(monthly_start, monthly_end, freq="MS"))
    assert monthly.eq(2.0).all()
    assert settings["datatype"] == "monthly"


@pytest.fixture
def workflow(tmp_path: Path) -> tuple[StationCalibrationWorkflow, FakeRain, FakeDischarge]:
    """Create a two-station basin and a separate river station."""
    hydro = Hydrography.__new__(Hydrography)
    hydro.cols = HydrographyColumns()
    hydro.reaches = gpd.GeoDataFrame(
        {
            "cobacia": ["120", "121", "130"],
            "cocursodag": ["12", "12", "13"],
            "dsversao": ["v1", "v1", "v1"],
        },
        geometry=[LineString([(i, 0), (i, 1)]) for i in range(3)],
        crs="EPSG:4674",
    )
    hydro.watersheds = gpd.GeoDataFrame(
        {
            "cobacia": ["120", "121", "130", "122"],
            "dsversao": ["v1", "v1", "v1", "v2"],
            "nuareacont": [1.25, 2.75, 3.0, 100.0],
        },
        geometry=[*[box(i, 0, i + 1, 1) for i in range(3)], box(100, 0, 101, 1)],
        crs="EPSG:4674",
    )
    station_frame = gpd.GeoDataFrame(
        {
            "CÓDIGO": [101, 102, 103],
            "cobacia": ["120", "121", "130"],
            "AreaDrenagem": [99.0, 88.0, 77.0],
            "RIO": ["RIO DOCE", "RIO DOCE", "OTHER"],
        },
        geometry=gpd.GeoSeries([Point(0, 0), Point(1, 1), Point(2, 2)], crs="EPSG:4674"),
    )
    stations_path = tmp_path / "stations.parquet"
    station_frame.to_parquet(stations_path)
    rain, discharge = FakeRain(), FakeDischarge()
    result = StationCalibrationWorkflow(
        Stations(stations_path, hydro),
        data_root=tmp_path,
        rain_source=rain,
        discharge_source=discharge,
    )
    return result, rain, discharge


def test_prepare_both_frequencies_and_reuse_saved_data(
    workflow: tuple[StationCalibrationWorkflow, FakeRain, FakeDischarge],
) -> None:
    """Store both area estimates, normalize dates, and reuse exact-window assets."""
    service, rain_source, discharge_source = workflow
    metadata = service.prepare_station(101, "2000-01-01", "2001-12-31", ("D", "M"))
    expected_reported_area = 99.0
    expected_summed_area = 4.0
    expected_source_calls = 3
    expected_daily_days = 731
    assert metadata["area_station_km2"] == expected_reported_area
    assert metadata["area_nuareacont_km2"] == expected_summed_area
    assert metadata["network_version"] == "v1"
    assert len(rain_source.calls) == expected_source_calls  # two daily years plus monthly
    assert discharge_source.calls == [101]
    folder = service.station_dir(101)
    assert gpd.read_parquet(folder / "watershed.parquet").geometry.iloc[0].equals(box(0, 0, 2, 1))

    daily_prec, daily_q, _ = service.load_station(101, "D")
    monthly_prec, monthly_q, _ = service.load_station(101, "M")
    assert len(daily_prec) == expected_daily_days
    assert daily_prec.index[0] == pd.Timestamp("2000-01-01")
    assert monthly_prec.index[0] == pd.Timestamp("2000-01-01")
    assert monthly_prec.index[-1] == pd.Timestamp("2001-12-01")
    assert monthly_q.loc["2000-01-01"] == pytest.approx(daily_q.loc["2000-01"].mean())

    service.prepare_station(101, "2000-01-01", "2001-12-31", ("D", "M"))
    assert len(rain_source.calls) == expected_source_calls
    assert discharge_source.calls == [101]
    with pytest.raises(ValueError, match="different date window"):
        service.prepare_station(101, "2000-02-01", "2001-12-31", ("M",))


def test_monthly_preparation_includes_partial_boundary_months(
    workflow: tuple[StationCalibrationWorkflow, FakeRain, FakeDischarge],
) -> None:
    """A date window beginning mid-month still includes that month's MERGE total."""
    service, rain_source, _ = workflow
    service.prepare_station(102, "2000-01-15", "2000-03-10", ("M",))
    rain, _, _ = service.load_station(102, "M")
    assert list(rain.index) == list(pd.date_range("2000-01-01", "2000-03-01", freq="MS"))
    assert rain_source.calls[0][1] == pd.Timestamp("2000-01-01")


def test_daily_preparation_does_not_request_outside_selected_dates(
    workflow: tuple[StationCalibrationWorkflow, FakeRain, FakeDischarge],
) -> None:
    """Partial years stay within the selected interval."""
    service, rain_source, _ = workflow
    service.prepare_station(102, "2000-01-15", "2000-03-10", ("D",))
    rain, _, _ = service.load_station(102, "D")
    assert rain_source.calls[0] == (
        "D",
        pd.Timestamp("2000-01-15"),
        pd.Timestamp("2000-03-10"),
    )
    assert rain.index[0] == pd.Timestamp("2000-01-15")
    assert rain.index[-1] == pd.Timestamp("2000-03-10")


def test_missing_rain_step_is_rejected(
    workflow: tuple[StationCalibrationWorkflow, FakeRain, FakeDischarge],
) -> None:
    """CN3S must not step through an irregular rainfall series as if it were regular."""
    service, _, _ = workflow
    service.prepare_station(102, "2000-01-15", "2000-03-10", ("D",))
    file_path = service.station_dir(102) / "rain" / "daily" / "2000.parquet"
    pd.read_parquet(file_path).iloc[1:].to_parquet(file_path)
    with pytest.raises(ValueError, match="every requested time step"):
        service.load_station(102, "D")


def test_refresh_of_daily_discharge_updates_saved_monthly_mean(
    workflow: tuple[StationCalibrationWorkflow, FakeRain, FakeDischarge],
) -> None:
    """Monthly Hydro data cannot remain stale after a daily source refresh."""
    service, _, discharge_source = workflow
    service.prepare_station(101, "2000-01-01", "2000-03-31", ("D", "M"))
    _, old_monthly, _ = service.load_station(101, "M")
    discharge_source.offset = 25.0
    service.prepare_station(101, "2000-01-01", "2000-03-31", ("D",), refresh=True)
    _, new_monthly, _ = service.load_station(101, "M")
    assert new_monthly.iloc[0] - old_monthly.iloc[0] == pytest.approx(discharge_source.offset)


def test_optimizer_train_and_test_dates_do_not_overlap() -> None:
    """The cutoff date belongs only to the held-out period."""
    index = pd.date_range("2000-01-01", periods=24, freq="MS")
    prec = pd.Series([50.0 + i for i in range(len(index))], index=index)
    q = pd.Series([100.0 + i for i in range(len(index))], index=index)
    optimizer = CN3SOptimizer(
        prec=prec,
        observed_q=q,
        model=CN3S(CN3SParams(area=4.0), freq="M"),
        train_ratio=0.8,
        objective="PlainNSE",
    )
    train = optimizer._select_subset(optimizer.aligned, train=True)  # noqa: SLF001
    test = optimizer._select_subset(optimizer.aligned, train=False)  # noqa: SLF001
    assert train.index.intersection(test.index).empty
    assert len(train) + len(test) == len(index)


def test_calibration_saves_final_metrics_and_map(
    workflow: tuple[StationCalibrationWorkflow, FakeRain, FakeDischarge],
) -> None:
    """Calibrate one station and leave the other basin station gray on the map."""
    service, _, _ = workflow
    service.prepare_station(101, "2000-01-01", "2001-12-31", ("M",))
    summary = service.calibrate_station(
        101,
        "M",
        optimizer_options={"maxiter": 1, "popsize": 2, "polish": False, "seed": 7},
    )
    expected_summed_area = 4.0
    assert summary["area_nuareacont_km2"] == expected_summed_area
    assert summary["objective"] == "PlainNSE"
    assert summary["status"] == "completed"
    assert summary["params"]["name"] == "Station 101"
    assert summary["train_count"] > 0
    assert summary["test_count"] > 0
    assert summary["split_date"].startswith("2001-")
    expected_max_act = 0
    assert summary["max_act"] == expected_max_act
    assert summary["params"]["act"] == 0
    assert summary["optimizer_options"] == {
        "maxiter": 1,
        "workers": 1,
        "disp": False,
        "popsize": 2,
        "polish": False,
        "seed": 7,
        "tol": 1e-4,
    }
    assert summary["test_nse"] is not None
    run_folder = CalibrationStore(service.data_root).resolve(101, "M", summary["run_id"])
    summary_path = run_folder / "summary.json"
    saved = json.loads(summary_path.read_text())
    assert saved["test_nse"] == summary["test_nse"]
    assert (run_folder / "history.parquet").exists()
    assert (run_folder / "modeled.parquet").exists()

    quality = service.quality_data("RIO DOCE", "M")
    assert quality.loc[101, "calibration_status"] == "calibrated"
    assert quality.loc[102, "calibration_status"] == "uncalibrated"
    fig, ax = plt.subplots()
    try:
        assert service.plot_quality(ax, "RIO DOCE", "M") is ax
        assert {label.get_text() for label in ax.texts} == {"101", "102"}
        expected_axes = 2
        assert len(fig.axes) == expected_axes  # map and test NSE colorbar
        fig.canvas.draw()
        gray = mpl.colors.to_rgba("gray")
        assert tuple(ax.collections[1].get_facecolors()[0]) == pytest.approx(gray)
    finally:
        plt.close(fig)

    service.prepare_station(101, "2000-01-01", "2001-12-31", ("M",), refresh=True)
    assert service.quality_data("RIO DOCE", "M").loc[101, "calibration_status"] == "uncalibrated"


def test_saved_only_workflow_reports_and_rejects_stale_fit(
    workflow: tuple[StationCalibrationWorkflow, FakeRain, FakeDischarge],
) -> None:
    """Saved preparation and fit are readable without Stations or providers."""
    service, _, _ = workflow
    service.prepare_station(101, "2000-01-01", "2001-12-31", ("M",))
    offline = StationCalibrationWorkflow.from_prepared(service.data_root)
    assert offline.stations is None
    assert offline.rain_source is None
    assert offline.discharge_source is None
    report = offline.preparation_report(101, "M")
    expected_months = 24
    assert report.loc["rain_steps", "value"] == expected_months
    assert report.loc["paired_steps", "value"] == expected_months
    with pytest.raises(RuntimeError, match="Preparation requires"):
        offline.prepare_station(101, "2000-01-01", "2001-12-31", ("M",))
    with pytest.raises(ValueError, match="max_act must be 0"):
        offline.calibrate_station(101, "M", max_act=3)
    summary = offline.calibrate_station(
        101, "M", optimizer_options={"maxiter": 1, "popsize": 2, "polish": False}
    )
    assert offline.calibration_summary(101, "M") == summary
    assert offline.calibration_settings(101, "M").loc["max_act", "value"] == 0
    assert offline.calibration_parameters(101, "M").loc["act", "fitted value"] == 0
    assert len(offline.calibration_quality(101, "M")) == len(("training", "held-out test"))
    fig = offline.calibration_figure(101, "M")
    try:
        fig.canvas.draw()
        ax = fig.axes[0]
        split_x = float(ax.lines[-1].get_xdata()[0])
        left, right = ax.get_xlim()
        assert left < split_x < right
    finally:
        plt.close(fig)
    service.prepare_station(101, "2000-01-01", "2001-12-31", ("M",), refresh=True)
    with pytest.raises(ValueError, match="stale"):
        offline.calibration_summary(101, "M")


def test_hydro_adapter_borrows_client() -> None:
    """The adapter uses the supplied client and leaves its lifecycle to the caller."""

    class FakeHydrology:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str]] = []

        def get_discharge(self, station: int, kind: str) -> pd.DataFrame:
            self.calls.append((station, kind))
            return pd.DataFrame({"Vazao": [3.0]}, index=pd.to_datetime(["2000-01-01"]))

    client = FakeHydrology()
    result = HydroDischargeSource(client).fetch(101)  # type: ignore[arg-type]
    assert client.calls == [(101, "vazao")]
    assert result.iloc[0] == pytest.approx(3.0)


def test_monthly_model_rejects_nonzero_act() -> None:
    """A daily concentration time cannot shift monthly dates."""
    model = CN3S(CN3SParams(area=4.0, act=1), freq="M")
    rain = pd.Series([50.0] * 4, index=pd.date_range("2000-01-01", periods=4, freq="MS"))
    with pytest.raises(ValueError, match="requires act=0"):
        model.run(rain, pbar=False)


def test_daily_model_keeps_act_shift() -> None:
    """Daily simulations still apply concentration time in days."""
    model = CN3S(CN3SParams(area=4.0, act=1), freq="D")
    rain = pd.Series([50.0] * 5, index=pd.date_range("2000-01-01", periods=5, freq="D"))
    model.run(rain, pbar=False)
    assert model.results.index[0] == pd.Timestamp("2000-01-05")


def test_multiple_runs_interruption_and_failure_preserve_selection(
    workflow: tuple[StationCalibrationWorkflow, FakeRain, FakeDischarge],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workflow failures and callback recovery never replace the last complete fit."""
    service, _, _ = workflow
    service.prepare_station(101, "2000-01-01", "2001-12-31", ("M",))
    options = {"maxiter": 1, "popsize": 2, "polish": False}
    first = service.calibrate_station(101, "M", optimizer_options=options, progress=False)
    store = CalibrationStore(service.data_root)
    store.select(101, "M", first["run_id"])
    second = service.calibrate_station(101, "M", optimizer_options=options, progress=False)
    assert first["run_id"] != second["run_id"]
    assert store.resolve(101, "M", "selected").name == first["run_id"]

    def interrupted(**kwargs: object) -> OptimizeResult:
        callback = kwargs["callback"]
        vector = np.asarray(CN3SParams().as_list()[:-1])
        callback(OptimizeResult(x=vector, fun=1.0, nfev=10))
        raise KeyboardInterrupt

    monkeypatch.setattr("cn3s.optim.differential_evolution", interrupted)
    recovered = service.calibrate_station(101, "M", optimizer_options=options, progress=False)
    assert recovered["status"] == "interrupted"
    assert store.resolve(101, "M").name == second["run_id"]
    assert store.load(101, "M", recovered["run_id"])[0]["status"] == "interrupted"
    recovery = json.loads(store.attempt_path(101, "M", recovered["run_id"]).read_text())
    assert recovery["generation"] == 1
    assert recovery["best_params"][-1] == 0

    def failed(**_: object) -> OptimizeResult:
        msg = "Synthetic solver failure"
        raise RuntimeError(msg)

    monkeypatch.setattr("cn3s.optim.differential_evolution", failed)
    with pytest.raises(RuntimeError, match="Synthetic solver failure"):
        service.calibrate_station(101, "M", optimizer_options=options, progress=False)
    assert store.resolve(101, "M").name == second["run_id"]
    assert store.list_attempts(101, "M").iloc[-1]["status"] == "failed"
