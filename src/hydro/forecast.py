"""Data loading and chart helpers for the monthly inference demonstration."""

from __future__ import annotations

import math
from itertools import pairwise
from typing import TYPE_CHECKING

import pandas as pd
import plotly.graph_objects as go
import rioxarray  # noqa: F401 -- register the spatial xarray accessor
import xarray as xr
from mergedownloader.utils import GISUtil

if TYPE_CHECKING:
    from pathlib import Path

    import geopandas as gpd


MONTH_LABELS = (
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
)


def load_forecast_grids(
    folder: Path,
    initialization: pd.Timestamp,
    models: list[str],
    basin: gpd.GeoDataFrame | None,
) -> xr.Dataset:
    """
    Read notebook 03's monthly forecast/hindcast grids for one basin.

    Args:
        folder: Forecast root containing prec/ and hindcast/ NetCDF files.
        initialization: First day of the CDS initialization month.
        models: Originating centres; the first supplies the reference spatial grid.
        basin: Upstream polygon geometry with its CRS, or None to retain the
            complete downloaded domain for regional visualization.

    Returns:
        Dataset with prec and hindcast in the stored 30-day-equivalent mm/month,
        on model/time/latitude/longitude dimensions. Stored timedelta leads mark
        accumulation period ends; time labels the corresponding month start.

    """
    variables = {}
    for variable in ("prec", "hindcast"):
        arrays: list[xr.DataArray] = []
        for centre in models:
            path = folder / variable / f"{centre}_{initialization:%Y%m}.nc2"
            with xr.open_dataset(path) as dataset:
                array = dataset["tprate"].load()
            # Keep the original first-model grid and linear interpolation convention.
            if arrays:
                array = array.interp(
                    latitude=arrays[0].latitude,
                    longitude=arrays[0].longitude,
                )
            arrays.append(array)
        combined = xr.concat(arrays, dim=pd.Index(models, name="model"), join="exact")
        # E.g. September initialization + 30 days is October 1: September's total.
        period_ends = initialization + pd.to_timedelta(combined.step.values)
        months = (period_ends - pd.Timedelta(days=1)).to_period("M").to_timestamp()
        combined = combined.rename(step="time").assign_coords(time=months)
        combined = combined.rio.write_crs("EPSG:4326")
        variables[variable] = (
            GISUtil.cut_cube_by_geoms(combined, basin.geometry) if basin is not None else combined
        )
    # An exact alignment prevents missing leads being introduced by an outer join.
    prec, hindcast = xr.align(variables["prec"], variables["hindcast"], join="exact")
    return xr.Dataset({"prec": prec, "hindcast": hindcast})


def plot_rainfall_comparison(
    observed: xr.DataArray,
    climatology: xr.DataArray,
    corrected: xr.DataArray,
    *,
    title: str,
) -> go.Figure:
    """
    Plot monthly basin rainfall with the original multi-model boxplots.

    Args:
        observed: Online observed totals in mm on time, possibly partial this month.
        climatology: Historical monthly reference in mm on time.
        corrected: Corrected rainfall in mm on model/time.
        title: Station-specific chart title.

    Returns:
        Figure with climatology, observed totals, forecast median and model spread.

    """
    day_ms = 24 * 60 * 60 * 1000
    fig = go.Figure()
    fig.add_scatter(
        x=climatology.time.values,
        y=climatology.values,
        mode="lines",
        name="Média mensal",
        line={"color": "darkorange", "width": 3},
    )
    fig.add_bar(
        x=corrected.time.values,
        y=corrected.median("model").values,
        name="Previsão (mediana)",
        marker_color="lightgray",
        width=20 * day_ms,
    )
    fig.add_bar(
        x=observed.time.values,
        y=observed.values,
        name="Observado",
        marker_color="steelblue",
        width=20 * day_ms,
    )
    for i, date in enumerate(corrected.time.values):
        values = corrected.sel(time=date).to_numpy()
        fig.add_box(
            x=[pd.Timestamp(date)] * len(values),
            y=values,
            name="Distribuição dos modelos",
            width=12 * day_ms,
            marker={"color": "dimgray", "size": 5, "opacity": 0.8},
            line={"color": "black", "width": 1.5},
            fillcolor="rgba(100,100,100,0.25)",
            boxpoints="all",
            jitter=0,
            pointpos=0,
            showlegend=(i == 0),
            hovertemplate="%{y:.1f} mm<extra></extra>",
        )
    fig.update_layout(
        title=title,
        xaxis_title="",
        yaxis_title="Precipitação (mm)",
        template="plotly_white",
        hovermode="closest",
        barmode="overlay",
        boxmode="overlay",
        legend={"orientation": "h", "y": 1.12, "x": 0},
        height=550,
        bargap=0.25,
    )
    fig.update_yaxes(rangemode="tozero", showgrid=True, gridcolor="rgba(0,0,0,0.08)")
    return fig


