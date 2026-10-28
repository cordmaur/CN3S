"""Monthly CN3S inference composed with basin rainfall forecasting."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from cn3s import CN3S, CN3SParams
from hydro.forecast import plot_discharge_comparison, plot_monthly_discharge_comparison
from hydro.rainfall import RainfallForecast
from hydro.station import Station
from utils.sql_connector import SqlConnector

if TYPE_CHECKING:
    from plotly.graph_objects import Figure as PlotlyFigure


class Inference:
    """Keep a station's rainfall component and calibrated CN3S results together."""

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
        self.rainfall = RainfallForecast(
            station.upstream_watershed,
            self.data_dir,
            name=f"{station.name} ({station.code})",
        )
        self.params = CN3SParams.from_file(station.station_dir / "optim" / optimization)
        self.model = CN3S(self.params, freq="M")

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
        Prepare basin rainfall and invalidate previous CN3S simulations.

        Args:
            start_month: CDS initialization month, e.g. "09" for September.
            year: Initialization year; defaults to the as-of year.
            as_of: Reference date; defaults to today in America/Sao_Paulo.
                Selects rainfall months, not a historical observation snapshot.
            models: CDS centre names; defaults to the nine notebook 03 centres.
            months: Forecast month count starting in the reference month. None
                uses all remaining downloaded leads; explicit counts must be available.

        Returns:
            None. Prepared arrays belong to rainfall. Clears rain_scenarios,
            discharge_scenarios and model results. Current-month observations may
            be partial; run_model uses a separate saved historical rainfall prefix.

        """
        self.rainfall.prepare_data(
            start_month,
            year=year,
            as_of=as_of,
            models=models,
            months=months,
        )
        # A different forcing invalidates simulations from the previous forecast cycle.
        self.rain_scenarios = pd.DataFrame()
        self.discharge_scenarios = pd.DataFrame()
        self.model.reset()

    def run_model(self) -> pd.DataFrame:
        """
        Run climatological-rainfall and corrected-forecast rainfall scenarios.

        Returns:
            Discharge DataFrame in m³/s on ACT-shifted model dates, also stored as
            discharge_scenarios. rain_scenarios retains monthly inputs for inspection.
            Both runs start with identical saved rainfall history and calibrated r0;
            calibration files are read only, and stored discharge is not used.

        """
        rainfall = self.rainfall
        history = pd.read_parquet(self.station.station_dir / "Monthly" / "rain.parquet")[
            "prec_mm"
        ].copy()
        history = history.loc[history.index < rainfall.forecast_start]
        climatology = rainfall.rain_climatology.sel(time=rainfall.forecast.time).to_pandas()
        future_rain = pd.DataFrame(
            {
                "climatology": climatology,
                "forecast": rainfall.rain_forecast,
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
        current_month = self.rainfall.as_of.to_period("M").to_timestamp()
        # Limit observations to the reference day, even when SQL returns more recent data.
        daily = self.discharge_daily.sort_index().loc[: self.rainfall.as_of.normalize()]
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
            as_of=self.rainfall.as_of,
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
                self.rainfall.as_of.year - 2: "green",
                self.rainfall.as_of.year - 1: "blue",
                self.rainfall.as_of.year: "black",
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
            forecast_steps=len(self.rainfall.forecast_months),
            act=self.params.act,
            as_of=self.rainfall.as_of,
        )
