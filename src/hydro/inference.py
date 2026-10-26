"""Monthly CN3S inference from CDS forecasts and basin rainfall observations."""

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

from cn3s import CN3S, CN3SParams
from hydro.forecast import (
    load_forecast_grids,
    plot_discharge_comparison,
    plot_monthly_discharge_comparison,
    plot_rainfall_comparison,
)
from hydro.station import Station
from utils.sql_connector import SqlConnector

if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from plotly.graph_objects import Figure as PlotlyFigure


class Inference:
    """Keep prepared monthly rainfall and CN3S results together for one station."""

    def __init__(
        self,
        station: Station,
        data_dir: str | Path,
        freq: str,
        optimization: str,
    ) -> None:
        """
        Load saved parameters and retain the context for one inference workflow.

        Args:
            station: Prepared station with basin geometry and station_dir.
            data_dir: CN3S root containing forecasts/ and downloads/.
            freq: Monthly frequency, "M". Daily inference is not implemented.
            optimization: Calibration JSON filename inside the station's optim/ folder.

        """
        if freq != "M":
            msg = "Inference currently supports monthly (M) rainfall only."
            raise NotImplementedError(msg)
        self.station = station
        self.data_dir = Path(data_dir)
        self.freq = freq
        self.params = CN3SParams.from_file(station.station_dir / "optim" / optimization)
        self.model = CN3S(self.params, freq="M")

    def prepare_data(
        self,
        start_month: str,
        *,
        year: int | None = None,
        as_of: str | None = None,
        models: list[str] | None = None,
    ) -> None:
        """
        Load CDS grids and online basin rainfall, then correct forecast bias.

        Args:
            start_month: CDS initialization month, e.g. "09" for September.
            year: Initialization year; defaults to the as-of year.
            as_of: Reference date; defaults to today in America/Sao_Paulo. Selects
                remaining forecast months and the recent rainfall window, but does
                not reconstruct an earlier snapshot of online observations.
            models: CDS centre names; defaults to the nine notebook 03 centres,
                with UKMO supplying the reference spatial grid.

        Returns:
            None. Stores forecast grids and rainfall arrays in mm/month, including
            rain_observed, rain_climatology, rain_corrected and rain_forecast.
            Current-month observed rainfall can be partial or cached; it is only
            plotted. run_model uses a separate copy of saved historical rainfall.

        """
        self.as_of = (
            pd.Timestamp(as_of)
            if as_of is not None
            else pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None).normalize()
        )
        initialization = pd.Timestamp(year or self.as_of.year, int(start_month), 1)
        self.forecast_start = self.as_of.to_period("M").to_timestamp()
        if models is None:
            models = ["ukmo", "ecmwf", "meteo_france", "dwd", "cmcc", "ncep", "jma", "eccc", "bom"]
        self.forecast = load_forecast_grids(
            self.data_dir / "forecasts",
            initialization,
            models,
            self.station.upstream_watershed,
        ).sel(time=slice(self.forecast_start, None))
        self.forecast_months = pd.DatetimeIndex(self.forecast.time.to_numpy())
        if self.forecast_months.empty:
            msg = "No forecast months remain for this initialization and as_of date."
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
            self.station.upstream_watershed.geometry,
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
                self.station.upstream_watershed.geometry,
            )
            .mean(dim=["latitude", "longitude"])
            .assign_coords(time=climatology_months)
        )
        self.correct_rainfall()
        # Re-preparation invalidates model results from a previous forecast cycle.
        self.rain_scenarios = pd.DataFrame()
        self.discharge_scenarios = pd.DataFrame()
        self.model.reset()

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

        """
        return plot_rainfall_comparison(
            self.rain_observed,
            self.rain_climatology,
            self.rain_corrected,
            title=(
                f"{self.station.name} ({self.station.code}) - "
                "Precipitação mensal: observações e previsão corrigida"
            ),
        )

    def run_model(self) -> pd.DataFrame:
        """
        Run climatological-rainfall and corrected-forecast rainfall scenarios.

        Returns:
            Discharge DataFrame in m³/s on ACT-shifted model dates, also stored as
            discharge_scenarios. rain_scenarios retains monthly inputs for inspection.
            Both runs start with identical saved rainfall history and calibrated r0;
            calibration files are read only, and stored discharge is not used.

        """
        history = pd.read_parquet(self.station.station_dir / "Monthly" / "rain.parquet")[
            "prec_mm"
        ].copy()
        history = history.loc[history.index < self.forecast_start]
        future_rain = pd.DataFrame(
            {
                "climatology": self.rain_climatology.sel(time=self.forecast.time).to_pandas(),
                "forecast": self.rain_forecast,
            },
        )
        self.rain_scenarios = pd.concat(
            [
                pd.DataFrame({"climatology": history, "forecast": history}),
                future_rain,
            ],
        )
        # Missing months would change the antecedent-rainfall and storage sequence.
        calendar = pd.date_range(
            self.rain_scenarios.index.min(),
            self.rain_scenarios.index.max(),
            freq="MS",
        )
        if not self.rain_scenarios.index.equals(calendar) or self.rain_scenarios.isna().any().any():
            msg = "Rainfall history and forecast must form a complete consecutive monthly series."
            raise ValueError(msg)
        discharge = {}
        for scenario in self.rain_scenarios:
            self.model.run(self.rain_scenarios[scenario], pbar=False)
            discharge[scenario] = self.model.results["q_m3s"].copy()
        self.discharge_scenarios = pd.DataFrame(discharge)
        return self.discharge_scenarios

    def load_discharge(self) -> pd.Series:
        """
        Retrieve daily discharge online for the historical comparison chart.

        Returns:
            Daily discharge in m³/s, also stored as discharge_daily. Requires Azure
            SQL sign-in and retains Station's historical/telemetric precedence.
            No observations are saved; the connection is closed after retrieval.

        """
        conn = SqlConnector()
        try:
            live_station = Station.from_folder(self.station.station_dir, connector=conn)
            live_station.load_series()
            discharge: pd.Series = live_station.get_series("hidro/telemetria", "vazao")["val"]
            self.discharge_daily = discharge
        finally:
            conn.close()
        return discharge

    def plot_monthly_discharge(
        self,
        *,
        months_each_side: int = 6,
        anchor_to_observed: bool = False,
    ) -> PlotlyFigure:
        """
        Compare monthly observed and predicted discharge around the as-of month.

        Args:
            months_each_side: Number of calendar months on either side of the
                as-of month; six gives a centered 13-month window.
            anchor_to_observed: Shift each plotted forecast scenario by a constant
                delta Q (m³/s) so its reference-month value equals the partial
                observed mean for that month. Requires both values in that month.
                Assumes the partial mean is representative and the bias persists
                across the forecast horizon. Raw model results are unchanged;
                shifted values are not clipped, even if they become negative.

        Returns:
            Plotly figure in m³/s. Stores discharge_monthly (mean and valid-day
            count) and discharge_monthly_stats (median, p10, p90, sample count).
            Historical statistics use monthly means from months before the as-of
            month, grouped by calendar month. Means use available daily values;
            gaps are not filled and no minimum coverage cutoff is imposed.
            The current month's observed mean is explicitly partial. The band
            represents historical variability, not forecast uncertainty.
            The reference year and its two preceding years are overlaid by
            calendar month, with month-only axis labels and source-year hovers.
            Call run_model and load_discharge first; this method performs no I/O.

        """
        if months_each_side < 1:
            msg = "months_each_side must be at least 1."
            raise ValueError(msg)
        current_month = self.as_of.to_period("M").to_timestamp()
        # Limit observations to the reference day, even when SQL returns more recent data.
        daily = self.discharge_daily.sort_index().loc[: self.as_of.normalize()]
        self.discharge_monthly = daily.resample("MS").agg(["mean", "count"])
        history = self.discharge_monthly.loc[self.discharge_monthly.index < current_month, "mean"]
        # Each year-month contributes one mean, rather than pooling unequal daily samples.
        groups = history.groupby(history.index.month)
        self.discharge_monthly_stats = pd.DataFrame(
            {
                "median": groups.median(),
                "p10": groups.quantile(0.10),
                "p90": groups.quantile(0.90),
                "count": groups.count(),
            },
        )
        return plot_monthly_discharge_comparison(
            self.discharge_monthly,
            self.discharge_scenarios,
            self.discharge_monthly_stats,
            as_of=self.as_of,
            months_each_side=months_each_side,
            anchor_to_observed=anchor_to_observed,
        )

    def plot_discharge(self, *, colors: dict[int, str] | None = None) -> PlotlyFigure:
        """
        Compare simulated discharge with the loaded daily observations.

        Args:
            colors: Comparison calendar years and colors. Defaults to the as-of
                year (black) and its two preceding years (green and blue).

        Returns:
            Plotly Figure with a 12-month window, daily historical percentiles and
            pooled-daily monthly medians, preserving notebook 04's conventions.
            Call run_model and load_discharge first; this method performs no I/O.

        """
        if colors is None:
            colors = {
                self.as_of.year - 2: "green",
                self.as_of.year - 1: "blue",
                self.as_of.year: "black",
            }
        dates = pd.DatetimeIndex(self.discharge_daily.index)
        groups = self.discharge_daily.groupby([dates.month, dates.day])
        daily_stats = pd.DataFrame(
            {
                "median": groups.median(),
                "p10": groups.quantile(0.10),
                "p90": groups.quantile(0.90),
            },
        )
        monthly_median = self.discharge_daily.groupby(dates.month).median()
        return plot_discharge_comparison(
            self.discharge_daily,
            self.discharge_scenarios,
            daily_stats,
            monthly_median,
            colors=colors,
            forecast_steps=len(self.forecast_months),
            act=self.params.act,
            as_of=self.as_of,
        )