def plot_discharge_comparison(
    observed: pd.Series,
    simulated: pd.DataFrame,
    daily_stats: pd.DataFrame,
    monthly_median: pd.Series,
    *,
    colors: dict[int, str],
    forecast_steps: int,
    act: int,
    as_of: pd.Timestamp,
) -> go.Figure:
    """
    Render notebook 04's rolling 12-month discharge comparison.

    Preserve its calendar-year overlays, cross-year connectors and pooled-daily
    monthly median. Historical percentiles are not forecast uncertainty bounds.

    Args:
        observed: Online daily discharge in m³/s with a DatetimeIndex.
        simulated: Monthly m³/s on model dates, with climatology/forecast columns.
        daily_stats: Median, p10 and p90 indexed by (calendar month, day).
        monthly_median: Median of daily discharge grouped by calendar month, m³/s.
        colors: Calendar years and their display colors, in legend order.
        forecast_steps: Number of future rainfall months shown by notebook 04.
        act: Calibrated monthly concentration lag; includes antecedent output points.
        as_of: Reference date for the vertical line.

    Returns:
        Figure matching the original chart conventions. Simulated markers are
        placed 14 days after model timestamps without changing the input data.

    """
    chart_discharge = simulated.copy()
    chart_discharge.index = chart_discharge.index + pd.DateOffset(days=14)
    end_month = chart_discharge.index.max().replace(day=1)
    start_date = end_month - pd.DateOffset(months=11)
    end_date = end_month + pd.DateOffset(months=1)
    dates = pd.date_range(start_date, end_date - pd.Timedelta(days=1), freq="D")
    calendar = pd.MultiIndex.from_arrays([dates.month, dates.day])
    stats = daily_stats.reindex(calendar).set_axis(dates, axis=0)
    boundaries = pd.date_range(start_date, end_date, freq="MS")
    centers = boundaries[:-1] + (boundaries[1:] - boundaries[:-1]) / 2

    fig = go.Figure()
    fig.add_scatter(
        x=dates,
        y=stats["p10"],
        mode="lines",
        line={"width": 0},
        showlegend=False,
        hoverinfo="skip",
    )
    fig.add_scatter(
        x=dates,
        y=stats["p90"],
        mode="lines",
        name="P10–P90 histórico",  # noqa: RUF001 -- preserve the original chart label
        line={"width": 0},
        fill="tonexty",
        fillcolor="rgba(128,128,128,0.15)",
        hoverinfo="skip",
    )
    fig.add_scatter(
        x=dates,
        y=stats["median"],
        mode="lines",
        name="Mediana histórica",
        line={"color": "royalblue", "dash": "dash", "width": 1},
        opacity=0.35,
    )
    # Preserve calendar-year segments exactly; changing to seasons would change the chart.
    observed_dates = pd.DatetimeIndex(observed.index)
    for year, color in colors.items():
        annual = observed.loc[observed_dates.year == year]
        annual = annual[~((annual.index.month == 2) & (annual.index.day == 29))]  # noqa: PLR2004 -- leap day
        segments = [
            annual[annual.index.month >= start_date.month],
            annual[annual.index.month < start_date.month],
        ]
        for i, segment in enumerate(segments):
            if segment.empty:
                continue
            target_year = start_date.year if i == 0 else end_date.year
            mapped = [date.replace(year=target_year) for date in segment.index]
            fig.add_scatter(
                x=mapped,
                y=segment.values,
                mode="lines",
                name=str(year),
                legendgroup=str(year),
                showlegend=(i == 0),
                line={"color": color, "width": 2 if year == max(colors) else 1},
            )

    boundary = pd.Timestamp(start_date.year + 1, 1, 1)
    if start_date < boundary < end_date:
        # These connectors intentionally retain notebook 04's cross-year convention.
        for year, color in colors.items():
            if year + 1 not in colors:
                continue
            december = observed[(observed_dates.year == year) & (observed_dates.month == 12)]  # noqa: PLR2004 -- December
            january = observed[(observed_dates.year == year + 1) & (observed_dates.month == 1)]
            if december.empty or january.empty:
                continue
            fig.add_scatter(
                x=[
                    pd.Timestamp(december.index[-1]).replace(year=boundary.year - 1),
                    pd.Timestamp(january.index[0]).replace(year=boundary.year),
                ],
                y=[december.iloc[-1], january.iloc[0]],
                mode="lines",
                line={"color": color, "width": 1},
                showlegend=False,
                hoverinfo="skip",
            )

    # Broken horizontal segments retain the original monthly reference presentation.
    line_dates = []
    line_values = []
    for left, right in pairwise(boundaries):
        value = monthly_median.loc[left.month]
        line_dates.extend([left, right, None])
        line_values.extend([value, value, None])
    fig.add_scatter(
        x=line_dates,
        y=line_values,
        mode="lines",
        name="Mediana mensal",
        line={"color": "orange", "width": 1, "dash": "dot"},
    )
    fig.add_scatter(
        x=centers,
        y=monthly_median.reindex(boundaries[:-1].month).values,
        mode="markers",
        marker={"color": "orange", "size": 6},
        showlegend=False,
    )
    scenarios = {
        "climatology": ("Previsão (chuva média)", "purple"),
        "forecast": ("Previsão (chuva prevista)", "red"),
    }
    for column, (label, color) in scenarios.items():
        series = chart_discharge[column].iloc[-(forecast_steps + act) :]
        fig.add_scatter(
            x=series.index,
            y=series.values,
            mode="lines+markers",
            name=label,
            line={"color": color, "width": 2, "dash": "dash"},
            marker={"color": color, "size": 9, "symbol": "circle"},
            hovertemplate="%{x|%b %Y}<br>Vazão: %{y:,.0f} m³/s<extra></extra>",
        )
    if start_date <= as_of < end_date:
        fig.add_vline(x=as_of, line={"color": "gray", "width": 1, "dash": "dot"})
        fig.add_annotation(
            x=as_of,
            y=1,
            yref="paper",
            text="Dia atual (hoje)",
            showarrow=False,
            textangle=-90,
            xanchor="right",
            yanchor="top",
            font={"color": "gray", "size": 11},
        )
    for date in boundaries:
        fig.add_shape(
            type="line",
            x0=date,
            x1=date,
            y0=0,
            y1=-0.015,
            yref="paper",
            line={"color": "black", "width": 1},
        )
    fig.update_layout(
        title="Vazão observada e prevista — janela móvel de 12 meses",
        width=1200,
        height=600,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin={"b": 65},
        xaxis={
            "title": "",
            "showline": True,
            "linecolor": "black",
            "mirror": True,
            "range": [start_date, end_date],
            "tickmode": "array",
            "tickvals": centers,
            "ticktext": centers.strftime("%b"),
            "ticks": "",
            "tickfont": {"size": 12},
            "showgrid": False,
        },
        yaxis={
            "title": "Vazão (m³/s)",
            "showline": True,
            "linecolor": "black",
            "mirror": True,
            "rangemode": "tozero",
        },
        legend={"orientation": "v", "x": 1.02, "y": 1},
        hovermode="closest",
    )
    return fig


