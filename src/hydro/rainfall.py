"""Basin rainfall observations and monthly multi-model forecasts."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pandas as pd
import plotly.express as px
from mergedownloader.downloader import Downloader
from mergedownloader.file_downloader import DownloadMode, FileDownloader
from mergedownloader.inpeparser import InpeParsers, InpeTypes
from mergedownloader.utils import GISUtil

from hydro.forecast import load_forecast_grids, plot_rainfall_comparison

if TYPE_CHECKING:
    import geopandas as gpd
    from matplotlib.figure import Figure
    from plotly.graph_objects import Figure as PlotlyFigure


class RainfallForecast:
    """Keep monthly rainfall observations and prepared forecasts for one basin."""

    def __init__(
        self,
        basin: gpd.GeoDataFrame,
        data_dir: str | Path,
        *,
        name: str = "Basin",
    ) -> None:
        """
        Retain basin geometry and the shared rainfall data location.

        Args:
            basin: Polygon rows forming one analysis region, with a defined CRS.
                Read GeoParquet and select the desired basin before construction.
            data_dir: CN3S root containing forecasts/ and downloads/.
            name: Basin label used in the corrected rainfall chart title.

        """
        if basin.crs is None:
            msg = "Basin geometry must have a defined CRS."
            raise ValueError(msg)
        self.basin = basin
        self.data_dir = Path(data_dir)
        self.name = name

    def prepare_data(
        self,
        start_month: str,
        *,
        year: int | None = None,
        as_of: str | None = None,
        models: list[str] | None = None,
        months: int | None = None,
    ) -> None:
        """
        Load saved CDS grids and online basin rainfall, then correct forecast bias.

        Args:
            start_month: CDS initialization month, e.g. "09" for September.
            year: Initialization year; defaults to the as-of year.
            as_of: Reference date; defaults to today in America/Sao_Paulo. Selects
                remaining forecast months and the recent rainfall window, but does
                not reconstruct an earlier snapshot of online observations.
            models: CDS centre names; defaults to the nine notebook 03 centres,
                with UKMO supplying the reference spatial grid.
            months: Positive forecast month count starting in the as-of month.
                None uses all remaining downloaded leads. Explicit counts require
                every requested calendar month to be present in the CDS files.

        Returns:
            None. Stores forecast grids (30-day-equivalent mm), rain_observed and
            rain_climatology (calendar-month mm), rain_anomaly_pct (%),
            rain_corrected (calendar-month mm per model) and rain_forecast (median
            calendar-month mm). Current-month observations may be partial or cached.

        Raises:
            FileNotFoundError: If forecast files are missing; download with notebook 03.
            ValueError: If the requested horizon is unavailable or months is below 1.

        """
        if months is not None and months < 1:
            msg = "months must be at least 1, or None for all remaining forecast months."
            raise ValueError(msg)
        self.as_of = (
            pd.Timestamp(as_of)
            if as_of is not None
            else pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None).normalize()
        )
        initialization = pd.Timestamp(year or self.as_of.year, int(start_month), 1)
        self.forecast_start = self.as_of.to_period("M").to_timestamp()
        if models is None:
            models = ["ukmo", "ecmwf", "meteo_france", "dwd", "cmcc", "ncep", "jma", "eccc", "bom"]
        try:
            forecast = load_forecast_grids(
                self.data_dir / "forecasts",
                initialization,
                models,
                self.basin,
            )
        except FileNotFoundError as error:
            msg = (
                f"{error}. Download the required forecast/hindcast files with "
                "notebook 03 (03-CDS-Forecast_Download.ipynb) before preparing rainfall."
            )
            raise FileNotFoundError(msg) from error
        available = pd.DatetimeIndex(forecast.time.to_numpy())
        available_text = ", ".join(available.strftime("%Y-%m"))
        self.forecast = forecast.sel(time=slice(self.forecast_start, None))
        if months is not None:
            requested = pd.date_range(self.forecast_start, periods=months, freq="MS")
            if not requested.isin(available).all():
                msg = (
                    f"Requested {months} forecast months from {self.forecast_start:%Y-%m}, "
                    f"but available months are: {available_text}. "
                    "Download additional leads with notebook 03 or reduce months."
                )
                raise ValueError(msg)
            self.forecast = forecast.sel(time=requested)
        self.forecast_months = pd.DatetimeIndex(self.forecast.time.to_numpy())
        if self.forecast_months.empty:
            msg = (
                "No forecast months remain for this initialization and as_of date. "
                f"Available months: {available_text}."
            )
            raise ValueError(msg)

        # Include 13 antecedent months plus the current month, as in notebook 05.
        recent_start = self.forecast_start - pd.DateOffset(months=13)
        downloader = Downloader(
            file_downloader=FileDownloader(download_mode=DownloadMode.NO_UPDATE),
            local_folder=str(self.data_dir / "downloads"),
            parsers=InpeParsers,
        )
        observed_grid = downloader.create_cube(
            recent_start.to_pydatetime(),
            self.forecast_start.to_pydatetime(),
            InpeTypes.MONTHLY_ACCUM_MANUAL,
        )
        self.rain_observed = GISUtil.cut_cube_by_geoms(
            observed_grid,
            self.basin.geometry,
        ).mean(dim=["latitude", "longitude"])

        climatology_months = pd.date_range(
            recent_start,
            self.forecast_months.max(),
            freq="MS",
        )
        climatology_grid = downloader.create_cube(
            climatology_months[0].to_pydatetime(),
            climatology_months[-1].to_pydatetime(),
            InpeTypes.MONTHLY_ACCUM,
        )
        # The climatology product labels months with reference-year timestamps.
        if not (climatology_grid.time.dt.month.to_numpy() == climatology_months.month).all():
            msg = "Rainfall climatology months do not match the requested calendar."
            raise ValueError(msg)
        self.rain_climatology = (
            GISUtil.cut_cube_by_geoms(
                climatology_grid,
                self.basin.geometry,
            )
            .mean(dim=["latitude", "longitude"])
            .assign_coords(time=climatology_months)
        )
        self.correct_rainfall()

    def correct_rainfall(self) -> None:
        """
        Apply forecast/hindcast grid ratios to observed rainfall climatology.

        Returns:
            None. Stores rain_anomaly_pct (%), rain_corrected (mm/month per model),
            and rain_forecast (median mm/month as a pandas Series). Preserves the
            basin mean of grid-cell ratios, not the ratio of basin means. Called
            by prepare_data after loading both products.

        """
        ratio = (self.forecast["prec"] / self.forecast["hindcast"]).mean(
            dim=["longitude", "latitude"],
        )
        self.rain_anomaly_pct = 100 * (ratio - 1)
        self.rain_corrected = self.rain_climatology.sel(time=self.forecast.time) * (
            1 + self.rain_anomaly_pct / 100
        )
        self.rain_forecast = self.rain_corrected.median(dim="model").to_pandas()

    def plot_raw_rainfall(self) -> Figure:
        """
        Compare observed rainfall and the uncorrected multi-model mean.

        Returns:
            Matplotlib Figure with monthly basin rainfall in mm. Current-month
            observations may be partial. All artists use dates measured in days.

        """
        rain_raw = self.forecast["prec"].mean(dim=["latitude", "longitude", "model"])
        fig, ax = plt.subplots(figsize=(10, 5))
        # With DataArray dates, width=20 can be interpreted as nanoseconds and
        # collapse to zero days. DatetimeIndex makes the bar width mean 20 days.
        ax.plot(
            pd.DatetimeIndex(self.rain_climatology.time.to_numpy()),
            self.rain_climatology.to_numpy(),
            label="Média Mensal",
            color="orange",
        )
        ax.bar(
            pd.DatetimeIndex(self.rain_observed.time.to_numpy()),
            self.rain_observed.to_numpy(),
            width=20,
            label="Observado",
        )
        ax.bar(
            pd.DatetimeIndex(rain_raw.time.to_numpy()),
            rain_raw.to_numpy(),
            width=20,
            label="Previsão",
            alpha=0.5,
            color="grey",
        )
        ax.set(
            title="Precipitação Média: Previsão vs Observado",
            xlabel="Time",
            ylabel="Precipitation (mm)",
        )
        ax.legend()
        return fig

    def plot_rainfall_anomaly(self) -> PlotlyFigure:
        """
        Plot the basin forecast/hindcast percentage anomaly by model and month.

        Returns:
            Plotly Figure of rainfall anomalies relative to each model's hindcast.

        """
        table = self.rain_anomaly_pct.to_dataframe(name="Anomaly (%)").reset_index()
        table["Month"] = table["time"].dt.strftime("%b %Y")
        fig = px.bar(
            table,
            x="Month",
            y="Anomaly (%)",
            color="model",
            barmode="group",
            title="Monthly precipitation anomaly by forecast model",
            labels={"model": "Forecast model"},
        )
        fig.update_layout(
            yaxis_title="Precipitation anomaly (%)",
            xaxis_title="",
            legend_title="Model",
            template="plotly_white",
            hovermode="x unified",
        )
        fig.add_hline(y=0, line_color="black", line_width=1)
        return fig

    def plot_forecast_rainfall(self) -> PlotlyFigure:
        """
        Plot bias-corrected rainfall against observed rainfall and climatology.

        Returns:
            Plotly Figure in mm/month with the corrected median and model spread.
            Each box contains one corrected ensemble-mean value per forecast centre,
            describing inter-model spread rather than individual ensemble members.

        """
        return plot_rainfall_comparison(
            self.rain_observed,
            self.rain_climatology,
            self.rain_corrected,
            title=(f"{self.name} - Precipitação mensal: observações e previsão corrigida"),
        )
