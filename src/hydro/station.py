"""Station inventory, source-aware daily series, and per-station quality statistics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Self, TypeAlias

import pandas as pd

from .data import SeriesType, Source, SqlReader, date_predicate, empty_series, validate_series_type
from .hidro import Hidro
from .hydro_stats import HydroStats
from .telemetria import Telemetria

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from mergedownloader.downloader import Downloader

    from hydrography import Hydrography

DataSanitization: TypeAlias = dict[SeriesType, dict[str, float]]

DEFAULT_PERIOD = slice(None, None)


class Station:
    """
    Aggregate a historical station and its associated telemetric stations.

    Live construction loads inventory; from_folder reads saved context only.
    Spatial preparation and daily series loading are explicit. The caller owns
    the shared SQL connector. Historical records take precedence on overlapping days.
    """

    def __init__(
        self,
        code: int,
        sanitization: DataSanitization | None = None,
        *,
        connector: SqlReader,
    ) -> None:
        """
        Load station inventory.

        Args:
            code: Historical station code.
            sanitization: Optional observation replacements by measurement and date.
            connector: Caller-owned SQL connector.

        """
        self.code = int(code)
        self.sanitization = sanitization
        self.connector: SqlReader | None = connector
        # Both providers borrow the caller's connector; Station does not own it.
        self.hidro = Hidro(connector)
        self.telemetria = Telemetria(self.hidro.connector)
        try:
            self.info = self.hidro.get_station_info(self.code)
        except Exception:
            self.close()
            raise

    @classmethod
    def from_folder(
        cls,
        station_dir: str | Path,
        *,
        connector: SqlReader | None = None,
        sanitization: DataSanitization | None = None,
    ) -> Self:
        """
        Load saved station context without querying inventory or observations.

        Args:
            station_dir: Folder containing metadata.json and the basin GeoParquet.
            connector: Caller-owned SQL connector, needed only for live series loading.
            sanitization: Optional replacements applied when daily series are requested.

        Returns:
            Station with saved identity, both drainage areas in km², and basin CRS.
            Full inventory, daily observations, and statistics are not reconstructed.

        """
        import geopandas as gpd  # noqa: PLC0415

        # Bypass the live constructor: reading saved inputs must not require SQL.
        station = cls.__new__(cls)
        station.station_dir = Path(station_dir)
        station.metadata_path = station.station_dir / "metadata.json"
        station.upstream_watershed_path = station.station_dir / "upstream_watershed.parquet"
        with station.metadata_path.open(encoding="utf-8") as file:
            station.metadata = json.load(file)
        station.upstream_watershed = gpd.read_parquet(station.upstream_watershed_path)
        station.code = int(str(station.metadata["station_code"]))
        station.sanitization = sanitization
        station.connector = connector
        station.hidro = Hidro(connector)
        station.telemetria = Telemetria(connector)
        return station

    def get_optim_data(self, freq: str) -> pd.DataFrame:
        """
        Read optimization inputs saved for the selected frequency.

        Args:
            freq: M for Monthly or D for Daily.

        Returns:
            Rainfall-indexed inputs with prec_mm in mm and q_m3s in m³/s.
            Discharge outside the rainfall window is excluded; missing matches stay NaN.

        Raises:
            ValueError: If the frequency is neither M nor D.
            RuntimeError: If the station has no prepared folder.
            FileNotFoundError: If inputs have not been prepared for this frequency.

        """
        folders = {"M": "Monthly", "D": "Daily"}
        if freq not in folders:
            msg = "Frequency must be 'M' or 'D'."
            raise ValueError(msg)
        if not hasattr(self, "station_dir"):
            msg = "Prepare station context or use Station.from_folder() before loading inputs."
            raise RuntimeError(msg)
        folder = self.station_dir / folders[freq]
        rain = pd.read_parquet(folder / "rain.parquet")
        discharge = pd.read_parquet(folder / "discharge.parquet")
        # Keep the rainfall calendar for model stepping; missing discharge stays NaN.
        return rain.join(discharge)

    @property
    def name(self) -> str:
        """
        Return the historical station name.

        Returns:
            Name reported by the Hidro inventory or saved station metadata.

        """
        if hasattr(self, "info"):
            return str(self.info["Nome"].iloc[0])
        return str(self.metadata["station_name"])

    def prepare_station(
        self,
        hydrography: Hydrography,
        output_dir: str | Path,
    ) -> dict[str, str | float | None]:
        """
        Assign a basin and save station metadata and upstream basin GeoParquet.

        Args:
            hydrography: Loaded network accepting EPSG:4326 latitude/longitude.
            output_dir: Parent stations directory; a code-named subfolder is created.

        Returns:
            Station identity and cobacia, with drainage_area from Hidro AreaDrenagem
            and drainage_area_geo from geographic nuareamont, both in km².
            Missing inventory area is represented by None.

        """
        # Folder context omits full inventory; query it only for spatial preparation.
        if not hasattr(self, "info"):
            if self.connector is None:
                msg = "Spatial preparation requires a caller-owned SQL connector."
                raise RuntimeError(msg)
            self.info = self.hidro.get_station_info(self.code)
        # Hidro inventory coordinates use decimal degrees in EPSG:4326.
        inventory = self.info.iloc[0]
        lat = float(inventory["Latitude"])
        lon = float(inventory["Longitude"])
        cobacia = hydrography.assign_cobacia(lat, lon)
        drainage_area_geo = hydrography.drainage_area(cobacia)
        watershed = hydrography.upstream_watershed(cobacia)

        # Preserve both sources: inventory and geographic areas can differ.
        inventory_area = inventory["AreaDrenagem"]
        drainage_area = None if pd.isna(inventory_area) else float(inventory_area)
        metadata: dict[str, str | float | None] = {
            "station_code": str(self.code),
            "station_name": self.name,
            "cobacia": cobacia,
            "drainage_area": drainage_area,
            "drainage_area_geo": drainage_area_geo,
        }
        watershed["station_code"] = str(self.code)
        watershed["cobacia"] = cobacia
        watershed["drainage_area_geo"] = drainage_area_geo

        # Each preparation call chooses its parent directory; names stay code-based.
        self.station_dir = Path(output_dir) / str(self.code)
        self.metadata_path = self.station_dir / "metadata.json"
        self.upstream_watershed_path = self.station_dir / "upstream_watershed.parquet"
        self.station_dir.mkdir(parents=True, exist_ok=True)
        watershed.to_parquet(self.upstream_watershed_path, index=False)
        with self.metadata_path.open("w", encoding="utf-8") as file:
            json.dump(metadata, file, ensure_ascii=False, indent=2, allow_nan=False)
        self.metadata = metadata
        self.upstream_watershed = watershed
        return metadata

    def download_rain(
        self,
        downloader: Downloader,
        *,
        freq: str,
        start: str,
        end: str,
    ) -> None:
        """
        Download and save basin rainfall independently of hydrological observations.

        MERGE monthly totals are averaged over clipped cells without area weighting.
        Normalize labels to month start and reject missing rainfall months so the
        saved series represents consecutive model steps.

        Args:
            downloader: MERGE downloader configured with its local download folder.
            freq: M for monthly; D is recognized but not implemented.
            start: Inclusive first date of the requested rainfall window.
            end: Inclusive last date of the requested rainfall window.

        Raises:
            NotImplementedError: If daily downloading is requested.
            ValueError: If frequency is unsupported or monthly rainfall is missing.

        """
        if freq == "D":
            msg = "Daily rainfall downloading is not implemented."
            raise NotImplementedError(msg)
        if freq != "M":
            msg = "Frequency must be 'M' or 'D'."
            raise ValueError(msg)

        from mergedownloader.inpeparser import InpeTypes  # noqa: PLC0415
        from mergedownloader.utils import GISUtil  # noqa: PLC0415

        cube = downloader.create_cube(start, end, InpeTypes.MONTHLY_ACCUM_YEARLY)
        clipped = GISUtil.cut_cube_by_geoms(cube, self.upstream_watershed.geometry)
        # MERGE already contains monthly totals; only their labels need normalization.
        rain = clipped.mean(dim=["latitude", "longitude"]).to_series()
        rain.index = pd.DatetimeIndex(rain.index).to_period("M").to_timestamp()
        first_month = pd.Timestamp(start).to_period("M").to_timestamp()
        months = pd.date_range(first_month, end, freq="MS", name="date")
        rain = rain.reindex(months)
        if rain.isna().any():
            msg = "Monthly rainfall is missing; choose a continuous rainfall window."
            raise ValueError(msg)

        for folder in ("Monthly", "Daily"):
            (self.station_dir / folder).mkdir(parents=True, exist_ok=True)
        rain.to_frame("prec_mm").to_parquet(self.station_dir / "Monthly" / "rain.parquet")

    def download_discharge(
        self,
        conn: SqlReader,
        *,
        freq: str,
        start: str,
        end: str,
    ) -> None:
        """
        Load and save discharge independently of basin rainfall.

        Monthly discharge is the mean of available daily values, ignoring NaN,
        after Station's existing Hidro/Telemetria merging and sanitization.
        The supplied SQL connector remains caller-owned.

        Args:
            conn: Shared SQL connector used to retrieve hydrological observations.
            freq: M for monthly; D is recognized but not implemented.
            start: Inclusive first date of the requested discharge window.
            end: Inclusive last date of the requested discharge window.

        Raises:
            NotImplementedError: If daily downloading is requested.
            ValueError: If frequency is unsupported.

        """
        if freq == "D":
            msg = "Daily discharge downloading is not implemented."
            raise NotImplementedError(msg)
        if freq != "M":
            msg = "Frequency must be 'M' or 'D'."
            raise ValueError(msg)

        self.connector = conn
        self.hidro = Hidro(conn)
        self.telemetria = Telemetria(conn)
        self.load_series(start=start, end=end)
        discharge = self.get_series(series_type="vazao", period=slice(start, end))["val"]
        monthly_q = discharge.resample("MS").mean().rename_axis("date")

        for folder in ("Monthly", "Daily"):
            (self.station_dir / folder).mkdir(parents=True, exist_ok=True)
        monthly_q.to_frame("q_m3s").to_parquet(
            self.station_dir / "Monthly" / "discharge.parquet",
        )

    def load_series(self, *, start: str | None = None, end: str | None = None) -> None:
        """
        Load daily observations by station code and calculate quality statistics.

        The historical code and each internal telemetric code remain separate in
        series and stats. Statistics describe the requested loading window's records.

        Args:
            start: Inclusive first date; omit for the complete available record.
            end: Inclusive last date; omit for the complete available record.

        """
        if self.connector is None:
            msg = "Live series loading requires a caller-owned SQL connector in from_folder()."
            raise RuntimeError(msg)
        date_predicate("Data", start, end)
        # Discover telemetry only when observations are requested, not for basin preparation.
        self.telemetric_info = self.telemetria.get_telemetric_code(self.code)
        self.series: dict[int, dict[SeriesType, pd.DataFrame]] = {
            self.code: {
                kind: self.hidro.get_series(self.code, kind, start=start, end=end)
                for kind in ("cota", "vazao")
            },
        }
        if self.telemetric_info is not None:
            for code in self.telemetric_info.index:
                self.series[int(code)] = {
                    kind: self.telemetria.get_series(
                        int(code),
                        kind,
                        start=start,
                        end=end,
                    )
                    for kind in ("cota", "vazao")
                }
        self.calc_stats()

    def get_source(self, station_code: int) -> str:
        """
        Return the source label for a loaded station code.

        Args:
            station_code: Historical Hidro code or internal telemetric code.

        Returns:
            Hidro for the historical code, or Telemetria followed by its origin.

        """
        if station_code == self.code:
            return "Hidro"
        if self.telemetric_info is not None and station_code in self.telemetric_info.index:
            return "Telemetria/" + str(self.telemetric_info.loc[station_code, "OGMORGAO"])
        return "Hidro"

    def get_series(
        self,
        source: Source = "hidro/telemetria",
        series_type: SeriesType = "vazao",
        period: slice = DEFAULT_PERIOD,
    ) -> pd.DataFrame:
        """
        Return a sorted daily DataFrame with source precedence and sanitization.

        Historical records take precedence over telemetry on overlapping days.

        Args:
            source: Historical, telemetric, or combined observations.
            series_type: Discharge (vazao, m³/s) or stage (cota, cm).
            period: Inclusive pandas date slice applied after merging observations.

        Returns:
            Daily observations indexed by Data, with values in the val column.

        Raises:
            RuntimeError: If load_series has not been called.
            ValueError: If source or series_type is unsupported.

        """
        validate_series_type(series_type)
        if not hasattr(self, "series"):
            msg = "Call load_series() before requesting observations."
            raise RuntimeError(msg)

        if source not in ("hidro", "telemetria", "hidro/telemetria"):
            msg = "Source must be 'hidro', 'telemetria', or 'hidro/telemetria'."
            raise ValueError(msg)

        frames = []
        if "hidro" in source and not self.series[self.code][series_type].empty:
            frames.append(self.series[self.code][series_type].copy())

        if "telemetria" in source:
            telemetry = [
                series[series_type].copy()
                for code, series in self.series.items()
                if code != self.code and not series[series_type].empty
            ]
            if telemetry:
                frame = pd.concat(telemetry).reset_index()
                # Resolve overlapping telemetry by origin priority, then station code.
                rank = {origin: i for i, origin in enumerate(Telemetria.PRECEDENCE)}
                frame["_origin_rank"] = frame["ORIGEM"].astype(object).map(rank).fillna(len(rank))
                frame = frame.sort_values(["Data", "_origin_rank", "HORESTACAO"], kind="stable")
                frame = frame.drop_duplicates("Data").drop(columns="_origin_rank").set_index("Data")
                frame["NivelConsistencia"] = 1
                frames.append(frame)

        if not frames:
            return empty_series()

        # Historical frames come first, followed by origin-ranked telemetry.
        frame = pd.concat(frames)
        frame = frame[~frame.index.duplicated(keep="first")].sort_index()
        if self.sanitization and series_type in self.sanitization:
            # Apply researcher-supplied replacements to the merged daily record.
            replacements = self.sanitization[series_type]
            for date, value in replacements.items():
                timestamp = pd.Timestamp(date).normalize()
                if timestamp in frame.index:
                    frame.loc[timestamp, "val"] = float(value)
        return frame.loc[period].copy()

    def available_series(self) -> pd.DataFrame:
        """
        List record counts after load_series has loaded observations.

        Returns:
            Station codes, sources, measurements, and daily record counts.

        """
        records = []
        for code, series in self.series.items():
            for kind, frame in series.items():
                records.append(
                    {
                        "code": code,
                        "source": "Hidro" if code == self.code else "Telemetria",
                        "measurement": kind,
                        "records": len(frame),
                    },
                )
        return pd.DataFrame(records)

    def plot_series(
        self,
        source: Source = "hidro/telemetria",
        series_type: SeriesType = "vazao",
        *,
        period: slice = DEFAULT_PERIOD,
        ax: Axes | None = None,
    ) -> Axes:
        """
        Plot daily discharge or stage for the requested source and period.

        Args:
            source: Historical, telemetric, or combined observations.
            series_type: Discharge (vazao, m³/s) or stage (cota, cm).
            period: Inclusive pandas date slice for the observations.
            ax: Existing plotting axes; omit to create axes.

        Returns:
            Axes showing the selected daily observations.

        Raises:
            ValueError: If the selected series is empty.

        """
        frame = self.get_series(source, series_type, period)
        if frame.empty:
            msg = f"No {series_type} observations for station {self.code} and source {source}."
            raise ValueError(msg)
        ax = frame["val"].plot(ax=ax, figsize=(12, 4))
        ax.set_title(f"{self.code} — {self.name} ({source})")
        ax.set_ylabel("Vazão (m³/s)" if series_type == "vazao" else "Cota (cm)")
        ax.set_xlabel("Data")
        return ax

    def calc_stats(self) -> None:
        """
        Summarize record coverage and consistency for each loaded station code.

        Store stats with an EstacaoCodigo index and Fonte, cota, and vazao column
        groups, matching the original station summary. Missing-day percentages
        use the inclusive span between the first and last observation. Only Hidro
        records with NivelConsistencia equal to 2 count as consolidated. Statistics
        describe stored observations before get_series merging or sanitization.

        Raises:
            RuntimeError: If load_series has not been called.

        """
        if not hasattr(self, "series"):
            msg = "Call load_series() before calculating statistics."
            raise RuntimeError(msg)

        rows = []
        for code, series in self.series.items():
            source = self.get_source(code)
            # Keep sources separate so merging cannot hide gaps or consistency differences.
            stats = {
                kind: HydroStats.calc_series_stats(
                    frame,
                    "val",
                    "NivelConsistencia" if source == "Hidro" else None,
                )
                for kind, frame in series.items()
            }

            # Unstack preserves the original (measurement, metric) column layout.
            df = pd.DataFrame(stats).unstack().to_frame().T  # noqa: PD010
            df.index = pd.Index([code], name="EstacaoCodigo")
            df["Fonte"] = source
            rows.append(df)

        stats_df = pd.concat(rows)
        self.stats = stats_df[["Fonte", "cota", "vazao"]]
