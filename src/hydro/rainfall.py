"""Basin rainfall observations, monthly forecasts, and spatial anomaly maps."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import xarray as xr
from matplotlib.colors import TwoSlopeNorm
from mergedownloader.downloader import Downloader
from mergedownloader.file_downloader import DownloadMode, FileDownloader
from mergedownloader.inpeparser import InpeParsers, InpeTypes
from mergedownloader.utils import GISUtil
from rasterio.enums import Resampling
from shapely.geometry import box

from hydro.forecast import load_forecast_grids, plot_rainfall_comparison

if TYPE_CHECKING:
    import geopandas as gpd
    from matplotlib.figure import Figure


MODEL_NAMES = {
    "ukmo": "UKMO GloaSea6-GC5.1",
    "ecmwf": "ECMWF SEAS5",
    "meteo_france": "Meteo France S9",
    "dwd": "DWD GCFS2.2",
    "cmcc": "CMCC SPS4",
    "ncep": "NCEP CFSv2",
    "jma": "JMA CPS4",
    "eccc": "ECCC GEM5.2-NEMO",
    "bom": "BOM ACCESS-S2",
}


def _month_labels(dates: pd.DatetimeIndex) -> list[str]:
    """
    Format Brazilian Portuguese month labels independently of the system locale.

    Args:
        dates: Monthly dates to label without changing their chronological order.

    Returns:
        Labels such as "out/2026" and "jan/2027".

    """
    months = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
    return [f"{months[date.month - 1]}/{date.year}" for date in dates]


class RainfallForecast:
    """Keep native rainfall grids, basin summaries, and regional map fields together."""

    def __init__(
        self,
        basin: gpd.GeoDataFrame,
        data_dir: str | Path,
        *,
        name: str = "Basin",
    ) -> None:
        """
        Retain basin context and initialize the processed-data dictionary.

        Args:
            basin: Polygon rows forming one analysis region, with a defined CRS.
                Read GeoParquet and select the desired basin before construction.
            data_dir: CN3S root containing forecasts/ and downloads/.
            name: Basin label used in chart titles.

        """
        if basin.crs is None:
            msg = "Basin geometry must have a defined CRS."
            raise ValueError(msg)
        self.basin = basin
        self.data_dir = Path(data_dir)
        self.name = name
        self.data: dict[str, xr.Dataset] = {
            "forecast": xr.Dataset(),
            "observed": xr.Dataset(),
            "climatology": xr.Dataset(),
            "map": xr.Dataset(),
        }

    def prepare_data(  # noqa: PLR0915 -- keep the scientific preparation steps together
        self,
        start_month: str,
        *,
        year: int | None = None,
        as_of: str | None = None,
        models: list[str] | None = None,
        months: int | None = None,
    ) -> None:
        """
        Prepare native grids, spatial corrections, and unchanged basin summaries.

        Args:
            start_month: CDS initialization month, e.g. "10" for October.
            year: Initialization year; defaults to the as-of year.
            as_of: Reference date; defaults to today in America/Sao_Paulo. Selects
                calendar months, not a historical snapshot of online observations.
            models: CDS centre names; defaults to the nine notebook 03 centres,
                with UKMO supplying the reference spatial grid.
            months: Positive forecast month count starting in the as-of month.
                None uses all remaining downloaded leads; explicit counts must
                include every requested calendar month.

        Returns:
            None. Replaces data only after successful processing. Native datasets
            contain grids and basin summaries; map retains unmasked regional
            anomalies for visualization. Forecast
            metadata records initialization, as_of, forecast_start, and models.
            Current-month observed rainfall may be partial or cached.

        Raises:
            FileNotFoundError: If CDS files are missing; download with notebook 03.
            ValueError: If the requested horizon or climatology calendar is invalid.

        """
        if months is not None and months < 1:
            msg = "months must be at least 1, or None for all remaining forecast months."
            raise ValueError(msg)
        reference = (
            pd.Timestamp(as_of)
            if as_of is not None
            else pd.Timestamp.now(tz="America/Sao_Paulo").tz_localize(None).normalize()
        )
        initialization = pd.Timestamp(year or reference.year, int(start_month), 1)
        forecast_start = reference.to_period("M").to_timestamp()
        if models is None:
            models = ["ukmo", "ecmwf", "meteo_france", "dwd", "cmcc", "ncep", "jma", "eccc", "bom"]
        try:
            forecast = load_forecast_grids(
                self.data_dir / "forecasts",
                initialization,
                models,
                None,
            )
        except FileNotFoundError as error:
            msg = (
                f"{error}. Download the required forecast/hindcast files with "
                "notebook 03 (03-CDS-Forecast_Download.ipynb) before preparing rainfall."
            )
            raise FileNotFoundError(msg) from error
        available = pd.DatetimeIndex(forecast.time.to_numpy())
        available_text = ", ".join(available.strftime("%Y-%m"))
        if months is None:
            forecast = forecast.sel(time=slice(forecast_start, None))
        else:
            requested = pd.date_range(forecast_start, periods=months, freq="MS")
            if not requested.isin(available).all():
                msg = (
                    f"Requested {months} forecast months from {forecast_start:%Y-%m}, "
                    f"but available months are: {available_text}. "
                    "Download additional leads with notebook 03 or reduce months."
                )
                raise ValueError(msg)
            forecast = forecast.sel(time=requested)
        forecast_months = pd.DatetimeIndex(forecast.time.to_numpy())
        if forecast_months.empty:
            msg = (
                "No forecast months remain for this initialization and as_of date. "
                f"Available months: {available_text}."
            )
            raise ValueError(msg)
        forecast = forecast.assign_coords(
            model_name=("model", [MODEL_NAMES.get(model, model) for model in models]),
        )

        # Keep the existing 13 antecedent months and partial current month.
        recent_start = forecast_start - pd.DateOffset(months=13)
        downloader = Downloader(
            file_downloader=FileDownloader(download_mode=DownloadMode.NO_UPDATE),
            local_folder=str(self.data_dir / "downloads"),
            parsers=InpeParsers,
        )
        observed_grid = downloader.create_cube(
            recent_start.to_pydatetime(),
            forecast_start.to_pydatetime(),
            InpeTypes.MONTHLY_ACCUM_MANUAL,
        )
        observed = GISUtil.cut_cube_by_geoms(observed_grid, self.basin.geometry)
        observed.attrs.update(units="mm", long_name="Observed monthly rainfall (possibly partial)")
        observed_data = xr.Dataset(
            {
                "rainfall": observed,
                "basin_mean": observed.mean(dim=["latitude", "longitude"]).assign_attrs(
                    units="mm",
                    long_name="Basin mean observed monthly rainfall",
                ),
            },
        )

        climatology_months = pd.date_range(recent_start, forecast_months.max(), freq="MS")
        climatology_grid = downloader.create_cube(
            climatology_months[0].to_pydatetime(),
            climatology_months[-1].to_pydatetime(),
            InpeTypes.MONTHLY_ACCUM,
        )
        # MERGE climatology uses reference-year dates; label the requested calendar.
        if not (climatology_grid.time.dt.month.to_numpy() == climatology_months.month).all():
            msg = "Rainfall climatology months do not match the requested calendar."
            raise ValueError(msg)
        climatology_grid = climatology_grid.assign_coords(time=climatology_months)
        climatology_grid.attrs.update(units="mm", long_name="Observed monthly rainfall climatology")
        climatology = GISUtil.cut_cube_by_geoms(climatology_grid, self.basin.geometry)
        climatology_data = xr.Dataset(
            {
                "rainfall": climatology,
                "basin_mean": climatology.mean(dim=["latitude", "longitude"]),
            },
        )
        climatology_data["basin_mean"].attrs.update(
            units="mm",
            long_name="Basin mean rainfall climatology",
        )

        # Average the original, uncut MERGE cells onto the coarse forecast grid.
        # Clipping first would bias coastal/basin-edge cells toward only their inside area.
        template = forecast["prec"].isel(model=0, time=0, drop=True)
        mapped_climatology = (
            climatology_grid.sel(time=forecast.time)
            .rio.reproject_match(template, resampling=Resampling.average)
            .rename(x="longitude", y="latitude")
        )
        # Retain real surrounding cells; basin products below keep the original mask.
        regional_ratio = forecast["prec"] / forecast["hindcast"]
        map_data = xr.Dataset(
            {
                "anomaly_pct": (100 * (regional_ratio - 1)).assign_attrs(
                    units="%",
                    long_name="Regional forecast/hindcast rainfall anomaly",
                ),
                "anomaly_mm": (mapped_climatology * (regional_ratio - 1)).assign_attrs(
                    units="mm",
                    long_name="Regional corrected rainfall minus observed climatology",
                ),
            },
        )
        forecast = xr.Dataset(
            {
                variable: GISUtil.cut_cube_by_geoms(forecast[variable], self.basin.geometry)
                for variable in ("prec", "hindcast")
            },
        )
        forecast["climatology"] = GISUtil.cut_cube_by_geoms(mapped_climatology, self.basin.geometry)
        forecast.attrs.update(
            initialization=initialization.isoformat(),
            as_of=reference.isoformat(),
            forecast_start=forecast_start.isoformat(),
            models=list(models),
            basin_name=self.name,
        )
        map_data.attrs = forecast.attrs.copy()
        forecast = self._correct_forecast(forecast, climatology_data["basin_mean"])
        self.data = {
            "forecast": forecast,
            "observed": observed_data,
            "climatology": climatology_data,
            "map": map_data,
        }

    @staticmethod
    def _correct_forecast(forecast: xr.Dataset, basin_climatology: xr.DataArray) -> xr.Dataset:
        """
        Calculate spatial products and preserve the original basin correction order.

        Args:
            forecast: Clipped CDS grids and observed climatology on the same spatial grid.
            basin_climatology: Native-grid basin climatology in calendar-month mm.

        Returns:
            Dataset with spatial and basin corrected rainfall/anomalies. Raw CDS
            values use 30-day-equivalent mm; their common scale cancels in the ratio.
            Basin correction uses mean(ratio) times mean(climatology), which differs
            from the mean of locally corrected grid cells.

        """
        forecast = forecast.copy()
        forecast["ratio"] = forecast["prec"] / forecast["hindcast"]
        forecast["anomaly_pct"] = 100 * (forecast["ratio"] - 1)
        forecast["corrected"] = forecast["climatology"] * forecast["ratio"]
        forecast["anomaly_mm"] = forecast["climatology"] * (forecast["ratio"] - 1)
        basin_ratio = forecast["ratio"].mean(dim=["longitude", "latitude"])
        forecast["basin_anomaly_pct"] = 100 * (basin_ratio - 1)
        baseline = basin_climatology.sel(time=forecast.time)
        # Retain the exact original arithmetic, including the percentage round trip.
        forecast["basin_corrected"] = baseline * (1 + forecast["basin_anomaly_pct"] / 100)
        forecast["basin_forecast"] = forecast["basin_corrected"].median(dim="model")
        forecast["basin_anomaly_mm"] = forecast["basin_corrected"] - baseline
        descriptions = {
            "prec": ("mm / 30 days", "Raw CDS forecast rainfall"),
            "hindcast": ("mm / 30 days", "CDS hindcast rainfall climatology"),
            "ratio": ("1", "Grid-cell forecast/hindcast ratio"),
            "climatology": ("mm", "Observed climatology averaged onto the forecast grid"),
            "corrected": ("mm", "Locally bias-corrected monthly rainfall"),
            "anomaly_pct": ("%", "Grid-cell forecast/hindcast rainfall anomaly"),
            "anomaly_mm": (
                "mm",
                "Local corrected rainfall anomaly relative to observed climatology",
            ),
            "basin_corrected": ("mm", "Basin corrected monthly rainfall per forecast centre"),
            "basin_forecast": ("mm", "Median corrected basin rainfall across forecast centres"),
            "basin_anomaly_pct": ("%", "Basin mean of grid-cell percentage anomalies"),
            "basin_anomaly_mm": ("mm", "Corrected basin rainfall minus basin climatology"),
        }
        for variable, (units, description) in descriptions.items():
            forecast[variable].attrs.update(units=units, long_name=description)
        return forecast

    def _forecast_data(self) -> xr.Dataset:
        """
        Return prepared forecast data or explain the missing preparation step.

        Returns:
            The forecast dataset, including its spatial products and basin summaries.

        Raises:
            RuntimeError: If prepare_data has not completed successfully.

        """
        forecast = self.data["forecast"]
        if not forecast.data_vars:
            msg = "Call prepare_data() before using prepared rainfall data or plots."
            raise RuntimeError(msg)
        return forecast

    def correct_rainfall(self) -> None:
        """
        Recalculate corrections from the currently prepared grids and climatology.

        Returns:
            None. Replaces data["forecast"] with recalculated spatial and basin
            products. Call prepare_data first; climatology remains in calendar-month mm.

        """
        self.data["forecast"] = self._correct_forecast(
            self._forecast_data(),
            self.data["climatology"]["basin_mean"],
        )

    def _anomaly(self, unit: str, *, spatial: bool = False) -> xr.DataArray:
        """
        Select the shared anomaly values used by the charts and maps.

        Args:
            unit: "%" for relative anomalies or "mm" for corrected rainfall differences.
            spatial: Select grid-cell anomalies instead of per-model basin anomalies.

        Returns:
            Anomalies on model/time and, for maps, latitude/longitude dimensions.

        Raises:
            ValueError: If units are unsupported or anomalies have no usable finite values.

        """
        if unit not in {"%", "mm"}:
            msg = 'unit must be "%" or "mm".'
            raise ValueError(msg)
        suffix = "pct" if unit == "%" else "mm"
        forecast = self._forecast_data()
        prefix = "" if spatial else "basin_"
        dataset = self.data["map"] if spatial else forecast
        anomaly = dataset[f"{prefix}anomaly_{suffix}"]
        # A regional map is checked after cropping, so remote missing/dry cells do
        # not invalidate an otherwise usable local view.
        if not spatial and (np.isinf(anomaly).any() or not np.isfinite(anomaly).any()):
            msg = "Anomalies contain infinities or no finite values; check forecast/hindcast data."
            raise ValueError(msg)
        return anomaly

    @staticmethod
    def _style_anomaly_chart(
        fig: go.Figure,
        anomaly: xr.DataArray,
        unit: str,
        *,
        show_median: bool,
    ) -> go.Figure:
        """
        Apply common anomaly labels and an optional prominent model median.

        Args:
            fig: Bar or boxplot figure containing the individual model values.
            anomaly: Per-model basin anomalies, in the requested unit.
            unit: "%" or "mm" for axis and hover labels.
            show_median: Add the median of basin anomalies as a black diamond line.

        Returns:
            Figure with a zero reference line and consistent monthly labels.

        """
        if show_median:
            fig.add_scatter(
                x=_month_labels(pd.DatetimeIndex(anomaly.time.to_numpy())),
                y=anomaly.median("model").to_numpy(),
                mode="lines+markers",
                name="Mediana dos modelos",
                line={"color": "black", "width": 3},
                marker={"color": "black", "symbol": "diamond", "size": 9},
                hovertemplate=f"Mês: %{{x}}<br>Mediana: %{{y:.1f}} {unit}<extra></extra>",
            )
        fig.update_layout(
            yaxis_title=f"Anomalia de precipitação ({unit})",
            xaxis_title="Mês",
            legend_title="Modelo",
            separators=",.",
            template="plotly_white",
            hovermode="x unified",
        )
        fig.add_hline(y=0, line_color="black", line_width=1)
        return fig

    def plot_raw_rainfall(self) -> Figure:
        """
        Compare observed rainfall and the uncorrected multi-model mean.

        Returns:
            Matplotlib figure with native observation timestamps and 20-day bars.
            Raw forecasts use 30-day-equivalent mm; current observations may be partial.

        """
        forecast = self._forecast_data()
        observed = self.data["observed"]["basin_mean"]
        climatology = self.data["climatology"]["basin_mean"]
        rain_raw = forecast["prec"].mean(dim=["latitude", "longitude", "model"])
        fig, ax = plt.subplots(figsize=(10, 5))
        # DatetimeIndex makes the width mean days rather than xarray nanoseconds.
        ax.plot(
            pd.DatetimeIndex(climatology.time.to_numpy()),
            climatology.to_numpy(),
            label="Média Mensal",
            color="orange",
        )
        ax.bar(
            pd.DatetimeIndex(observed.time.to_numpy()),
            observed.to_numpy(),
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

    def plot_rainfall_anomaly(self, unit: str = "%", *, show_median: bool = True) -> go.Figure:
        """
        Plot per-model basin anomalies, optionally emphasizing their monthly median.

        Args:
            unit: "%" for forecast/hindcast anomalies, or "mm" for corrected
                rainfall minus observed basin climatology.
            show_median: Subdue model bars and add a prominent black median line.

        Returns:
            Plotly grouped bars with model identities and basin-level anomalies.

        """
        anomaly = self._anomaly(unit)
        label = f"Anomalia ({unit})"
        table = anomaly.to_dataframe(name=label).reset_index()
        table["Mês"] = _month_labels(pd.DatetimeIndex(table["time"]))
        table["Modelo"] = table["model_name"]
        fig = px.bar(
            table,
            x="Mês",
            y=label,
            color="Modelo",
            barmode="group",
            title="Anomalia mensal de precipitação por modelo",
        )
        fig.update_traces(
            hovertemplate=(
                f"Mês: %{{x}}<br>Anomalia: %{{y:.1f}} {unit}<extra>%{{fullData.name}}</extra>"
            ),
        )
        if show_median:
            fig.update_traces(opacity=0.7)
        return self._style_anomaly_chart(fig, anomaly, unit, show_median=show_median)

    def plot_rainfall_anomaly_boxplot(
        self,
        unit: str = "%",
        *,
        show_median: bool = True,
        height: int = 700,
        yaxis_range: tuple[float, float] | None = None,
    ) -> go.Figure:
        """
        Plot monthly distributions of model basin anomalies and individual values.

        Args:
            unit: "%" for relative anomalies or "mm" relative to observed climatology.
            show_median: Add a prominent median line; intrinsic box medians remain visible.
            height: Figure height in pixels; defaults to 700 to give the model legend room.
            yaxis_range: Optional (minimum, maximum) in the selected unit, e.g.
                (-60, 60) for symmetric percentage limits. None uses automatic
                scaling. Values outside explicit limits are hidden, not changed.

        Returns:
            Plotly figure with one box per month and named, subtle model points.
            Each model contributes its ensemble-mean basin anomaly, not its members.

        Raises:
            ValueError: If height is not positive or the axis bounds are not increasing.

        """
        if height <= 0:
            msg = "height must be positive."
            raise ValueError(msg)
        if yaxis_range is not None and yaxis_range[0] >= yaxis_range[1]:
            msg = "yaxis_range must contain increasing (minimum, maximum) bounds."
            raise ValueError(msg)
        anomaly = self._anomaly(unit)
        fig = go.Figure()
        for i, date in enumerate(anomaly.time.to_numpy()):
            values = anomaly.sel(time=date).to_numpy()
            fig.add_box(
                x=_month_labels(pd.DatetimeIndex([date])) * len(values),
                y=values,
                name="Distribuição dos modelos",
                legendgroup="distribution",
                showlegend=(i == 0),
                boxpoints=False,
                line={"color": "gray"},
                fillcolor="rgba(128,128,128,0.15)",
                hovertemplate=f"Anomalia: %{{y:.1f}} {unit}<extra>Distribuição dos modelos</extra>",
            )
        for i, model in enumerate(anomaly.model.to_numpy()):
            fig.add_scatter(
                x=_month_labels(pd.DatetimeIndex(anomaly.time.to_numpy())),
                y=anomaly.sel(model=model).to_numpy(),
                mode="markers",
                name=str(anomaly.model_name.sel(model=model).item()),
                marker={"color": px.colors.qualitative.Plotly[i % 10], "size": 6, "opacity": 0.55},
                hovertemplate=(
                    f"Mês: %{{x}}<br>Anomalia: %{{y:.1f}} {unit}<extra>%{{fullData.name}}</extra>"
                ),
            )
        fig.update_layout(
            title="Distribuição das anomalias mensais de precipitação",
            height=height,
            yaxis_range=yaxis_range,
        )
        return self._style_anomaly_chart(fig, anomaly, unit, show_median=show_median)

    @staticmethod
    def _map_view(
        anomaly: xr.DataArray,
        extent: tuple[float, float, float, float],
        resample_factor: int,
    ) -> xr.DataArray:
        """
        Crop a regional anomaly field and optionally interpolate its display grid.

        Args:
            anomaly: Selected model or cellwise median on the native forecast grid.
            extent: View bounds (west, south, east, north), in the raster CRS.
            resample_factor: Integer row/column multiplier; one retains native cells.

        Returns:
            A temporary view with a one-cell halo. Bilinear interpolation changes
            only this display array; missing cells remain missing and coordinates
            stay within the native domain without extrapolation.

        Raises:
            ValueError: If the view contains infinities or has no finite values.

        """
        west, south, east, north = extent
        dx = abs(float(anomaly.longitude.diff("longitude").median()))
        dy = abs(float(anomaly.latitude.diff("latitude").median()))
        # A halo brackets viewport edges so interpolation does not leave an empty rim.
        view = anomaly.where(
            (anomaly.longitude >= west - dx)
            & (anomaly.longitude <= east + dx)
            & (anomaly.latitude >= south - dy)
            & (anomaly.latitude <= north + dy),
            drop=True,
        )
        if np.isinf(view).any() or not np.isfinite(view).any():
            msg = "The map extent contains infinities or no finite anomalies; check input data."
            raise ValueError(msg)
        if resample_factor > 1:
            view = view.interp(
                longitude=np.linspace(
                    float(view.longitude.min()),
                    float(view.longitude.max()),
                    resample_factor * view.sizes["longitude"],
                ),
                latitude=np.linspace(
                    float(view.latitude.min()),
                    float(view.latitude.max()),
                    resample_factor * view.sizes["latitude"],
                ),
                method="linear",
            )
        return view

    def plot_rainfall_anomaly_map(  # noqa: PLR0915 -- keep map layers and their extent explicit
        self,
        unit: str = "%",
        model: str = "median",
        *,
        states: gpd.GeoDataFrame | None = None,
        extent_scale: float = 1.2,
        resample_factor: int = 2,
    ) -> Figure:
        """
        Plot regional anomalies, state context, and the basin boundary by month.

        Args:
            unit: "%" for forecast/hindcast anomalies, or "mm" using observed
                climatology averaged onto the native regional forecast grid.
            model: Originating-centre ID or "median" for native cellwise medians.
                Display labels use full model names, while selection retains IDs.
            states: Optional state polygons with CRS and a SIGLA_UF abbreviation
                column. Load explicitly before plotting; no vector files are read here.
            extent_scale: Multiplier of basin width/height, at least one. A value
                of 1.2 adds ten percent of the original span on each side.
            resample_factor: Positive integer display-grid multiplier. Two uses
                bilinear interpolation to double rows/columns; one keeps native pixels.

        Returns:
            Monthly Matplotlib panels with a common red-white-blue scale: deficits
            are red and surpluses blue. Real surrounding cells are shown, including
            outside the basin. Interpolation affects only visualization; prepared
            datasets and basin summaries retain their original native-grid values.

        Raises:
            ValueError: If the model, extent scale, or resampling factor is invalid.

        """
        if not np.isfinite(extent_scale) or extent_scale < 1:
            msg = "extent_scale must be finite and at least 1."
            raise ValueError(msg)
        if not isinstance(resample_factor, int) or resample_factor < 1:
            msg = "resample_factor must be a positive integer."
            raise ValueError(msg)
        anomaly = self._anomaly(unit, spatial=True)
        if model == "median":
            # Select the native cellwise statistic before interpolating its display.
            anomaly = anomaly.median("model")
            selection = "Mediana pontual dos modelos"
        elif model in anomaly.model.to_numpy():
            anomaly = anomaly.sel(model=model)
            selection = str(anomaly.model_name.item())
        else:
            msg = (
                f"Unknown model {model!r}; choose 'median' or {anomaly.model.to_numpy().tolist()}."
            )
            raise ValueError(msg)
        basin = self.basin.to_crs(anomaly.rio.crs)
        west, south, east, north = basin.total_bounds
        cx, cy = (west + east) / 2, (south + north) / 2
        half_width, half_height = (
            (east - west) * extent_scale / 2,
            (north - south) * extent_scale / 2,
        )
        extent = (cx - half_width, cy - half_height, cx + half_width, cy + half_height)
        view = self._map_view(anomaly, extent, resample_factor)
        limit = float(abs(view).max()) or 1.0
        norm = TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit)
        visible_states = states.to_crs(anomaly.rio.crs) if states is not None else None
        labels: list[tuple[str, float, float]] = []
        if visible_states is not None:
            viewport = box(*extent)
            visible_states = visible_states.loc[visible_states.intersects(viewport)]
            points = visible_states.geometry.intersection(viewport).representative_point()
            labels = [
                (str(name), float(point.coords[0][0]), float(point.coords[0][1]))
                for name, point in zip(visible_states["SIGLA_UF"], points, strict=True)
            ]
        count = view.sizes["time"]
        columns = min(2, count)
        rows = (count + columns - 1) // columns
        fig, axes = plt.subplots(
            rows,
            columns,
            figsize=(6 * columns, 5 * rows),
            squeeze=False,
            sharex=True,
            sharey=True,
            layout="constrained",
        )
        used_axes = []
        for i, month in enumerate(_month_labels(pd.DatetimeIndex(view.time.to_numpy()))):
            ax = axes.flat[i]
            mesh = ax.pcolormesh(
                view.longitude.to_numpy(),
                view.latitude.to_numpy(),
                view.isel(time=i).transpose("latitude", "longitude").to_numpy(),
                cmap="bwr_r",
                norm=norm,
                shading="auto",
            )
            if visible_states is not None and not visible_states.empty:
                visible_states.boundary.plot(ax=ax, color="0.35", linewidth=0.6)
            basin.boundary.plot(ax=ax, color="black", linewidth=1.5)
            for name, x, y in labels:
                # Keep UF text inside the viewport when only a state sliver is visible.
                alignment = "center"
                if abs(x - cx) > 0.9 * half_width:
                    alignment = "right" if x > cx else "left"
                ax.text(
                    x,
                    y,
                    name,
                    fontsize=9,
                    ha=alignment,
                    va="center",
                    clip_on=True,
                    bbox={"facecolor": "white", "alpha": 0.7, "edgecolor": "none", "pad": 1},
                )
            # Vector plotting can expand limits to whole states; restore the chosen view.
            ax.set(
                title=month,
                xlabel="Longitude",
                ylabel="Latitude",
                xlim=(extent[0], extent[2]),
                ylim=(extent[1], extent[3]),
            )
            used_axes.append(ax)
        for ax in list(axes.flat)[count:]:
            ax.set_visible(False)
        fig.colorbar(mesh, ax=used_axes, label=f"Anomalia de precipitação ({unit})", shrink=0.85)
        fig.suptitle(f"{self.name} — {selection}\nAnomalia de precipitação ({unit})")
        if resample_factor > 1:
            fig.supxlabel(
                f"Interpolação bilinear {resample_factor}x apenas para visualização",
                fontsize=9,
            )
        return fig

    def plot_forecast_rainfall(self) -> go.Figure:
        """
        Plot corrected basin rainfall against observations and climatology.

        Returns:
            Plotly figure in calendar-month mm with corrected basin median and model
            spread. Each box contains one ensemble-mean value per forecast centre.

        """
        forecast = self._forecast_data()
        return plot_rainfall_comparison(
            self.data["observed"]["basin_mean"],
            self.data["climatology"]["basin_mean"],
            forecast["basin_corrected"],
            title=f"{self.name} - Precipitação mensal: observações e previsão corrigida",
        )
