import json
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Literal, TypeAlias

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from .hidro import SeriesType, Source
from .hydro_stats import HydroStats
from .station import Station

Method: TypeAlias = Literal["direct", "from_discharge"]
CurveType: TypeAlias = Literal["daily", "exceedance"]
LEAP_DAY = (2, 29)


@dataclass
class ExceedanceCurveResult:
    """Encapsulates the output of a whole-series exceedance curve computation."""

    station_code: int
    station_name: str
    station_stats: pd.DataFrame
    df: pd.DataFrame  # columns: Vazões, Cota, Cota (a partir da vazao)
    summary: pd.DataFrame  # columns (to be defined)
    stats_discharge: pd.Series  # stats for vazao series
    stats_stage: pd.Series  # stats for cota series
    source: Source
    descr_discharge: str
    descr_stage: str
    status: str  # "Ok" or "Falha na curva chave"

    def save(self, path: str | Path, subfolder: bool = True) -> None:
        path = Path(path)

        if subfolder:
            path /= str(self.station_code)

        path.mkdir(parents=True, exist_ok=True)

        # ─── Parquet files (for programmatic reload) ──────────────
        self.df.to_parquet(path / "exceedance.parquet", index=True)
        self.summary.to_parquet(path / "summary.parquet", index=True, engine="pyarrow")
        self.station_stats.to_parquet(path / "station_stats.parquet", index=True, engine="pyarrow")

        self.stats_discharge.to_frame("vazao").join(
            self.stats_stage.to_frame("cota"),
        ).T.to_parquet(path / "series_stats.parquet")

        # ─── JSON sidecar ─────────────────────────────────────────
        meta = {
            "station_code": self.station_code,
            "station_name": self.station_name,
            "source": self.source,
            "descr_discharge": self.descr_discharge,
            "descr_stage": self.descr_stage,
            "status": self.status,
        }
        (path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

        # ─── Excel (human-friendly, multi-sheet) ──────────────────
        info_df = pd.DataFrame(
            {
                "Campo": [
                    "Código",
                    "Nome",
                    "Fonte",
                    "Status",
                    "Descrição (vazão)",
                    "Descrição (cota)",
                ],
                "Valor": [
                    self.station_code,
                    self.station_name,
                    self.source,
                    self.status,
                    self.descr_discharge,
                    self.descr_stage,
                ],
            },
        )

        # Stats as rows: one row per metric, columns = vazao / cota
        stats_df = pd.DataFrame(
            {
                "Vazão": self.stats_discharge,
                "Cota": self.stats_stage,
            },
        )

        with pd.ExcelWriter(
            path / f"Permanencias_{self.station_code}.xlsx",
            engine="openpyxl",
        ) as writer:
            info_df.to_excel(writer, sheet_name="Info", index=False)
            stats_df.to_excel(writer, sheet_name="Estatísticas", index=True)
            self.df.to_excel(writer, sheet_name="Curvas", index=True)
            self.summary.to_excel(writer, sheet_name="Resumo", index=True)
            self.station_stats.to_excel(writer, sheet_name="Inventário", index=True)

    @classmethod
    def load(cls, path: str | Path) -> "ExceedanceCurveResult":
        path = Path(path)
        df = pd.read_parquet(path / "exceedance.parquet")
        stats_df = pd.read_parquet(path / "stats.parquet")
        meta = json.loads((path / "meta.json").read_text())

        return cls(
            df=df,
            stats_discharge=stats_df["vazao"],
            stats_stage=stats_df["cota"],
            **meta,
        )

    def __repr__(self):
        return f"ExceedanceCurveResult(station={self.station_code}, source={self.source}, status={self.status})"


@dataclass
class DurationCurveResult:
    """Encapsulates the output of a duration curve computation."""

    station_code: int  # station identifier
    station_name: str  # human-readable station name
    df: pd.DataFrame  # columns: [val, exceedance_pct]
    series_type: SeriesType  # "cota" or "vazao"
    source: Source  # source used
    description: str  # human-readable provenance
    stats: pd.Series  # series stats (Inicio, Fim, Anos, Falhas...)
    method: Method
    # Caller-provided stage levels in centimetres, keyed by their legend labels.
    thresholds: dict[str, float] = field(default_factory=dict)

    def update_thresholds(self, thresholds: dict[str, float]) -> None:
        """
        Replace all thresholds drawn as horizontal lines on the annual stage chart.

        The change is kept in memory; save the result again to persist it.

        Args:
            thresholds: New mapping of legend label to stage level (cm). Previous
                thresholds are discarded.

        """
        self.thresholds = dict(thresholds)

    def save(self, path: str | Path) -> None:
        """Persist result to disk as parquet + JSON sidecar."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        # Data (already has metodo, EstacaoCodigo, etc.)
        self.df.to_parquet(path / "curve.parquet", index=True)

        # Stats as a separate small file
        self.stats.to_frame().T.to_parquet(path / "stats.parquet")

        # Scalar metadata
        meta = {
            "station_code": self.station_code,
            "station_name": self.station_name,
            "series_type": self.series_type,
            "source": self.source,
            "description": self.description,
            "method": self.method,
            "thresholds": self.thresholds,
        }
        (path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "DurationCurveResult":
        """Reconstruct from saved files."""
        path = Path(path)

        df = pd.read_parquet(path / "curve.parquet")
        stats = pd.read_parquet(path / "stats.parquet").T[0]
        meta = json.loads((path / "meta.json").read_text())

        return cls(
            df=df,
            stats=stats,
            **meta,
        )

    def __repr__(self):
        return f"DurationCurveResult(station={self.station_code}, {self.series_type}, {self.source}, {self.description}, {self.method})"


class DurationCurveReporter:
    """
    Builds duration curves from a Station instance.

    Encapsulates volatile heuristics (source selection, series comparison)
    away from the stable Station core.
    """

    # Minimum acceptable years of record to prefer a source
    MIN_YEARS_THRESHOLD = 5
    # Maximum gap percentage to accept a source without fallback
    MAX_GAP_PCT = 30.0
    # Define a threshold for the discharge series lenght in comparison to the stage series
    DISCHARGE_STAGE_LENGHT_THRESHOLD = 0.8

    def __init__(
        self,
        station: Station | int,
        thresholds: dict[str, float] | None = None,
    ) -> None:
        """
        Initialize the reporter.

        Args:
            station: Station instance (or code) providing the observations.
            thresholds: Optional stage levels (cm) keyed by legend label, drawn as
                horizontal lines on the annual stage chart. They are stored in
                each result created by this reporter.

        """
        if isinstance(station, int):
            self.station = Station(station)
        else:
            self.station = station

        self.thresholds: dict[str, float] = dict(thresholds or {})
        self.results: DurationCurveResult | None = None

    @classmethod
    def from_saved(cls, path: str | Path, station: Station) -> "DurationCurveReporter":
        """
        Create a reporter from a saved duration-curve result.

        Thresholds come from the saved result; change them afterwards with
        `reporter.results.update_thresholds(...)`.

        Args:
            path: Directory containing the saved result (curve.parquet, meta.json...).
            station: Live station of the same code, used to fetch recent observations.

        Returns:
            Reporter whose `results` is the loaded result.

        Raises:
            ValueError: If the saved result belongs to a different station.

        """
        results = DurationCurveResult.load(path)
        if results.station_code != station.code:
            msg = f"Saved result is for station {results.station_code}, not {station.code}."
            raise ValueError(msg)

        reporter = cls(station, thresholds=results.thresholds)
        reporter.results = results
        return reporter

    # Inside DurationCurveReporter

    def _build_exceedance_summary(
        self,
        exceedance_curves: pd.DataFrame,
        descr_q: str,
        descr_s: str,
    ) -> pd.DataFrame:
        """One-row MultiIndex summary suitable for batch concatenation."""
        quantile_map = {
            "max": "max",
            "q5": lambda x: x.quantile(0.95),
            "q10": lambda x: x.quantile(0.9),
            "q25": lambda x: x.quantile(0.75),
            "mediana": lambda x: x.quantile(0.5),
            "MLT": "mean",  # mean
            "q75": lambda x: x.quantile(0.25),
            "q90": lambda x: x.quantile(0.1),
            "q95": lambda x: x.quantile(0.05),
            "min": "min",
        }

        data = {("Info", "Nome"): self.station.name}

        for col, series in exceedance_curves.items():
            for stat, func in quantile_map.items():
                data[(col, stat)] = (
                    series.agg(func) if (series is not None) and (not series.empty) else None
                )

        data[("Descrição", "vazao")] = descr_q
        data[("Descrição", "cota")] = descr_s

        summary = pd.DataFrame(data, index=[self.station.code])
        summary.columns = pd.MultiIndex.from_tuples(summary.columns)
        summary.index.name = "EstacaoCodigo"

        return summary

    @staticmethod
    def _create_description(df) -> str:
        stats = HydroStats.calc_series_stats(
            df,
            "val",
            "NivelConsistencia" if "NivelConsistencia" in df.columns else None,
        )

        stats = pd.Series(stats)
        stats = stats[["Inicio", "Fim", "Anos", "Falhas (%)", "Consist (%)"]]
        s = " ".join([f"{k}:{v}" for k, v in stats.items()])

        sources = [
            f"{k}({100 * (v / len(df)):.1f}%)"
            for k, v in df.groupby("Sistema", observed=True).size().items()
        ]

        if not isinstance(sources, str):
            sources = "/".join(sources)

        s = sources.upper() + " - " + s.replace(" (", "(")

        return s

    # ─── Public API ────────────────────────────────────────────────

    def create_exceedance_curves(
        self,
        source: Source | None = None,
        period: slice = slice(None, None),
    ) -> ExceedanceCurveResult:
        """
        Calculates exceedance curves for a given period.
        Produces 3 curves: discharge, stage (direct), stage (from discharge via rating curve).
        """
        if source is None:
            source = self._select_best_source()

        df_q, stats_q = self.station.get_series(source, "vazao", period)
        descr_q = self.station.descr

        df_s, stats_s = self.station.get_series(source, "cota", period)
        descr_s = self.station.descr

        # Try to compute stage from discharge via rating curve
        try:
            q_to_s = partial(hidro.compute_stage_from_flow, station=self.station.code)

            df_s_from_q = q_to_s(df_q["val"])

            # exceedance_s_from_q = q_to_s(exceedance_q)
            status = "Ok"
        except Exception:
            df_s_from_q = None
            status = "Falha na curva chave"

        exceedance_q = HydroStats.calc_exceedance_curve(df_q["val"])
        exceedance_s = HydroStats.calc_exceedance_curve(df_s["val"])
        exceedance_s_from_q = (
            None if df_s_from_q is None else HydroStats.calc_exceedance_curve(df_s_from_q)
        )

        exceedance_curves = pd.DataFrame(
            {
                "Vazões": exceedance_q,
                "Cota": exceedance_s,
                "Cota (a partir da vazao)": exceedance_s_from_q,
            },
        )

        summary = self._build_exceedance_summary(
            {
                "Vazões": df_q["val"],
                "Cota": df_s["val"],
                "Cota (a partir da vazao)": df_s_from_q,
            },
            descr_q,
            descr_s,
        )

        self.exceedance_results = ExceedanceCurveResult(
            station_code=self.station.code,
            station_name=self.station.name,
            station_stats=self.station.stats,
            df=exceedance_curves,
            stats_discharge=stats_q,
            stats_stage=stats_s,
            source=source,
            descr_discharge=descr_q,
            descr_stage=descr_s,
            status=status,
            summary=summary,
        )

        return self.exceedance_results

    def create_duration_curve(
        self,
        series_type: SeriesType = "vazao",
        source: Source | None = None,
        method: Method = "direct",
        period: slice = slice(None, None),  # e.g., slice("2026-01-01", "2026-12-31")
    ) -> None:
        """
        Create a duration curve for the station.

        If source is None, selects the best onebased on internal heuristics.
        """
        if self.station.stats is None:
            self.station.load_series()

        hidro = self.station.hidro

        status = "OK"

        if source is None:
            source = self._select_best_source(series_type)

        if (series_type == "vazao") or (method == "direct"):
            print(f"Calculating {series_type} duration curve directly...")
            df, stats = self.station.get_series(source, series_type, period)

        else:
            # At this point, we want stage curve through from_discharge method
            df_q = self.station.get_series(source, "vazao", period)
            df_s = self.station.get_series(source, "cota", period)

            stats_q = HydroStats.calc_series_stats(df_q, "val", None)

            if df_q.empty and df_s.empty:
                msg = "No data for station {self.station.code}/{self.station.name}"
                raise ValueError(msg)

            # Calculate discharge to stage ratio
            q_to_s_ratio = len(df_q) / len(df_s)

            # Decide whether to use discharge or stage curve
            if (q_to_s_ratio < self.DISCHARGE_STAGE_LENGHT_THRESHOLD) or (
                stats_q["Anos (Efet.)"] < self.MIN_YEARS_THRESHOLD
            ):
                print("Obtendo cota diretamente")
                method = "direct"
                df = self.station.get_series(source, "cota", period)
                stats = HydroStats.calc_series_stats(df, "val", None)

            else:
                df = df_q
                stats = stats_q

        # Calculate the percentiles for the dataframe
        curve = HydroStats._calc_quantiles(df, "val")

        # Check if we need to convert from discharge to stage
        if (series_type == "cota") and (method == "from_discharge"):
            try:
                # Create a function that converts discharge to stage using
                # the discharge to stage curves. Station code must be from HIDRO.
                print("Calculating stage duration curve from discharge data...")
                func = hidro.compute_stage_from_flow
                q_to_h = partial(func, station=self.station.code)

                # Convert every column from discharge to stage
                for c in curve.columns:
                    curve[c] = q_to_h(curve[c])

            except Exception as e:
                print(f"Error converting discharge to stage: {e}")
                status = "Problema na curva chave"
                method = "direct"
                df = self.station.get_series(source, "cota")
                stats = HydroStats.calc_series_stats(df, "val", None)
                curve = HydroStats._calc_quantiles(df, "val")

        if (method == "direct") or (series_type == "vazao"):
            method = series_type
        elif method == "from_discharge":
            method = series_type + "/vazao"

        descr = DurationCurveReporter._create_description(df)
        curve["metodo"] = method
        curve["EstacaoCodigo"] = self.station.code
        curve["Descricao"] = descr

        self.results = DurationCurveResult(
            station_code=self.station.code,
            station_name=self.station.name,
            df=curve,
            series_type=series_type,
            source=source,
            description=descr,
            stats=pd.Series(stats),  # calc_series_stats returns a dict; the result stores a Series
            method=method,
            thresholds=dict(self.thresholds),
        )

    def save_results(self, base_path: str | Path) -> None:
        """Save results to a subfolder named after the station code."""
        if self.results is None:
            raise ValueError("No results to save. Run create_duration_curve() first.")

        path = Path(base_path) / str(self.station.code)
        self.results.save(path)

    def plot_duration_curve(self, ax: plt.Axes, ref_year: int | None = None) -> None:
        if self.results is None:
            raise ValueError("No results to save. Run create_duration_curve() first.")

        ref_year = str(ref_year) if isinstance(ref_year, int) else pd.Timestamp.now().year

        stats = self.results.df.copy()

        # Remove 29 feb
        stats["dia"] = stats.index.get_level_values("dia").to_list()
        stats["mes"] = stats.index.get_level_values("mes").to_list()
        stats = stats[~((stats["dia"] == 29) & (stats["mes"] == 2))]

        stats.index = pd.to_datetime(
            str(ref_year) + "-" + stats["mes"].astype(str) + "-" + stats["dia"].astype(str),
        )

        stats[["min", "max"]].plot(ax=ax, color=["red", "blue"])

        stats[["MLT"]].plot(ax=ax, color="lightblue", linestyle="--")
        # Draw a filled area between stats[q10] and stats[q90]
        ax.fill_between(stats.index, stats["q10"], stats["q90"], color="lightblue", alpha=0.2)

        # Set the title
        title = f"Estação {self.station.name} - {self.station.code}\n"
        if "/" in self.results.method:
            title += "Permanência de cotas obtidas a partir da vazão\n"
        else:
            title += f"Permanência de {self.results.series_type}\n"
        title += self.results.description

        ax.set_title(title)

    def plot_annual_stage_chart(
        self,
        ax: plt.Axes,
        ref_year: int | None = None,
    ) -> None:
        """
        Plot climatological stage statistics with recent telemetric observations.

        The two preceding years are aligned by month and day with the reference
        year. February 29 is excluded to match the climatological curve. The
        current reference-year trace ends at the latest observation available
        in the station's loaded series.

        The station is not modified: its series must already be loaded
        (`station.load_series()`), and must be reloaded to include newer data.

        Args:
            ax: Matplotlib axes on which to draw the chart.
            ref_year: Calendar year used for the climatology axis. Defaults to
                the current year.

        Raises:
            ValueError: If no result exists, the result is not a stage curve, or
                no telemetric stage observations are available for the period.
            RuntimeError: If the station's series have not been loaded.

        """
        if self.results is None:
            msg = "No results to plot. Run create_duration_curve() or from_saved() first."
            raise ValueError(msg)
        if self.results.series_type != "cota":
            msg = "Annual stage charts require a 'cota' duration-curve result."
            raise ValueError(msg)

        ref_year = pd.Timestamp.now().year if ref_year is None else ref_year
        start_year = ref_year - 2

        # Uses the series already loaded in the station; reload it beforehand to get the
        # latest observations.
        telemetry = self.station.get_series(
            source="telemetria",
            series_type="cota",
            period=slice(f"{start_year}-01-01", f"{ref_year}-12-31"),
        )
        if telemetry.empty:
            msg = (
                f"No telemetric stage observations for station {self.station.code} "
                f"from {start_year} through {ref_year}."
            )
            raise ValueError(msg)

        stats = self.results.df.copy()
        stats["mes"] = stats.index.get_level_values("mes")
        stats["dia"] = stats.index.get_level_values("dia")
        stats = stats.loc[~((stats["mes"] == LEAP_DAY[0]) & (stats["dia"] == LEAP_DAY[1]))]
        stats.index = pd.to_datetime(
            str(ref_year) + "-" + stats["mes"].astype(str) + "-" + stats["dia"].astype(str),
        )

        ax.plot(stats.index, stats["min"], color="darkgray", linewidth=0.5, label="_nolegend_")
        ax.plot(stats.index, stats["max"], color="gray", linewidth=0.5, label="_nolegend_")
        ax.plot(
            stats.index,
            stats["MLT"],
            color="lightblue",
            linestyle="--",
            linewidth=1.5,
            label="MLT",
        )
        ax.fill_between(
            stats.index,
            stats["q10"],
            stats["q90"],
            color="lightblue",
            alpha=0.2,
        )

        telemetry = telemetry.loc[
            telemetry.index.map(lambda date: (date.month, date.day) != LEAP_DAY)
        ]
        for year in range(start_year, ref_year + 1):
            annual = telemetry.loc[telemetry.index.year == year]
            if annual.empty:
                continue

            plot_dates = annual.index.map(lambda date: date.replace(year=ref_year))
            if year == ref_year:
                ax.plot(
                    plot_dates,
                    annual["val"],
                    label=str(year),
                    color="black",
                    linewidth=1.5,
                )
            else:
                ax.plot(plot_dates, annual["val"], label=str(year), linewidth=1)

        threshold_colors = ("darkgoldenrod", "darkred", "red")
        threshold_lines = []
        for index, (label, value) in enumerate(self.results.thresholds.items()):
            line = ax.hlines(
                value,
                stats.index[0],
                stats.index[-1],
                color=threshold_colors[index % len(threshold_colors)],
                linestyle="--",
                label=label,
            )
            threshold_lines.append(line)

        title = f"Estação {self.results.station_name} - {self.results.station_code}\n"
        if "/" in self.results.method:
            title += "Permanência de cotas obtidas a partir da vazão\n"
        else:
            title += f"Permanência de {self.results.series_type}\n"
        ax.set_title(title + self.results.description)

        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        fig = ax.get_figure()
        fig.autofmt_xdate()

        # Two legend rows: fixed entries (statistics and years) first, then the
        # variable number of caller-defined thresholds below them.
        handles, labels = ax.get_legend_handles_labels()
        fixed = [
            (h, label)
            for h, label in zip(handles, labels, strict=False)
            if h not in threshold_lines
        ]
        fixed_handles = [
            Line2D([], [], color="gray", linewidth=0.8),
            Patch(facecolor="lightblue", edgecolor="none", alpha=0.4),
            *(h for h, _ in fixed),
        ]
        fixed_labels = ["Min/Max", "Permanência 90-10%", *(label for _, label in fixed)]
        fixed_legend = ax.legend(
            handles=fixed_handles,
            labels=fixed_labels,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.15),
            ncol=len(fixed_handles),
        )

        if threshold_lines:
            # add_artist keeps the first legend when the second one is created.
            ax.add_artist(fixed_legend)
            ax.legend(
                handles=threshold_lines,
                labels=list(self.results.thresholds),
                loc="upper center",
                bbox_to_anchor=(0.5, -0.25),
                ncol=len(threshold_lines),
            )

        ax.set_ylabel("Cota (cm)")
        # Legends and the title sit outside the axes; fit them in the figure so that a
        # plain savefig does not clip them.
        fig.tight_layout()

    # ─── Heuristics (volatile logic lives here) ────────────────────
    def _select_best_source(self, series_type: SeriesType = "vazao") -> Source:
        """
        Compare available sources and pick the best one based on
        series length, gap percentage, and consistency level.
        """
        years_hidro = self.station.stats.iloc[0]["cota"]["Anos (Efet.)"]
        if (years_hidro > self.MIN_YEARS_THRESHOLD) or (self.station.telemetric_info is None):
            return "hidro"
        return "hidro/telemetria"
