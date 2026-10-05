"""Offline evaluation of fixed calibration runs and independent parameter trials."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.dates import date2num
from matplotlib.markers import MarkerStyle

from cn3s.artifacts import CalibrationStore, read_json
from cn3s.metrics import flow_metrics

if TYPE_CHECKING:
    from matplotlib.figure import Figure


class CalibrationEvaluation:
    """Inspect persisted results without fitting or constructing external clients."""

    def __init__(
        self,
        summary: dict[str, Any],
        modeled: pd.DataFrame,
        history: pd.DataFrame,
        rain: pd.Series | None,
        discharge: pd.Series | None,
        metadata: dict[str, Any],
        *,
        data_root: str | Path,
        input_note: str = "snapshotted inputs",
        watershed_bytes: bytes | None = None,
    ) -> None:
        """Keep independent copies of the saved reference and its provenance."""
        self.summary = deepcopy(summary)
        self.modeled = modeled.copy(deep=True)
        self.history = history.copy(deep=True)
        self.rain = None if rain is None else rain.copy()
        self.discharge = None if discharge is None else discharge.copy()
        self.metadata = deepcopy(metadata)
        self.data_root = Path(data_root)
        self.input_note = input_note
        self.watershed_bytes = watershed_bytes
        self.frequency = str(summary["frequency"])
        self.cutoff = pd.Timestamp(summary["split_date"])
        self.run_id = str(summary["run_id"])
        self._validate()

    def _validate(self) -> None:
        if self.frequency not in ("D", "M"):
            msg = "Frequency must be D or M"
            raise ValueError(msg)
        for frame in (self.modeled, self.rain, self.discharge):
            if frame is not None and (
                not isinstance(frame.index, pd.DatetimeIndex)
                or frame.index.has_duplicates
                or not frame.index.is_monotonic_increasing
            ):
                msg = "Evaluation data must have unique, increasing datetime indexes"
                raise ValueError(msg)
        if self.rain is not None:
            values = self.rain.to_numpy(dtype=float)
            expected = pd.date_range(
                self.rain.index.min(),
                self.rain.index.max(),
                freq="D" if self.frequency == "D" else "MS",
            )
            if (
                not np.isfinite(values).all()
                or (values < 0).any()
                or not self.rain.index.equals(expected)
            ):
                msg = "Replay requires finite nonnegative continuous rainfall"
                raise ValueError(msg)

    @classmethod
    def from_run(
        cls,
        data_root: str | Path = "/data/CN3S",
        *,
        station_code: str | int,
        frequency: str,
        run_id: str = "latest",
    ) -> CalibrationEvaluation:
        """Load a bundle or legacy result; only matching legacy inputs enable replay."""
        summary, modeled, history, path = CalibrationStore(data_root).load(
            station_code,
            frequency,
            run_id,
        )
        rain = None
        discharge = None
        metadata: dict[str, Any] = {}
        note = "snapshotted inputs"
        watershed_bytes = None
        if (path / "inputs").is_dir():
            metadata = read_json(path / "inputs/metadata.json")
            if metadata.get("input_revisions", {}).get(frequency) != summary.get("input_revision"):
                msg = "Input snapshot revision does not match calibration"
                raise ValueError(msg)
            rain = pd.read_parquet(path / "inputs/rain.parquet")["prec"]
            discharge = pd.read_parquet(path / "inputs/discharge.parquet")["Vazao"]
            if (path / "inputs/watershed.parquet").exists():
                watershed_bytes = (path / "inputs/watershed.parquet").read_bytes()
        else:
            note = "Legacy paired results; replay unavailable without matching prepared inputs"
            station = Path(data_root) / "stations" / str(station_code)
            if (station / "metadata.json").exists():
                metadata = read_json(station / "metadata.json")
                if metadata.get("input_revisions", {}).get(frequency) == summary.get(
                    "input_revision"
                ):
                    from cn3s.workflow import StationCalibrationWorkflow  # noqa: PLC0415

                    rain, discharge, metadata = StationCalibrationWorkflow.from_prepared(
                        data_root,
                    ).load_station(station_code, cast("Any", frequency))
                    note = "Legacy run with matching current inputs (not an immutable snapshot)"
                    if (station / "watershed.parquet").exists():
                        watershed_bytes = (station / "watershed.parquet").read_bytes()
        return cls(
            summary,
            modeled,
            history,
            rain,
            discharge,
            metadata,
            data_root=data_root,
            input_note=note,
            watershed_bytes=watershed_bytes,
        )

    def settings(self) -> pd.DataFrame:
        """Show run settings and replay limitations."""
        fields = (
            "run_id",
            "label",
            "kind",
            "status",
            "converged",
            "frequency",
            "station_code",
            "input_revision",
            "split_date",
            "warmup_steps",
            "max_act",
            "objective",
            "optimizer_options",
            "solver",
            "timings_seconds",
        )
        values = {key: self.summary.get(key) for key in fields}
        values["inputs"] = self.input_note
        return pd.Series(values, name="value").to_frame()

    def parameters(self) -> pd.DataFrame:
        """Show the exact persisted parameter vector."""
        return cast("pd.DataFrame", pd.Series(self.summary["params"], name="value").to_frame())

    def saved_metrics(self) -> pd.DataFrame:
        """Keep original recorded scores distinguishable from recomputed scores."""
        return pd.DataFrame(
            [
                {
                    "period": part,
                    "NSE": self.summary.get(f"{part}_nse"),
                    "objective": self.summary.get(f"{part}_objective"),
                    "paired_steps": self.summary.get(f"{part}_count"),
                }
                for part in ("train", "test")
            ]
        )

    def _period(self, frame: pd.DataFrame, period: str) -> pd.DataFrame:
        if period not in ("all", "train", "test"):
            msg = "period must be all, train or test"
            raise ValueError(msg)
        if period == "all":
            return frame.copy()
        return cast(
            "pd.DataFrame",
            frame.loc[frame.index < self.cutoff]
            if period == "train"
            else frame.loc[frame.index >= self.cutoff],
        )

    def frame(self, period: str = "test", *, paired: bool = False) -> pd.DataFrame:
        """Return dated evaluation data; missing observation dates remain visible."""
        frame = self.modeled[["q_m3s", "obs_q_m3s"]].astype(float).copy()
        index = pd.date_range(
            frame.index.min(), frame.index.max(), freq="D" if self.frequency == "D" else "MS"
        )
        frame = frame.reindex(index)
        if self.discharge is not None:
            frame["obs_q_m3s"] = self.discharge.reindex(index)
        frame = self._period(frame, period)
        if paired:
            frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=["q_m3s", "obs_q_m3s"])
        return frame

    def coverage(self) -> pd.DataFrame:
        """Report actual simulated and paired dates, independently of requested rain dates."""
        rows = []
        for period in ("train", "test"):
            full = self.frame(period)
            paired = self.frame(period, paired=True)
            row = {
                "period": period,
                "calendar_steps": len(full),
                "paired_steps": len(paired),
                "excluded_steps": len(full) - len(paired),
                "evaluated_start": paired.index.min(),
                "evaluated_end": paired.index.max(),
            }
            if self.frequency == "M" and self.summary["run_id"] == "legacy":
                row["note"] = "Legacy monthly means have no daily-coverage snapshot"
            rows.append(row)
        return pd.DataFrame(rows)

    def _baselines(self, period: str) -> pd.DataFrame:
        frame = self.frame(period)
        training = self.frame("train", paired=True)
        monthly = training.obs_q_m3s.groupby(pd.DatetimeIndex(training.index).month).mean()
        frame["seasonal_climatology"] = pd.Series(
            pd.DatetimeIndex(frame.index).month, index=frame.index
        ).map(monthly)
        if self.frequency == "D":
            observations = (
                self.discharge if self.discharge is not None else self.frame("all").obs_q_m3s
            )
            # Shift dates, not rows: a missing yesterday never borrows an older observation.
            previous = observations.copy()
            previous.index = previous.index + pd.Timedelta(days=1)
            frame["one_day_persistence"] = previous.reindex(frame.index)
        return frame

    def metrics(self, period: str = "test") -> pd.DataFrame:
        """Score CN3S and training-fit baselines on one common finite mask."""
        frame = self._baselines(period)
        names = ["q_m3s", "seasonal_climatology"]
        if self.frequency == "D":
            names.append("one_day_persistence")
        common = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=["obs_q_m3s", *names])
        rows = [{"series": "CN3S (all pairs)", **flow_metrics(self.frame(period), self.frequency)}]
        for name in names:
            pair = common[["obs_q_m3s", name]].rename(columns={name: "q_m3s"})
            rows.append({"series": f"{name} (common pairs)", **flow_metrics(pair, self.frequency)})
        return pd.DataFrame(rows).set_index("series")

    def hydrograph(
        self,
        period: str = "all",
        *,
        rainfall: bool = True,
        start: str | None = None,
        end: str | None = None,
        reference: CalibrationEvaluation | None = None,
    ) -> Figure:
        """Plot response-date discharge and downward bars on original rain dates."""
        frame = self.frame(period).loc[slice(start, end)]
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(frame.index, frame.obs_q_m3s, color="black", linewidth=0.9, label="Observed")
        ax.plot(frame.index, frame.q_m3s, color="tab:blue", linewidth=0.9, label=self.run_id)
        if reference is not None:
            ref = reference.frame(period).loc[slice(start, end)]
            ax.plot(
                ref.index,
                ref.q_m3s,
                color="tab:orange",
                alpha=0.7,
                linewidth=0.9,
                label=f"Reference: {reference.run_id}",
            )
        ax.axvline(date2num(self.cutoff), color="tab:red", linestyle="--", label="Train/test split")
        ax.set(
            xlabel="Date",
            ylabel="Discharge (m³/s)",
            title=f"Station {self.summary['station_code']} · {self.frequency} · {period}",
        )
        if rainfall and self.rain is not None and not frame.empty:
            rain = self.rain.loc[frame.index.min() : frame.index.max()]
            rain_ax = ax.twinx()
            rain_ax.bar(
                rain.index,
                rain,
                width=0.8 if self.frequency == "D" else 20,
                alpha=0.5,
                color="tab:cyan",
                label="Rain on forcing date",
            )
            maximum = max(float(rain.max()) if not rain.empty else 0, 1)
            rain_ax.set_ylim(maximum * 4, 0)
            rain_ax.set_ylabel("Rain (mm/day)" if self.frequency == "D" else "Rain (mm/month)")
            handles, labels = ax.get_legend_handles_labels()
            extra, extra_labels = rain_ax.get_legend_handles_labels()
            ax.legend(handles + extra, labels + extra_labels, loc="upper left")
        else:
            ax.legend(loc="upper left")
        if (start is not None or end is not None) and not frame.empty:
            ax.set_xlim(date2num(frame.index.min()), date2num(frame.index.max()))
        fig.tight_layout()
        return fig

    def scatter(
        self,
        period: str = "test",
        *,
        reference: CalibrationEvaluation | None = None,
        log: bool = False,
    ) -> Figure:
        """Compare flow pairs against the identity line; never call NSE correlation²."""
        fig, ax = plt.subplots(figsize=(6, 6))
        excluded = 0
        for evaluation in [self] if reference is None else [reference, self]:
            frame = evaluation.frame(period, paired=True)
            if log:
                mask = (frame.q_m3s > 0) & (frame.obs_q_m3s > 0)
                excluded += int((~mask).sum())
                frame = frame.loc[mask]
            ax.scatter(frame.obs_q_m3s, frame.q_m3s, s=9, alpha=0.4, label=evaluation.run_id)
        lower = min(ax.get_xlim()[0], ax.get_ylim()[0])
        upper = max(ax.get_xlim()[1], ax.get_ylim()[1])
        if log:
            lower = max(lower, 0.001)
            ax.set(xscale="log", yscale="log")
        ax.plot([lower, upper], [lower, upper], "k--", linewidth=0.8, label="1:1")
        ax.set(
            xlim=(lower, upper),
            ylim=(lower, upper),
            xlabel="Observed (m³/s)",
            ylabel="Simulated (m³/s)",
            title=f"{period} pairs" + (f"; {excluded} nonpositive pairs excluded" if log else ""),
        )
        ax.legend()
        fig.tight_layout()
        return fig

    def residuals(self, period: str = "test") -> Figure:
        """Show signed residuals against time and observed flow."""
        frame = self.frame(period, paired=True)
        residual = frame.q_m3s - frame.obs_q_m3s
        fig, axes = plt.subplots(1, 2, figsize=(13, 4))
        for ax, x, label in zip(
            axes, [frame.index, frame.obs_q_m3s], ["Date", "Observed (m³/s)"], strict=False
        ):
            ax.scatter(x, residual, s=8, alpha=0.5)
            ax.axhline(0, color="black", linewidth=0.8)
            ax.set(xlabel=label, ylabel="Simulated - observed (m³/s)")
        fig.tight_layout()
        return fig

    def flow_duration(self, period: str = "test") -> Figure:
        """Use rank/(n+1) exceedance probabilities on identical paired dates."""
        frame = self.frame(period, paired=True)
        fig, ax = plt.subplots(figsize=(8, 4))
        exceedance = 100 * np.arange(1, len(frame) + 1) / (len(frame) + 1)
        for column in ("obs_q_m3s", "q_m3s"):
            ax.plot(exceedance, np.sort(frame[column].to_numpy(dtype=float))[::-1], label=column)
        ax.set(xlabel="Exceedance probability (%)", ylabel="Discharge (m³/s)", title=period)
        ax.legend()
        fig.tight_layout()
        return fig

    def seasonality(self, period: str = "test") -> Figure:
        """Display paired calendar-month flow means and mean signed errors."""
        frame = self.frame(period, paired=True)
        frame["residual"] = frame.q_m3s - frame.obs_q_m3s
        means = frame.groupby(pd.DatetimeIndex(frame.index).month)[
            ["obs_q_m3s", "q_m3s", "residual"]
        ].mean()
        fig, raw_axes = plt.subplots(1, 2, figsize=(12, 4))
        axes = cast("Any", raw_axes)
        for column in ("obs_q_m3s", "q_m3s"):
            axes[0].plot(means.index, means[column], marker="o", label=column)
        axes[1].bar(means.index, means.residual)
        for ax in axes:
            ax.set(xlabel="Calendar month", ylabel="Discharge (m³/s)", xticks=range(1, 13))
        axes[0].legend()
        axes[1].set_title("Mean simulated - observed")
        fig.tight_layout()
        return fig

    def seasonal_errors(self, period: str = "test", *, by: str = "month") -> pd.DataFrame:
        """Report month/year paired counts and bias without hiding sparse groups."""
        frame = self.frame(period, paired=True)
        if by not in ("month", "year"):
            msg = "by must be month or year"
            raise ValueError(msg)
        frame["bias"] = frame.q_m3s - frame.obs_q_m3s
        groups = (
            pd.DatetimeIndex(frame.index).month
            if by == "month"
            else pd.DatetimeIndex(frame.index).year
        )
        return frame.groupby(groups).agg(paired_steps=("bias", "count"), bias=("bias", "mean"))

    def optimization_history(self) -> Figure:
        """Plot recorded training objectives and the final solution without replay."""
        fig, ax = plt.subplots(figsize=(9, 4))
        history = self.history
        if not history.empty and "train_objective" in history:
            evolution = history.loc[history.phase == "evolution"] if "phase" in history else history
            ax.plot(evolution.index, evolution.train_objective, label="DE generation best")
        final = self.summary.get("train_objective")
        if final is not None:
            ax.scatter(
                [len(history)],
                [final],
                marker=MarkerStyle("*"),
                s=100,
                label="Saved final objective",
            )
        ax.set(xlabel="Generation / final record", ylabel="Training objective", title=self.run_id)
        if ax.has_data():
            ax.legend()
        fig.tight_layout()
        return fig

    def compare(
        self, other: CalibrationEvaluation, period: str = "test", *, monthly: bool = False
    ) -> pd.DataFrame:
        """Score both runs on common dates/observations; require complete daily months."""
        if self.summary["station_code"] != other.summary["station_code"]:
            msg = "Run comparisons require the same station"
            raise ValueError(msg)
        if self.frequency != other.frequency and not monthly:
            msg = "Different frequencies require monthly=True"
            raise ValueError(msg)
        frames = []
        for evaluation in (self, other):
            frame = evaluation.frame(period)[["q_m3s", "obs_q_m3s"]].astype(float)
            frame = frame.replace([np.inf, -np.inf], np.nan)
            if monthly and evaluation.frequency == "D":
                counts = frame.resample("MS").count()
                frame = frame.resample("MS").mean()
                frame = frame.loc[
                    counts.eq(pd.DatetimeIndex(counts.index).days_in_month, axis=0).all(axis=1)
                ]
            frames.append(frame)
        joined = frames[0].join(frames[1], how="inner", lsuffix="_a", rsuffix="_b").dropna()
        if not np.allclose(joined.obs_q_m3s_a, joined.obs_q_m3s_b):
            msg = "Observation values differ; compare runs with a common observation revision"
            raise ValueError(msg)
        rows = []
        for suffix, evaluation in zip(("a", "b"), (self, other), strict=False):
            frame = joined[[f"q_m3s_{suffix}", f"obs_q_m3s_{suffix}"]].rename(
                columns={f"q_m3s_{suffix}": "q_m3s", f"obs_q_m3s_{suffix}": "obs_q_m3s"}
            )
            rows.append(
                {
                    "run_id": evaluation.run_id,
                    "input_revision": evaluation.summary.get("input_revision"),
                    "start": frame.index.min(),
                    "end": frame.index.max(),
                    **flow_metrics(frame, "M" if monthly else self.frequency),
                }
            )
        return pd.DataFrame(rows)