def monthly_discharge_window(
    current: pd.Timestamp,
    forecast_dates: pd.DatetimeIndex,
    months_each_side: int,
    *,
    centered: bool,
) -> pd.DatetimeIndex:
    """
    Calculate the display calendar for the centered or calendar-year view.

    Args:
        current: First day of the reference month.
        forecast_dates: Available ACT-adjusted month starts on or after current.
        months_each_side: Minimum number of months on each side of a centered window.
        centered: Use a symmetric window including the forecast horizon.

    Returns:
        Month-start index covering the display window.

    """
    last_forecast = forecast_dates.max()
    if centered:
        # Expand both sides equally when the ACT-adjusted horizon extends the view.
        lead = (last_forecast.year - current.year) * 12 + last_forecast.month - current.month
        radius = max(months_each_side, int(lead)) if pd.notna(last_forecast) else months_each_side
        start = current - pd.DateOffset(months=radius)
        end = current + pd.DateOffset(months=radius)
    else:
        start = pd.Timestamp(current.year, 1, 1)
        end = pd.Timestamp(current.year, 12, 1)
    return pd.date_range(start, end, freq="MS")


def add_monthly_scenario(
    figure: go.Figure,
    series: pd.Series,
    *,
    current: pd.Timestamp,
    centered: bool,
    label: str,
    color: str,
    hover: str,
) -> None:
    """
    Plot a monthly scenario, breaking the line at New Year in the calendar view.

    Args:
        figure: Figure receiving the scenario traces.
        series: Month-start discharge in m³/s, with any visual offset applied.
        current: First day of the reference month, plotted at zero.
        centered: Plot continuous dates or fold them onto January through December.
        label: Scenario name shared by all segments.
        color: Plotly color of the scenario.
        hover: Template containing actual source dates and discharge units.

    """
    dates = pd.DatetimeIndex(series.index)
    # Separate traces prevent a diagonal line from December back to January.
    periods = [series] if centered else [values for _, values in series.groupby(dates.year)]
    for i, values in enumerate(periods):
        dates = pd.DatetimeIndex(values.index)
        positions = dates.month - current.month
        if centered:
            positions += (dates.year - current.year) * 12
        figure.add_scatter(
            x=positions.tolist(),
            y=values,
            text=[f"{MONTH_LABELS[date.month - 1]}/{date.year}" for date in dates],
            mode="lines+markers",
            name=label,
            legendgroup=label,
            showlegend=i == 0,
            line={"color": color, "width": 2, "dash": "dash"},
            marker={"size": 8},
            hovertemplate=hover,
            connectgaps=False,
        )


