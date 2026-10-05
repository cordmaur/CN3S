"""Station inventory and source-aware daily series, without statistics clients."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, TypeAlias

import pandas as pd

from .data import SeriesType, Source, date_predicate, empty_series, validate_series_type
from .hidro import Hidro
from .telemetria import Telemetria

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from .sql import SqlConnector

DataSanitization: TypeAlias = dict[SeriesType, dict[str, float]]

DEFAULT_PERIOD = slice(None, None)


class Station:
    """
    Aggregate a historical station and its associated telemetric stations.

    Providers are borrowed when supplied. Otherwise both share one lazily created
    connector owned by the station's Hidro provider. Series contain daily values;
    historical records take precedence when both systems cover a day.
    """

    def __init__(
        self,
        code: int,
        sanitization: DataSanitization | None = None,
        *,
        connector: SqlConnector,
        start: str | None = None,
        end: str | None = None,
    ) -> None:
        """Load inventory and daily observations for a station and optional window."""
        date_predicate("Data", start, end)
        self.code = int(code)
        self.sanitization = sanitization
        self.start, self.end = start, end
        self.connector = connector
        self.hidro = Hidro(connector)
        self.telemetria = Telemetria(self.hidro.connector)
        try:
            self.info = self.hidro.get_station_info(self.code)
            self.telemetric_info = self.telemetria.get_telemetric_code(self.code)
            self.load_series()
        except Exception:
            self.close()
            raise

    @property
    def name(self) -> str:
        """Return the historical station name."""
        return str(self.info["Nome"].iloc[0])

    def load_series(self) -> None:
        """Load both measurements for each source within the configured date window."""
        self.historical_series = {
            kind: self.hidro.get_series(self.code, kind, start=self.start, end=self.end)
            for kind in ("cota", "vazao")
        }
        self.telemetric_series: dict[int, dict[SeriesType, pd.DataFrame]] = {}
        if self.telemetric_info is not None:
            for code in self.telemetric_info.index:
                self.telemetric_series[int(code)] = {
                    kind: self.telemetria.get_series(
                        int(code), kind, start=self.start, end=self.end
                    )
                    for kind in ("cota", "vazao")
                }

    def get_series(
        self,
        source: Source = "hidro/telemetria",
        series_type: SeriesType = "vazao",
        period: slice = DEFAULT_PERIOD,
    ) -> pd.DataFrame:
        """
        Return a sorted daily DataFrame with source precedence and sanitization.

        This core API returns the data directly. Statistics and reporter integration
        are deferred; it does not return the legacy (data, statistics) tuple.
        """
        validate_series_type(series_type)
        if source not in ("hidro", "telemetria", "hidro/telemetria"):
            msg = "Source must be 'hidro', 'telemetria', or 'hidro/telemetria'."
            raise ValueError(msg)
        frames = []
        if "hidro" in source and not self.historical_series[series_type].empty:
            frames.append(self.historical_series[series_type].copy())
        if "telemetria" in source:
            telemetry = [
                series[series_type].copy()
                for series in self.telemetric_series.values()
                if not series[series_type].empty
            ]
            if telemetry:
                frame = pd.concat(telemetry).reset_index()
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
            replacements = self.sanitization[series_type]
            for date, value in replacements.items():
                timestamp = pd.Timestamp(date).normalize()
                if timestamp in frame.index:
                    frame.loc[timestamp, "val"] = float(value)
        return frame.loc[period].copy()

    def available_series(self) -> pd.DataFrame:
        """List loaded source/measurement combinations and their daily record counts."""
        records = []
        for kind, frame in self.historical_series.items():
            records.append(
                {"code": self.code, "source": "Hidro", "measurement": kind, "records": len(frame)}
            )
        for code, series in self.telemetric_series.items():
            for kind, frame in series.items():
                records.append(
                    {
                        "code": code,
                        "source": "Telemetria",
                        "measurement": kind,
                        "records": len(frame),
                    }
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
        """Plot one selected series, keeping plotting setup out of notebooks."""
        frame = self.get_series(source, series_type, period)
        if frame.empty:
            msg = f"No {series_type} observations for station {self.code} and source {source}."
            raise ValueError(msg)
        ax = frame["val"].plot(ax=ax, figsize=(12, 4))
        ax.set_title(f"{self.code} — {self.name} ({source})")
        ax.set_ylabel("Vazão (m³/s)" if series_type == "vazao" else "Cota (cm)")
        ax.set_xlabel("Data")
        return ax

    def close(self) -> None:
        """Close owned providers, leaving caller-supplied providers open."""
        if self.telemetria is not None:
            self.telemetria.close()
        if self.hidro is not None:
            self.hidro.close()

    def __enter__(self) -> Self:
        """Return this station as a context manager."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Release owned resources on context exit."""
        self.close()
