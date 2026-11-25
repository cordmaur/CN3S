"""Calendar-day climatology and whole-record hydrological exceedances."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import matplotlib.dates as mdates
import pandas as pd

from .hydro_stats import HydroStats

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from .hidro import Source
    from .station import DataSanitization, Station

Method = Literal["direct", "from_discharge"]
LEAP_DAY = (2, 29)
PERCENTAGES = (5, 10, 25, 50, 75, 90, 95)
DEFAULT_PERIOD = slice(None)
DEFAULT_RESULTS_DIR = Path("/data/CN3S/Exceedance")
TABLE_NAMES = ("daily_curve", "exceedance_curve", "stats", "summary", "station_stats")
RESULT_FILES = (*(f"{name}.parquet" for name in TABLE_NAMES), "metadata.json")
SCHEMA_VERSION = 1


def default_thresholds() -> dict[str, float | None]:
    """Return editable stage limits in cm; None means not yet specified."""
    return {"Cota de Alerta": None, "Cota de Inundação": None}


def statistic_column(variable: str, statistic: str | int) -> str:
    """
    Name a flat column using Brazilian exceedance notation.

    Args:
        variable: Q, C, or C_from_Q.
        statistic: Exceedance percentage or min/max/mean/count.

    Returns:
        Column such as Q95, C_mean, or C95_from_Q.

    """
    prefix = "Q" if variable == "Q" else "C"
    suffix = "_from_Q" if variable == "C_from_Q" else ""
    middle = str(statistic) if isinstance(statistic, int) else f"_{statistic}"
    return f"{prefix}{middle}{suffix}"


def calculate_tables(
    frame: pd.DataFrame, variable: str
) -> tuple[pd.DataFrame, pd.Series, dict[str, float]]:
    """
    Summarize one daily observation record without filling missing dates.

    Args:
        frame: Valid observations indexed by date, with a val column.
        variable: Q (m³/s), C (cm), or C_from_Q (cm).

    Returns:
        Calendar-day statistics, whole-record exceedances, and named summary.

    """
    values = frame["val"]
    # A non-leap reference calendar guarantees 365 rows without shifting March.
    calendar = pd.date_range("2001-01-01", "2001-12-31")
    index = pd.MultiIndex.from_arrays([calendar.month, calendar.day], names=["month", "day"])
    dates = pd.DatetimeIndex(values.index)
    grouped = values.groupby([dates.month, dates.day])
    daily = grouped.agg(["min", "max", "mean", "count"]).reindex(index)
    daily["count"] = daily["count"].fillna(0).astype(int)
    summary: dict[str | int, float] = {
        name: getattr(values, name)() for name in ("min", "max", "mean", "count")
    }
    # Whole-record statistics include leap day and weight every valid observation equally.
    curve = values.quantile([1 - p / 100 for p in range(1, 101)], interpolation="linear")
    curve.index = pd.Index(range(1, 101), name="exceedance_pct")
    for percentage in PERCENTAGES:
        daily[percentage] = grouped.quantile(1 - percentage / 100, interpolation="linear").reindex(
            index
        )
        summary[percentage] = curve.loc[percentage]
    daily.columns = [statistic_column(variable, name) for name in daily.columns]
    return (
        daily,
        curve,
        {statistic_column(variable, name): value for name, value in summary.items()},
    )


def describe_record(frame: pd.DataFrame, stats: dict[str, Any]) -> str:
    """
    Describe the actual sample coverage and source proportions.

    Args:
        frame: Valid daily observations with optional source labels.
        stats: Coverage statistics for this same record.

    Returns:
        Human-readable provenance for chart subtitles.

    """
    if frame.empty:
        return "Sem observações disponíveis"
    sources = (
        "/".join(
            f"{name}({100 * count / len(frame):.1f}%)"
            for name, count in frame.groupby("Sistema", observed=True).size().items()
        )
        if "Sistema" in frame
        else ""
    )
    metrics = " ".join(
        f"{name}:{stats[name]}" for name in ("Inicio", "Fim", "Anos", "Falhas (%)", "Consist (%)")
    )
    return f"{sources.upper()} - {metrics}"


@dataclass
class ExceedanceResult:
    """Persist all three variables and chart settings independently of live observations."""

    station_code: int
    station_name: str
    daily_curve: pd.DataFrame
    exceedance_curve: pd.DataFrame
    stats: pd.DataFrame
    summary: pd.DataFrame
    station_stats: pd.DataFrame
    source: Source
    period: dict[str, str | None]
    calculated_at: str
    descriptions: dict[str, str]
    coverage: dict[str, dict[str, str | None]]
    status: dict[str, str]
    sanitization: DataSanitization = field(default_factory=dict)
    thresholds: dict[str, float | None] = field(default_factory=default_thresholds)
    reference_exceedances: list[int] = field(default_factory=list)
    plot_method: Method = "from_discharge"

    def update_thresholds(self, thresholds: dict[str, float | None]) -> None:
        """
        Replace manual stage limits while retaining blank standard entries.

        Args:
            thresholds: Named levels in centimetres; None disables a line.

        """
        self.thresholds = default_thresholds() | thresholds

    def save(self, path: str | Path) -> None:
        """
        Save every scientific table and metadata to an exact station directory.

        Args:
            path: Destination directory, including the station code.

        """
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        for name in TABLE_NAMES:
            getattr(self, name).to_parquet(path / f"{name}.parquet")
        self.update_thresholds(self.thresholds)
        meta = {
            name: getattr(self, name)
            for name in (
                "station_code",
                "station_name",
                "source",
                "period",
                "calculated_at",
                "descriptions",
                "coverage",
                "status",
                "sanitization",
                "thresholds",
                "reference_exceedances",
                "plot_method",
            )
        }
        meta.update(
            schema_version=SCHEMA_VERSION,
            units={"Q": "m³/s", "C": "cm", "C_from_Q": "cm"},
            quantile_method="linear; quantile(1 - exceedance_pct / 100)",
            leap_day_policy="Excluded from daily calendar; included in whole-record statistics",
        )
        # Keep each original source separate; merged coverage can hide source gaps.
        meta["station_stats"] = [
            {
                "station_code": int(code),
                "source": row[("Fonte", "")],
                "cota": json.loads(row["cota"].to_json(force_ascii=False)),
                "vazao": json.loads(row["vazao"].to_json(force_ascii=False)),
            }
            for code, row in self.station_stats.iterrows()
        ]
        (path / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> ExceedanceResult:
        """
        Load references without database access or rating-curve calculations.

        Args:
            path: Directory containing the new scientific tables and metadata.json.

        Returns:
            Complete result including manual and computed chart references.

        """
        path = Path(path)
        if not (path / "metadata.json").exists() and (path / "curve.parquet").exists():
            msg = "Legacy daily curve: recalculate all variables into /data/CN3S/Exceedance."
            raise ValueError(msg)
        meta = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        if meta.pop("schema_version") != SCHEMA_VERSION:
            msg = "Unsupported exceedance result schema."
            raise ValueError(msg)
        for name in ("units", "quantile_method", "leap_day_policy", "station_stats"):
            meta.pop(name, None)
        meta.update({name: pd.read_parquet(path / f"{name}.parquet") for name in TABLE_NAMES})
        result = cls(**meta)
        result.update_thresholds(result.thresholds)
        return result

    def stage_variable(self, method: Method | None = None) -> str:
        """
        Resolve and check the stage variable used by either chart renderer.

        Args:
            method: Plot override; None uses the saved chart method.

        Returns:
            C for observed stage or C_from_Q for derived stage.

        """
        method = self.plot_method if method is None else method
        if method not in ("direct", "from_discharge"):
            msg = f"Unknown stage method: {method}"
            raise ValueError(msg)
        variable = "C" if method == "direct" else "C_from_Q"
        if not self.daily_curve[statistic_column(variable, "count")].any():
            msg = f"No {variable} references: {self.status[variable]}. Choose an available method."
            raise ValueError(msg)
        return variable

    def stage_references(
        self, method: Method | None = None, percentages: list[int] | None = None
    ) -> dict[str, float]:
        """
        Resolve whole-record stage references and nonblank manual limits.

        Args:
            method: Stage method; None uses the saved chart method.
            percentages: Plot-only selection of 5 and/or 95; None uses saved choices.

        Returns:
            Legend labels mapped to stage in cm, shared by both renderers.

        """
        variable = self.stage_variable(method)
        percentages = self.reference_exceedances if percentages is None else percentages
        if any(p not in (5, 95) for p in percentages):
            msg = "Horizontal references must be 5 and/or 95 percent."
            raise ValueError(msg)
        references = {
            f"C{p} — Permanência {p}%": float(self.exceedance_curve[variable].loc[p])
            for p in percentages
        }
        references.update(
            {name: value for name, value in self.thresholds.items() if value is not None}
        )
        return references

    def plot_daily_climatology(
        self, ax: Axes, ref_year: int | None = None, method: Method | None = None
    ) -> None:
        """
        Draw saved stage climatology without reading observations.

        Args:
            ax: Matplotlib axes.
            ref_year: Year for date labels; defaults to the current local year.
            method: Stage method; None uses the saved chart method.

        """
        variable = self.stage_variable(method)
        year = pd.Timestamp.now(tz="America/Sao_Paulo").year if ref_year is None else ref_year
        dates = pd.to_datetime([f"{year}-{m:02d}-{d:02d}" for m, d in self.daily_curve.index])
        for stat, color, label in (("min", "darkgray", "Min"), ("max", "gray", "Max")):
            ax.plot(
                dates, self.daily_curve[statistic_column(variable, stat)], color=color, label=label
            )
        ax.plot(
            dates,
            self.daily_curve[statistic_column(variable, "mean")],
            color="lightblue",
            linestyle="--",
            label="MLT",
        )
        # Installed Matplotlib stubs restrict y to scalars, although arrays are supported.
        ax.fill_between(
            dates,
            self.daily_curve[statistic_column(variable, 90)].to_numpy(),  # type: ignore[arg-type]
            self.daily_curve[statistic_column(variable, 10)].to_numpy(),  # type: ignore[arg-type]
            color="lightblue",
            alpha=0.2,
            label="Permanência 90-10% (dia do ano)",
        )
        origin = "Cotas observadas" if variable == "C" else "Cotas obtidas a partir da vazão"
        ax.set_title(
            f"Estação {self.station_name} - {self.station_code}\n{origin}\n"
            + self.descriptions[variable]
        )
        ax.set_ylabel("Cota (cm)")
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=4)


class ExceedanceAnalysis:
    """Calculate fixed historical references and overlay independently refreshed observations."""

    def __init__(self, station: Station, thresholds: dict[str, float | None] | None = None) -> None:
        """
        Attach the caller-owned station and optional manual stage limits.

        Args:
            station: Station with a connector or already loaded daily observations.
            thresholds: Named limits in cm; None values are retained but not plotted.

        """
        self.station = station
        self.thresholds = default_thresholds() | (thresholds or {})
        self.results: ExceedanceResult | None = None

    @classmethod
    def from_saved(cls, path: str | Path, station: Station) -> ExceedanceAnalysis:
        """
        Attach a live station to saved references without recalculation.

        Args:
            path: Exact saved-result directory, including the station code.
            station: Same station, used only for refreshed observations.

        Returns:
            Analysis with all saved historical references loaded.

        """
        result = ExceedanceResult.load(path)

        analysis = cls(station, result.thresholds)
        analysis.results = result
        return analysis

    def calculate(
        self, source: Source = "hidro/telemetria", period: slice = DEFAULT_PERIOD
    ) -> ExceedanceResult:
        """
        Calculate all three variables from the currently loaded historical window.

        Reload the full intended record before calling after a telemetry-only refresh.
        Rating-curve failure leaves derived-stage columns missing, never substituted.

        Args:
            source: Historical, telemetric, or historical-first merged observations.
            period: Inclusive slice of loaded observations; omitted bounds use all loaded data.

        Returns:
            Both curves, summaries, coverage and metadata; also stored as results.

        """
        if self.station.stats is None:
            self.station.load_series(source=source)
        frames = {
            variable: self.station.get_series(source, kind, period).dropna(subset=["val"])
            for variable, kind in (("Q", "vazao"), ("C", "cota"))
        }
        if all(frame.empty for frame in frames.values()):
            msg = f"No usable observations for station {self.station.code}."
            raise ValueError(msg)
        status = {name: "No observations" if df.empty else "Ok" for name, df in frames.items()}
        frames["C_from_Q"] = frames["Q"].iloc[:0].copy()
        status["C_from_Q"] = "No discharge observations"
        if not frames["Q"].empty:
            try:
                # Convert observations first: mean stage is not stage at mean discharge.
                converted = self.station.hidro.compute_stage_from_flow(
                    frames["Q"]["val"], station=self.station.code
                )
            except Exception as exc:
                status["C_from_Q"] = f"Rating-curve conversion failed: {exc}"
            else:
                frames["C_from_Q"] = frames["Q"].assign(val=converted)
                status["C_from_Q"] = "Ok"
        self.results = self._summarize(frames, status, source, period)
        return self.results

    def _summarize(
        self, frames: dict[str, pd.DataFrame], status: dict[str, str], source: Source, period: slice
    ) -> ExceedanceResult:
        """
        Assemble per-variable statistics and reproducible processing metadata.

        Args:
            frames: Selected daily records, including converted stage.
            status: Availability and conversion messages by variable.
            source: Requested source policy.
            period: Requested inclusive date slice.

        Returns:
            Complete result with unchanged manual and plotting settings on recalculation.

        """
        daily, curves, summary, statistics, descriptions, coverage = [], {}, {}, {}, {}, {}
        for variable, frame in frames.items():
            calendar, curve, row = calculate_tables(frame, variable)
            daily.append(calendar)
            curves[variable] = curve
            summary.update(row)
            stats = HydroStats.calc_series_stats(
                frame, "val", "NivelConsistencia" if "NivelConsistencia" in frame else None
            )
            statistics[variable] = stats | {"count": len(frame)}
            descriptions[variable] = describe_record(frame, stats)
            coverage[variable] = {
                "start": None if frame.empty else frame.index.min().isoformat(),
                "end": None if frame.empty else frame.index.max().isoformat(),
            }
        previous = self.results
        return ExceedanceResult(
            station_code=self.station.code,
            station_name=self.station.name,
            daily_curve=pd.concat(daily, axis=1),
            exceedance_curve=pd.DataFrame(curves),
            summary=pd.DataFrame(summary, index=pd.Index([self.station.code], name="station_code")),
            stats=pd.DataFrame.from_dict(statistics, orient="index").rename_axis("variable"),
            station_stats=self.station.stats.copy(),
            source=source,
            period={
                "start": None if period.start is None else str(period.start),
                "end": None if period.stop is None else str(period.stop),
            },
            calculated_at=pd.Timestamp.now(tz="America/Sao_Paulo").isoformat(),
            descriptions=descriptions,
            coverage=coverage,
            status=status,
            sanitization=self.station.sanitization or {},
            thresholds=dict(previous.thresholds if previous else self.thresholds),
            reference_exceedances=list(previous.reference_exceedances if previous else []),
            plot_method=previous.plot_method if previous else "from_discharge",
        )

    def save_results(self, base_path: str | Path = DEFAULT_RESULTS_DIR) -> None:
        """
        Save all tables beneath the station-code subdirectory.

        Args:
            base_path: Root result directory; defaults to /data/CN3S/Exceedance.

        """
        if self.results is None:
            msg = "Call calculate() before saving results."
            raise ValueError(msg)
        self.results.save(Path(base_path) / str(self.station.code))

    def plot_annual_stage_chart(
        self,
        ax: Axes,
        ref_year: int | None = None,
        lookback: int = 2,
        *,
        method: Method | None = None,
        reference_exceedances: list[int] | None = None,
        allow_missing_telemetry: bool = False,
    ) -> None:
        """
        Overlay recent stage observations on fixed saved historical references.

        Args:
            ax: Matplotlib axes.
            ref_year: Calendar year; defaults to the current São Paulo year.
            lookback: Number of preceding years to overlay.
            method: Direct or derived-stage reference; None uses the saved method.
            reference_exceedances: Horizontal 5/95 percent lines; None uses saved choices.
            allow_missing_telemetry: Plot references alone with an explicit notice.

        """
        if self.results is None:
            msg = "Call calculate() or from_saved() before plotting."
            raise ValueError(msg)
        year = pd.Timestamp.now(tz="America/Sao_Paulo").year if ref_year is None else ref_year
        telemetry = self.station.get_series(
            "hidro/telemetria", "cota", slice(f"{year - lookback}-01-01", f"{year}-12-31")
        )
        if telemetry.empty and not allow_missing_telemetry:
            msg = "No recent stage observations. Load Hidro/Telemetria before plotting."
            raise ValueError(msg)
        self.results.plot_daily_climatology(ax, year, method)
        telemetry = telemetry.loc[
            ~((telemetry.index.month == LEAP_DAY[0]) & (telemetry.index.day == LEAP_DAY[1]))
        ]
        for observed_year in range(year - lookback, year + 1):
            annual = telemetry.loc[telemetry.index.year == observed_year, "val"]
            if not annual.empty:
                dates = annual.index.map(lambda day: day.replace(year=year))
                ax.plot(
                    dates,
                    annual,
                    label=str(observed_year),
                    **({"color": "black", "linewidth": 1.5} if observed_year == year else {}),
                )
        handles, labels = ax.get_legend_handles_labels()
        fixed_legend = ax.legend(
            handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=len(handles)
        )
        references = self.results.stage_references(method, reference_exceedances)
        lines = [
            ax.axhline(value, linestyle="--", color=color, label=label)
            for (label, value), color in zip(
                references.items(),
                ("darkgoldenrod", "darkred", "red", "purple") * (len(references) + 1),
                strict=False,
            )
        ]
        if lines:
            ax.add_artist(fixed_legend)
            ax.legend(
                handles=lines, loc="upper center", bbox_to_anchor=(0.5, -0.25), ncol=len(lines)
            )
        if telemetry.empty:
            ax.set_title(ax.get_title() + "\nSem observações recentes de Hidro/Telemetria")
        figure = ax.get_figure()
        if figure is not None:
            figure.autofmt_xdate()
            figure.tight_layout()

        