def add_monthly_observation_years(
    figure: go.Figure,
    observed: pd.DataFrame,
    months: pd.DatetimeIndex,
    positions: list[int],
    *,
    current: pd.Timestamp,
    previous_years: int,
    hover: str,
) -> None:
    """
    Plot the current year on its own dates and prior years by calendar month.

    Args:
        figure: Figure receiving the observation traces.
        observed: Month-start mean discharge in m³/s and valid daily counts.
        months: Month starts covered by the display window.
        positions: Equally spaced positions for the display window.
        current: First day of the reference month. Its mean uses data through cutoff.
        previous_years: Number of prior years to include, up to three.
        hover: Template with date and discharge.

    """
    observed_dates = pd.DatetimeIndex(observed.index)
    for years_ago, color in (
        (3, "#a75f20"),
        (2, "green"),
        (1, "blue"),
        (0, "black"),
    ):
        if years_ago > previous_years:
            continue
        year = current.year - years_ago
        annual = observed.loc[(observed_dates.year == year) & (observed_dates <= current)]
        by_month = annual.set_axis(pd.DatetimeIndex(annual.index).month, axis="index")
        # Match source calendar months to display slots regardless of the displayed year.
        # Split at the calendar wrap instead of connecting December to that same year's January.
        for segment, display_year in enumerate(months.year.unique()):
            mask = months.year == display_year
            calendar = months[mask]
            values = (
                annual.reindex(calendar)
                if year == current.year
                else by_month.reindex(calendar.month)
            )
            figure.add_scatter(
                x=[position for position, show in zip(positions, mask, strict=True) if show],
                y=values["mean"],
                text=[f"{MONTH_LABELS[date.month - 1]}/{year}" for date in calendar],
                customdata=values["count"],
                mode="lines+markers",
                name=str(year),
                legendgroup=str(year),
                showlegend=display_year == year if year == current.year else segment == 0,
                line={
                    "color": color,
                    "width": 2.5 if year == current.year else 1.5,
                    "dash": "solid",
                },
                marker={"size": 6 if year == current.year else 4},
                opacity=1 if year == current.year else 0.65,
                connectgaps=False,
                hovertemplate=hover.replace("<extra>", "<br>%{customdata} dias com dados<extra>"),
            )
        if year < current.year:
            # Join consecutive real months across the wrap, never December to its own January.
            endpoints = pd.to_datetime([f"{year}-12-01", f"{year + 1}-01-01"])
            bridge = observed.loc[observed.index < current, "mean"].reindex(endpoints)
            if bridge.notna().all():
                for position, month in zip(positions[1:], months[1:], strict=True):
                    if month.month == 1:
                        figure.add_scatter(
                            x=[position - 1, position],
                            y=bridge.values,
                            mode="lines",
                            line={"color": color, "width": 1.5, "dash": "solid"},
                            opacity=0.65,
                            legendgroup=str(year),
                            showlegend=False,
                            hoverinfo="skip",
                        )


