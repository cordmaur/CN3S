"""Prepare station data, calibrate CN3S, and map calibration quality."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast
from uuid import uuid4

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import colormaps  # type: ignore[attr-defined]
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.dates import date2num

from cn3s.artifacts import CalibrationStore, read_json, write_json
from cn3s.model import CN3S, CN3SParams
from cn3s.optim import CN3SOptimizer

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    import geopandas as gpd
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

    from cn3s.objectives import Objective
    from hydrography import Stations
    from utils.hydrology import Hydrology

Frequency = Literal["D", "M"]
logger = logging.getLogger(__name__)


class RainSource(Protocol):
    """Provide mean areal MERGE rainfall for a watershed and date range."""

    def fetch(
        self,
        area: gpd.GeoDataFrame,
        start: pd.Timestamp,
        end: pd.Timestamp,
        frequency: Frequency,
    ) -> pd.Series:
        """Return rainfall depth in millimetres indexed by date."""


class DischargeSource(Protocol):
    """Provide the daily observed discharge for a station."""

    def fetch(self, station_code: int) -> pd.Series:
        """Return daily discharge in m³/s indexed by date."""


class MergeRainSource:
    """Read MERGE rainfall through the downloader used in the notebooks."""

    def __init__(self, download_root: str | Path) -> None:
        """
        Store the shared raw-download cache location.

        Args:
            download_root: Folder for cached MERGE source files.

        """
        self.download_root = Path(download_root)
        self._downloader: Any = None

    def fetch(
        self,
        area: gpd.GeoDataFrame,
        start: pd.Timestamp,
        end: pd.Timestamp,
        frequency: Frequency,
    ) -> pd.Series:
        """
        Clip a MERGE cube to the watershed and average its grid cells.

        Args:
            area: Dissolved watershed polygon.
            start: Inclusive first source date.
            end: Inclusive last source date.
            frequency: Daily or monthly rainfall source.

        Returns:
            Mean areal precipitation as a dated series.

        """
        try:
            from mergedownloader.downloader import Downloader  # noqa: PLC0415
            from mergedownloader.file_downloader import (  # noqa: PLC0415
                DownloadMode,
                FileDownloader,
            )
            from mergedownloader.inpeparser import (  # noqa: PLC0415
                InpeParsers,
                InpeTypes,
            )
            from mergedownloader.utils import GISUtil  # noqa: PLC0415
        except ImportError as exc:
            msg = "MERGE rainfall requires merge-downloader; see .devcontainer/devcontainer.json"
            raise ImportError(msg) from exc

        if self._downloader is None:
            self.download_root.mkdir(parents=True, exist_ok=True)
            file_downloader = FileDownloader(
                download_mode=DownloadMode.NO_UPDATE,
                log_level=logging.WARNING,
            )
            self._downloader = Downloader(
                file_downloader=file_downloader,
                local_folder=str(self.download_root),
                parsers=InpeParsers,
                log_level=logging.WARNING,
            )

        dates = pd.date_range(start, end, freq="D" if frequency == "D" else "MS")
        datatype = InpeTypes.DAILY_RAIN if frequency == "D" else InpeTypes.MONTHLY_ACCUM_YEARLY
        expected_name = "rdp" if frequency == "D" else "pacum"
        values: list[float] = []
        minx, miny, maxx, maxy = area.total_bounds
        for date in dates:
            source = self._downloader.open_file(date, datatype)
            if source is None or source.name != expected_name:
                msg = f"MERGE {frequency} rainfall is missing on {date.date()}"
                raise ValueError(msg)
            window = source.rio.clip_box(minx, miny, maxx, maxy, crs=area.crs)
            clipped = GISUtil.cut_cube_by_geoms(window, area.geometry)
            values.append(float(clipped.mean(dim=["latitude", "longitude"]).item()))
            del source, window, clipped
            cached_open = getattr(self._downloader, "_open_file_cached", None)
            cache_clear = getattr(cached_open, "cache_clear", None)
            if cache_clear is not None:
                cache_clear()
        return pd.Series(values, index=dates, name="prec")


class HydroDischargeSource:
    """Read daily Vazao through the existing Hydro client."""

    def __init__(self, hydrology: Hydrology) -> None:
        """Borrow an externally owned client without managing its connection."""
        self.hydrology = hydrology

    def fetch(self, station_code: int) -> pd.Series:
        """
        Fetch the complete daily discharge record for a station.

        Args:
            station_code: Hydro station identifier.

        Returns:
            Daily observed discharge in m³/s.

        """
        frame = self.hydrology.get_discharge(station_code, "vazao")
        return cast("pd.Series", frame["Vazao"].rename("Vazao"))


class StationCalibrationWorkflow:
    """Manage station assets and compose the existing CN3S optimizer."""

    def __init__(
        self,
        stations: Stations | None,
        data_root: str | Path = "/data/CN3S",
        *,
        rain_source: RainSource | None = None,
        discharge_source: DischargeSource | None = None,
    ) -> None:
        """
        Set locations and providers without contacting external services.

        Args:
            stations: In-memory stations and Hydrography network.
            data_root: Parent for station folders and shared MERGE downloads.
            rain_source: Optional rainfall provider for alternate sources or tests.
            discharge_source: Optional daily discharge provider for tests.

        """
        self.stations = stations
        self.data_root = Path(data_root)
        self.rain_source = rain_source or (
            MergeRainSource(self.data_root / "downloads") if stations is not None else None
        )
        self.discharge_source = discharge_source

    @classmethod
    def from_prepared(cls, data_root: str | Path = "/data/CN3S") -> StationCalibrationWorkflow:
        """Create an offline workflow that reads only persisted station assets."""
        return cls(None, data_root=data_root)

    def station_dir(self, station_code: str | int) -> Path:
        """
        Return the stable station folder without creating it.

        Args:
            station_code: Station identifier.

        Returns:
            Path beneath the configured data root.

        """
        code = str(station_code)
        if not code.isdecimal():
            msg = f"Station code must contain only digits: {code!r}"
            raise ValueError(msg)
        return self.data_root / "stations" / code

    def _station_row(self, station_code: str | int) -> pd.Series:
        """Find exactly one station row by code."""
        if self.stations is None:
            msg = "Station selection requires Stations; use a preparation workflow"
            raise RuntimeError(msg)
        matching = self.stations.stations.loc[
            self.stations.stations.index.astype(str) == str(station_code)
        ]
        if len(matching) != 1:
            msg = f"Station code {station_code} must identify exactly one station"
            raise ValueError(msg)
        return cast("pd.Series", matching.iloc[0])

    def station_details(self, station_code: str | int) -> pd.DataFrame:
        """Return station identity and verify its watershed assignment."""
        row = self._station_row(station_code)
        if row.get("assignment_status") != "assigned":
            msg = f"Station {station_code} has no unique watershed assignment"
            raise ValueError(msg)
        fields = ("ESTCODIGO", "ESTNOME", "cobacia", "dsversao", "assignment_status")
        return row[[field for field in fields if field in row.index]].to_frame("value")

    @staticmethod
    def _dates(
        start: str | pd.Timestamp, end: str | pd.Timestamp
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        """Normalize and validate an inclusive date window."""
        first, last = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
        if pd.isna(first) or pd.isna(last) or first > last:
            msg = "start and end must be valid dates with start <= end"
            raise ValueError(msg)
        return first, last

    @staticmethod
    def _frequencies(frequencies: Iterable[Frequency]) -> tuple[Frequency, ...]:
        """Validate an explicit non-empty set of frequencies."""
        values = tuple(dict.fromkeys(frequencies))
        if not values or any(value not in ("D", "M") for value in values):
            msg = "frequencies must contain D, M, or both"
            raise ValueError(msg)
        return values

    @staticmethod
    def _normalize_series(series: pd.Series, frequency: Frequency, name: str) -> pd.Series:
        """Sort a dated series and put daily or monthly dates on canonical boundaries."""
        if not isinstance(series.index, pd.DatetimeIndex):
            msg = f"{name} must have a DatetimeIndex"
            raise TypeError(msg)
        clean = series.astype(float).copy()
        index = cast("pd.DatetimeIndex", clean.index)
        clean.index = index.normalize() if frequency == "D" else index.to_period("M").to_timestamp()
        clean = clean.sort_index()
        if clean.index.has_duplicates:
            msg = f"{name} contains duplicate {frequency} dates"
            raise ValueError(msg)
        clean.name = name
        return clean

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, Any]:
        """Read existing station metadata, if any."""
        return cast("dict[str, Any]", json.loads(path.read_text())) if path.exists() else {}

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        """Write human-readable JSON, rejecting non-finite numeric values."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")

    def prepare_station(  # noqa: PLR0912, PLR0915
        self,
        station_code: str | int,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        frequencies: Iterable[Frequency],
        *,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """
        Build the watershed and save requested rain and discharge inputs.

        Args:
            station_code: Station to prepare.
            start: Inclusive first rainfall date.
            end: Inclusive last rainfall date.
            frequencies: Explicit daily and/or monthly selection.
            refresh: Replace existing assets for requested frequencies.

        Returns:
            Station metadata, including both reported and summed watershed areas.

        """
        if self.stations is None:
            msg = "Preparation requires Stations and Hydrography"
            raise RuntimeError(msg)
        if self.rain_source is None or self.discharge_source is None:
            msg = "Preparation requires explicit rain and discharge sources"
            raise RuntimeError(msg)
        first, last = self._dates(start, end)
        requested = self._frequencies(frequencies)
        row = self._station_row(station_code)
        code = str(station_code)
        cobacia, _, version = self.stations._resolve_target(None, station_code)  # noqa: SLF001
        folder = self.station_dir(code)
        metadata_path = folder / "metadata.json"
        metadata = self._read_metadata(metadata_path)
        network_changed = bool(metadata) and (
            metadata.get("cobacia"),
            metadata.get("network_version"),
        ) != (cobacia, version)
        if network_changed and not refresh:
            msg = "Watershed network changed; run prepare_station with refresh=True"
            raise ValueError(msg)

        periods = cast("dict[str, dict[str, str]]", metadata.get("rain_periods", {}))
        if network_changed:
            periods = {}
        date_record = {"start": first.date().isoformat(), "end": last.date().isoformat()}
        for frequency in requested:
            if frequency in periods and periods[frequency] != date_record and not refresh:
                msg = f"{frequency} rainfall has a different date window; use refresh=True"
                raise ValueError(msg)

        area = self.stations.create_upstream(station_code=station_code)
        summed_area = float(area["area_nuareacont_km2"].iloc[0])
        area_changed = bool(metadata) and not math.isclose(
            summed_area,
            float(metadata.get("area_nuareacont_km2", 0.0)),
        )
        if area_changed and not refresh:
            msg = "Watershed area changed; run prepare_station with refresh=True"
            raise ValueError(msg)
        if area_changed:
            periods = {}
        reported = row.get("AreaDrenagem")
        reported_area = None if pd.isna(reported) else float(reported)
        folder.mkdir(parents=True, exist_ok=True)
        watershed_path = folder / "watershed.parquet"
        if refresh or not watershed_path.exists():
            area.to_parquet(watershed_path)

        for frequency in requested:
            if frequency == "D":
                annual = folder / "rain" / "daily"
                annual.mkdir(parents=True, exist_ok=True)
                for year in range(first.year, last.year + 1):
                    year_path = annual / f"{year}.parquet"
                    if refresh or frequency not in periods or not year_path.exists():
                        year_start = max(first, pd.Timestamp(year=year, month=1, day=1))
                        year_end = min(last, pd.Timestamp(year=year, month=12, day=31))
                        rain = self.rain_source.fetch(area, year_start, year_end, "D")
                        rain = self._normalize_series(rain, "D", "prec")
                        rain.to_frame().to_parquet(year_path)
            else:
                monthly_path = folder / "rain" / "monthly.parquet"
                if refresh or frequency not in periods or not monthly_path.exists():
                    monthly_path.parent.mkdir(parents=True, exist_ok=True)
                    month_start = first.to_period("M").to_timestamp()
                    month_end = last.to_period("M").to_timestamp()
                    rain = self.rain_source.fetch(area, month_start, month_end, "M")
                    rain = self._normalize_series(rain, "M", "prec")
                    rain.to_frame().to_parquet(monthly_path)
            periods[frequency] = date_record

        daily_path = folder / "discharge" / "daily.parquet"
        if refresh or not daily_path.exists():
            daily_path.parent.mkdir(parents=True, exist_ok=True)
            discharge = self.discharge_source.fetch(int(code))
            discharge = self._normalize_series(discharge, "D", "Vazao")
            discharge.to_frame().to_parquet(daily_path)
        else:
            discharge = pd.read_parquet(daily_path)["Vazao"]
        monthly_q_path = folder / "discharge" / "monthly.parquet"
        if ("M" in requested or monthly_q_path.exists()) and (
            refresh or not monthly_q_path.exists()
        ):
            discharge.resample("MS").mean().to_frame("Vazao").to_parquet(monthly_q_path)

        revisions = cast("dict[str, str]", metadata.get("input_revisions", {}))
        if refresh:
            revisions = {frequency: uuid4().hex for frequency in periods}
        for frequency in requested:
            revisions.setdefault(frequency, uuid4().hex)

        metadata.update(
            {
                "station_code": code,
                "cobacia": cobacia,
                "network_version": version,
                "area_station_km2": reported_area,
                "area_nuareacont_km2": summed_area,
                "rain_periods": periods,
                "input_revisions": revisions,
                "rain_source": "MERGE",
                "discharge_source": "Hydro Vazao",
            }
        )
        self._write_json(metadata_path, metadata)
        return metadata

    def load_station(
        self, station_code: str | int, frequency: Frequency
    ) -> tuple[pd.Series, pd.Series, dict[str, Any]]:
        """
        Read prepared rainfall, discharge, and station metadata.

        Args:
            station_code: Prepared station identifier.
            frequency: Daily or monthly data to load.

        Returns:
            Rainfall, discharge, and metadata.

        """
        if frequency not in ("D", "M"):
            msg = "frequency must be D or M"
            raise ValueError(msg)
        folder = self.station_dir(station_code)
        metadata = self._read_metadata(folder / "metadata.json")
        period = metadata.get("rain_periods", {}).get(frequency)
        if period is None:
            msg = f"Station {station_code} has no prepared {frequency} rainfall"
            raise ValueError(msg)
        first, last = self._dates(period["start"], period["end"])
        if frequency == "D":
            frames = [
                pd.read_parquet(folder / "rain" / "daily" / f"{year}.parquet")
                for year in range(first.year, last.year + 1)
            ]
            rain = pd.concat(frames)["prec"]
        else:
            rain = pd.read_parquet(folder / "rain" / "monthly.parquet")["prec"]
            first, last = first.to_period("M").to_timestamp(), last.to_period("M").to_timestamp()
        rain = self._normalize_series(rain.loc[first:last], frequency, "prec")
        if rain.empty or rain.isna().any():
            msg = f"Prepared {frequency} rainfall is empty or contains missing values"
            raise ValueError(msg)
        expected = pd.date_range(first, last, freq="D" if frequency == "D" else "MS")
        if not rain.index.equals(expected):
            msg = f"Prepared {frequency} rainfall does not cover every requested time step"
            raise ValueError(msg)
        q_path = folder / "discharge" / ("daily.parquet" if frequency == "D" else "monthly.parquet")
        discharge = self._normalize_series(pd.read_parquet(q_path)["Vazao"], frequency, "Vazao")
        return rain, discharge, metadata

    def preparation_report(self, station_code: str | int, frequency: Frequency) -> pd.DataFrame:
        """Validate saved inputs and summarize their coverage for one station."""
        rain, discharge, metadata = self.load_station(station_code, frequency)
        observed = discharge.reindex(rain.index)
        paired = observed.notna() & rain.notna()
        return pd.DataFrame(
            {
                "value": [
                    str(station_code),
                    frequency,
                    metadata["rain_periods"][frequency]["start"],
                    metadata["rain_periods"][frequency]["end"],
                    len(rain),
                    int(observed.notna().sum()),
                    int(paired.sum()),
                    metadata["area_nuareacont_km2"],
                    str(self.station_dir(station_code)),
                ]
            },
            index=[
                "station_code",
                "frequency",
                "start",
                "end",
                "rain_steps",
                "observed_steps",
                "paired_steps",
                "upstream_area_km2",
                "saved_in",
            ],
        )

    def calibration_summary(
        self, station_code: str | int, frequency: Frequency, run_id: str | None = None
    ) -> dict[str, Any]:
        """Read a saved run; latest-only compatibility calls reject stale inputs."""
        summary, _, _, _ = CalibrationStore(self.data_root).load(
            station_code,
            frequency,
            run_id or "latest",
        )
        if run_id is None:
            metadata = self._read_metadata(self.station_dir(station_code) / "metadata.json")
            current = metadata.get("input_revisions", {}).get(frequency)
            if not current or summary.get("input_revision") != current:
                msg = f"Saved {frequency} calibration is stale for station {station_code}"
                raise ValueError(msg)
        return summary

    def calibration_settings(self, station_code: str | int, frequency: Frequency) -> pd.DataFrame:
        """Return the saved fit settings as a notebook-ready table."""
        summary = self.calibration_summary(station_code, frequency)
        fields = (
            "station_code",
            "frequency",
            "objective",
            "rain_period",
            "train_ratio",
            "warmup_steps",
            "max_act",
            "optimizer_options",
            "converged",
            "split_date",
            "train_count",
            "test_count",
        )
        table = pd.Series({key: summary[key] for key in fields}, name="value").to_frame()
        return cast("pd.DataFrame", table)

    def calibration_parameters(self, station_code: str | int, frequency: Frequency) -> pd.DataFrame:
        """Return fitted model parameters from the saved summary."""
        summary = self.calibration_summary(station_code, frequency)
        return cast("pd.DataFrame", pd.Series(summary["params"], name="fitted value").to_frame())

    def calibration_quality(self, station_code: str | int, frequency: Frequency) -> pd.DataFrame:
        """Return saved training and held-out NSE with sample counts."""
        summary = self.calibration_summary(station_code, frequency)
        return pd.DataFrame(
            {
                "period": ["training", "held-out test"],
                "paired_steps": [summary["train_count"], summary["test_count"]],
                "NSE": [summary["train_nse"], summary["test_nse"]],
            }
        )

    def calibration_figure(self, station_code: str | int, frequency: Frequency) -> Figure:
        """Plot persisted observed and simulated flow with the split date."""
        summary = self.calibration_summary(station_code, frequency)
        _, modeled, _, output = CalibrationStore(self.data_root).load(station_code, frequency)
        if not {"obs_q_m3s", "q_m3s"}.issubset(modeled.columns) or modeled.empty:
            msg = f"Saved modeled discharge is incomplete in {output}"
            raise ValueError(msg)
        fig, ax = plt.subplots(figsize=(14, 5))
        ax.plot(
            modeled.index,
            modeled["obs_q_m3s"],
            label="Hydro observed",
            color="black",
            linewidth=0.9,
        )
        ax.plot(
            modeled.index, modeled["q_m3s"], label="CN3S modeled", color="tab:blue", linewidth=0.9
        )
        ax.axvline(
            date2num(pd.Timestamp(summary["split_date"])),
            color="tab:red",
            linestyle="--",
            label="train/test split",
        )
        ax.set(
            title=f"Station {station_code}: observed vs modeled {frequency} discharge",
            xlabel="Date",
            ylabel="Discharge (m³/s)",
        )
        ax.legend()
        fig.tight_layout()
        return fig

    @staticmethod
    def _finite_or_none(value: float) -> float | None:
        """Convert non-finite scores to JSON null."""
        return float(value) if math.isfinite(value) else None

    def calibrate_station(
        self,
        station_code: str | int,
        frequency: Frequency,
        *,
        warmup_steps: int = 3,
        train_ratio: float = 0.8,
        max_act: int | None = None,
        objective: str | Objective = "PlainNSE",
        optimizer_options: Mapping[str, Any] | None = None,
        label: str | None = None,
        progress: bool = True,
        polish_maxiter: int = 50,
        polish_maxfun: int = 500,
    ) -> dict[str, Any]:
        """
        Calibrate CN3S against prepared inputs and save its best result.

        Args:
            station_code: Prepared station identifier.
            frequency: Daily or monthly calibration frequency.
            warmup_steps: Antecedent precipitation steps for each model run.
            train_ratio: Chronological fraction used for parameter fitting.
            max_act: Upper bound of the ACT search in days.
            objective: Existing optimizer objective name or object.
            optimizer_options: Overrides for SciPy differential evolution.
            label: Optional human-readable run label.
            progress: Report phases and generation progress.
            polish_maxiter: Local refinement iteration budget.
            polish_maxfun: Hard limit on local refinement objective evaluations.

        Returns:
            Saved calibration summary with held-out test NSE.

        """
        rain, discharge, metadata = self.load_station(station_code, frequency)
        area_km2 = float(metadata["area_nuareacont_km2"])
        params = CN3SParams(
            name=f"Station {station_code}",
            area=area_km2,
            warmup_steps=warmup_steps,
        )
        model = CN3S(params, freq=frequency)
        effective_max_act = max_act if max_act is not None else (10 if frequency == "D" else 0)
        if frequency == "M" and effective_max_act != 0:
            msg = "Monthly calibration fixes act=0; max_act must be 0"
            raise ValueError(msg)
        optimizer = CN3SOptimizer(
            prec=rain,
            observed_q=discharge,
            model=model,
            train_ratio=train_ratio,
            max_act=effective_max_act,
            objective=objective,
        )
        options: dict[str, Any] = {
            "maxiter": 100,
            "workers": 1,
            "disp": False,
            "seed": 42,
            "tol": 1e-4,
            "popsize": 15,
            "polish": True,
        }
        options.update(optimizer_options or {})
        store = CalibrationStore(self.data_root)
        run_id = store.new_id()
        attempt_path = store.attempt_path(station_code, frequency, run_id)
        attempt = {
            "run_id": run_id,
            "station_code": str(station_code),
            "frequency": frequency,
            "status": "running",
            "label": label,
            "input_revision": metadata["input_revisions"][frequency],
            "warmup_steps": warmup_steps,
            "max_act": effective_max_act,
            "train_ratio": train_ratio,
            "objective": optimizer.objective.name,
            "optimizer_options": json.loads(json.dumps(options, default=str)),
        }
        write_json(attempt_path, attempt)
        optimizer.recovery_path = attempt_path
        try:
            optimizer.optimize(
                progress=progress,
                polish_maxiter=polish_maxiter,
                polish_maxfun=polish_maxfun,
                **options,
            )
            if optimizer.result is None:
                msg = "Calibration stopped before a completed generation; no result was saved"
                raise RuntimeError(msg)  # noqa: TRY301
            if progress:
                print("Calibration: scoring", flush=True)
            started = perf_counter()
            metrics = optimizer.evaluate_best()
            optimizer.timings["scoring"] = perf_counter() - started
            split_date = cast("pd.Timestamp", optimizer.aligned.index[optimizer.train_idx])
            paired = optimizer.model.results[["q_m3s", "obs_q_m3s"]].dropna()
            train_count = int((paired.index < split_date).sum())
            test_count = int((paired.index >= split_date).sum())
            summary: dict[str, Any] = {
                "station_code": str(station_code),
                "frequency": frequency,
                "label": label,
                "kind": "calibration",
                "objective": optimizer.objective.name,
                "objective_config": json.loads(json.dumps(vars(optimizer.objective), default=str)),
                "area_nuareacont_km2": area_km2,
                "area_station_km2": metadata.get("area_station_km2"),
                "rain_period": metadata["rain_periods"][frequency],
                "input_revision": metadata["input_revisions"][frequency],
                "train_ratio": train_ratio,
                "warmup_steps": warmup_steps,
                "max_act": effective_max_act,
                "optimizer_options": json.loads(json.dumps(options, default=str)),
                "split_date": split_date.date().isoformat(),
                "train_count": train_count,
                "test_count": test_count,
                "converged": bool(optimizer.result.success),
                "status": "interrupted" if optimizer.interrupted else "completed",
                "params": asdict(optimizer.model.params),
                "train_nse": self._finite_or_none(metrics["train_nse"]),
                "test_nse": self._finite_or_none(metrics["test_nse"]),
                "train_objective": self._finite_or_none(metrics["train_objective"]),
                "test_objective": self._finite_or_none(metrics["test_objective"]),
                "timings_seconds": optimizer.timings,
                "solver": json.loads(json.dumps(optimizer.diagnostics, default=str)),
                "formulation": "legacy-v1-30-day-month-vj100",
            }
            history = optimizer.history.drop(columns=["params"], errors="ignore").copy()
            history["phase"] = "evolution"
            final_row = {
                **asdict(optimizer.model.params),
                **metrics,
                "phase": "final",
                "step": len(history) + 1,
            }
            history = pd.concat([history, pd.DataFrame([final_row]).set_index("step")])
            if progress:
                print("Calibration: writing immutable run and input snapshots", flush=True)
            saved = store.save(
                summary, optimizer.model.results, history, rain, discharge, metadata, run_id=run_id
            )
            attempt = read_json(attempt_path)
            attempt.update(status=saved["status"], result_run_id=run_id)
            write_json(attempt_path, attempt)
            if progress:
                print(f"Calibration {saved['status']}: {run_id}", flush=True)
            return saved
        except BaseException as exc:
            attempt = read_json(attempt_path)
            attempt.update(
                status="interrupted" if optimizer.interrupted else "failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            write_json(attempt_path, attempt)
            raise

    def quality_data(self, basin: str, frequency: Frequency) -> gpd.GeoDataFrame:
        """
        Attach saved test NSE values to stations in one named river basin.

        Args:
            basin: Value from the station RIO column.
            frequency: Daily or monthly calibration frequency.

        Returns:
            Basin station GeoDataFrame with test_nse and status columns.

        """
        if self.stations is None:
            msg = "Basin quality maps require Stations"
            raise RuntimeError(msg)
        if frequency not in ("D", "M"):
            msg = "frequency must be D or M"
            raise ValueError(msg)
        if "RIO" not in self.stations.stations:
            msg = "Stations need a RIO column for basin quality maps"
            raise ValueError(msg)
        subset = self.stations.stations.loc[self.stations.stations["RIO"] == basin].copy()
        scores: list[float | None] = []
        statuses: list[str] = []
        for station_code in subset.index:
            store = CalibrationStore(self.data_root)
            pointer = (
                "selected"
                if (store.folder(station_code, frequency) / "selected.json").exists()
                else "latest"
            )
            try:
                summary, _, _, _ = store.load(station_code, frequency, pointer)
            except (OSError, ValueError, KeyError):
                summary = {}
            metadata = self._read_metadata(self.station_dir(str(station_code)) / "metadata.json")
            current_revision = metadata.get("input_revisions", {}).get(frequency)
            score = (
                summary.get("test_nse")
                if summary.get("status") == "completed"
                and summary.get("input_revision") == current_revision
                else None
            )
            scores.append(
                float(score) if score is not None and math.isfinite(float(score)) else None
            )
            statuses.append("calibrated" if scores[-1] is not None else "uncalibrated")
        subset["test_nse"] = scores
        subset["calibration_status"] = statuses
        return cast("gpd.GeoDataFrame", subset)

    def plot_quality(self, ax: Axes, basin: str, frequency: Frequency) -> Axes:
        """
        Map station test NSE, with uncalibrated stations shown in gray.

        Args:
            ax: Matplotlib axes to draw on.
            basin: Value from the station RIO column.
            frequency: Daily or monthly calibration frequency.

        Returns:
            The supplied axes.

        """
        data = self.quality_data(basin, frequency)
        if data.empty:
            msg = f"No stations found for basin {basin!r}"
            raise ValueError(msg)
        norm = Normalize(vmin=-1.0, vmax=1.0, clip=True)
        cmap = colormaps["RdYlGn"]
        calibrated = 0
        missing = 0
        for station_code, geometry in data.geometry.items():
            point = geometry.representative_point()
            score = float(cast("float", data["test_nse"].loc[station_code]))
            if math.isnan(score):
                color = "gray"
                missing += 1
            else:
                color = cmap(norm(score))
                calibrated += 1
            ax.scatter(point.x, point.y, c=[color], s=35, zorder=9)
            ax.annotate(
                str(station_code),
                (point.x, point.y),
                xytext=(3, 3),
                textcoords="offset points",
                zorder=10,
            )
        if calibrated:
            scalar = ScalarMappable(norm=norm, cmap=cmap)
            ax.figure.colorbar(scalar, ax=ax, label="Test NSE")
        if missing:
            ax.scatter([], [], c="gray", s=35, label="Not calibrated")
            ax.legend()
        ax.set_title(f"{basin} — CN3S {frequency} calibration")
        return ax