def plot_monthly_discharge_comparison(
    observed: pd.DataFrame,
    simulated: pd.DataFrame,
    monthly_stats: pd.DataFrame,
    *,
    as_of: pd.Timestamp,
    months_each_side: int,
    anchor_to_observed: bool = False,
    centered: bool = True,
    previous_years: int = 2,
) -> go.Figure:
    """
    Plot monthly means and historical percentiles on a centered monthly calendar.

    Args:
        observed: Month-start mean discharge in m³/s and valid daily count.
        simulated: Month-start discharge in m³/s with climatology/forecast columns.
            Model concentration lags are already included in these timestamps.
        monthly_stats: Median, p10, p90 and count of historical monthly means,
            indexed by calendar month. Excludes the as-of month and later data.
        as_of: Reference date; its month is the center of the chart.
        months_each_side: Calendar months shown before and after the central month.
        anchor_to_observed: Apply a scenario-specific constant offset in m³/s,
            equal to the partial observed mean minus the reference-month prediction.
            Requires observations and predictions for that same month. Only plotted
            forecasts change; no clipping or modification of simulated is performed.
        centered: Use a symmetric window or fold forecast dates onto the
            January-to-December axis, breaking curves at year boundaries.
        previous_years: Include up to this many of the three prior observation years.

    Returns:
        Figure with equally spaced month slots, a historical P10-P90 band and
        separate observations and forecast scenarios. Missing months remain gaps.
        Previous years align by calendar month. In the centered view, December
        connects to January of the following source year when available.
        The reference year ends at the mean through the observation cutoff.

    """
    current = as_of.to_period("M").to_timestamp()
    future = simulated.loc[simulated.index >= current].dropna(how="all")
    months = monthly_discharge_window(
        current, pd.DatetimeIndex(future.index), months_each_side, centered=centered
    )
    reference_index = months.tolist().index(current)
    # Equal slots keep the reference month centered despite unequal month lengths.
    positions = list(range(-reference_index, len(months) - reference_index))
    labels = [f"{MONTH_LABELS[date.month - 1]}/{date.year}" for date in months]
    stats = monthly_stats.reindex(months.month)
    obs = observed.reindex(months)
    observed_mean = float(obs["mean"].astype(float).iloc[reference_index])
    prediction_months = months
    if not centered and not future.empty:
        prediction_months = pd.date_range(current, future.index[-1], freq="MS")
    predictions = future.reindex(prediction_months)
    if anchor_to_observed:
        reference = predictions.reindex([current]).iloc[0]
        if not math.isfinite(observed_mean) or reference.isna().any():
            msg = "Anchoring requires observed and predicted discharge in the reference month."
            raise ValueError(msg)
        # A constant additive correction preserves each scenario's month-to-month changes.
        offsets = observed_mean - reference
        predictions = predictions + offsets
    hover = "%{text}<br>%{y:,.0f} m³/s<extra>%{fullData.name}</extra>"
    fig = go.Figure()
    fig.add_scatter(
        x=positions,
        y=stats["p10"],
        mode="lines",
        line={"width": 0},
        showlegend=False,
        hoverinfo="skip",
        connectgaps=False,
    )
    fig.add_scatter(
        x=positions,
        y=stats["p90"],
        mode="lines",
        line={"width": 0},
        name="P10-P90 histórico (médias mensais)",
        fill="tonexty",
        fillcolor="rgba(156,156,156,0.20)",
        hoverinfo="skip",
        connectgaps=False,
    )
    fig.add_scatter(
        x=positions,
        y=stats["median"],
        text=labels,
        mode="lines",
        name="Mediana histórica mensal",
        line={"color": "gray", "dash": "dash", "width": 1},
        opacity=0.6,
        customdata=stats["count"],
        connectgaps=False,
        hovertemplate=hover.replace("<extra>", "<br>%{customdata} meses históricos<extra>"),
    )
    add_monthly_observation_years(
        fig,
        observed,
        months,
        positions,
        current=current,
        previous_years=previous_years,
        hover=hover,
    )
    if math.isfinite(observed_mean):
        fig.add_scatter(
            x=[0],
            y=[observed_mean],
            text=[labels[reference_index]],
            customdata=[obs.loc[current, "count"]],
            mode="markers",
            name=f"Observado (até {as_of:%d/%m})",
            marker={"color": "black", "size": 11, "symbol": "circle-open"},
            hovertemplate=hover.replace("<extra>", "<br>%{customdata} dias com dados<extra>"),
        )
    for column, label, color in (
        ("climatology", "Previsão (chuva média)", "purple"),
        ("forecast", "Previsão (chuva prevista)", "red"),
    ):
        forecast_hover = hover
        if anchor_to_observed:
            forecast_hover = hover.replace(
                "<extra>",
                f"<br>ΔQ: {offsets[column]:+,.0f} m³/s<extra>",
            )
        add_monthly_scenario(
            fig,
            predictions[column],
            current=current,
            centered=centered,
            label=f"{label} (ancorada)" if anchor_to_observed else label,
            color=color,
            hover=forecast_hover,
        )
    fig.add_vline(x=0, line_dash="dot", line_color="gray")
    fig.add_annotation(
        x=0,
        y=1,
        yref="paper",
        text=f"{as_of:%m/%Y}",
        showarrow=False,
        yanchor="bottom",
    )
    fig.update_layout(
        title="Vazão média mensal observada e prevista",
        template="plotly_white",
        height=600,
        xaxis={
            "title": "",
            "tickmode": "array",
            "tickvals": positions,
            "ticktext": [
                f"{MONTH_LABELS[date.month - 1]}<br>{date.year}"
                if centered and (i == 0 or date.month == 1)
                else MONTH_LABELS[date.month - 1]
                for i, date in enumerate(months)
            ],
            "range": [positions[0] - 0.5, positions[-1] + 0.5],
        },
        yaxis={"title": "Vazão média mensal (m³/s)", "rangemode": "tozero"},
        legend={"orientation": "h", "y": -0.2, "x": 0},
        margin={"b": 120, "t": 100},
        hovermode="x unified",
    )
    return fig
