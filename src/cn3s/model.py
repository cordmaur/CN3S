"""Core implementation of the CN3S rainfall-runoff model."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd
from tqdm.auto import tqdm

from cn3s.metrics import compute_nse

try:
    import plotly.graph_objects as go
except ImportError:
    go = None

if TYPE_CHECKING:
    from collections.abc import Iterable

    from plotly.graph_objs import Figure

    from utils import FREQ


@dataclass
class CN3SParams:
    """
    Parameters for the CN3S rainfall-runoff model.

    Stores both basin descriptors and the six calibration parameters.
    All numeric fields default to values calibrated for the Porto Uruaçu basin.
    """

    name: str = "Unnamed"
    """"Basin name (used for labeling plots and outputs)."""

    area: float = 34334.0
    """Drainage area in km²."""

    r0: float = 350.0
    """Initial groundwater storage in mm (used as R at t=0)."""

    cn_i: float = 7.35
    """Curve Number calibration anchor (CN-I, dry antecedent condition)."""

    alfa: float = 0.2
    """Initial abstraction ratio — fraction of S withheld before runoff starts."""

    beta: float = 0.00211662329536844
    """Antecedent precipitation sensitivity parameter (Eq. 04)."""

    k0: float = 1.0
    """Exponential decay factor for older antecedent precipitation months."""

    k1: float = 0.316
    """Groundwater recharge fraction of net rainfall (K1 < 1, Eq. 11)."""

    k2: float = 0.305
    """Baseflow recession coefficient (fraction of R released per step, Eq. 12)."""

    act: int = 0
    """Average Concentration Time — days of lag between precipitation and discharge.

    Shifts the precipitation index forward by this many days before aligning with
    observed discharge. Must be a non-negative integer. Only applied when
    :meth:`CN3S.run` receives a :class:`pandas.Series` (index-aware mode).
    """

    warmup_steps: int = 3
    """Number of antecedent precipitation steps used by :meth:`CN3S.vj`.

    Also defines the burn-in length excluded from `results` indexing in
    :meth:`CN3S.run`.
    """

    @classmethod
    def from_vector(
        cls,
        vector: Iterable[float],
        **kwargs: Any,
    ) -> CN3SParams:
        """
        Create a CN3SParams instance from a flat vector of optimizable parameters.

        The vector must contain exactly 8 values in the order:
        ``[r0, cn_i, alfa, beta, k0, k1, k2, act]``.
        Basin name and drainage area are fixed descriptors passed separately.
        ``act`` is rounded to the nearest integer.

        Args:
            vector: Iterable of 8 floats — ``[r0, cn_i, alfa, beta, k0, k1, k2, act]``.
            **kwargs: Additional keyword arguments passed to the CN3SParams constructor.

        Returns:
            CN3SParams instance with the given parameter values.

        """
        r0, cn_i, alfa, beta, k0, k1, k2, act = vector
        return cls(
            **kwargs,
            r0=r0,
            cn_i=cn_i,
            alfa=alfa,
            beta=beta,
            k0=k0,
            k1=k1,
            k2=k2,
            act=round(act),
        )

    def as_list(self) -> list[float]:
        """
        Return the optimizable parameters as a flat vector.

        The order of values is: ``[r0, cn_i, alfa, beta, k0, k1, k2, act]``.

        Returns:
            List of 8 values corresponding to the optimizable parameters.
            Note: ``act`` is an :class:`int` but is included as-is for compatibility
            with scipy optimizers (which treat all values as floats).

        """
        return [
            self.r0,
            self.cn_i,
            self.alfa,
            self.beta,
            self.k0,
            self.k1,
            self.k2,
            float(self.act),
        ]


class CN3S:
    """
    CN3S rainfall-runoff model with exponentially weighted antecedent precipitation.

    Computes mean monthly discharge from mean areal precipitation. The model
    separates total runoff into direct runoff (Qup, surface) and baseflow (Qlow,
    subsurface), with the Curve Number adjusted each time step by a weighted
    index of the preceding precipitation totals over ``params.warmup_steps``.


    Typical usage::

        params = CN3SParams(area=34334.0, cn_i=7.35)
        model = CN3S(params)

        vj = model.vj(past_prec)
        cnv = model.cnv(vj)
        s = model.s(cnv)
        q_up = model.q_up(prec, s)
        r1 = model.r1(prec, q_up)
        q_low = model.q_low(r1)
        r = model.r(r1, q_low)
        q_m3s = model.q_calc_m3s(model.q_calc_mm(q_up, q_low))

    """

    def __init__(self, params: CN3SParams, freq: FREQ) -> None:
        """
        Store calibration parameters for later use in each computation step.

        Args:
            params: Basin and model calibration parameters.

        """
        self.params = params
        self.freq = freq

        # Init results dataframe
        self.results = pd.DataFrame()
        self.last_nse: float | None = None
        self.last_vj: list[float] = []

    # -------- CORE METHODS -------- #
    def vj(self, past_prec: Iterable[float]) -> float:
        """
        Compute antecedent precipitation coefficient Vj using exponential decay.

        Weights the previous ``warmup_steps`` precipitation totals using an
        exponential decay controlled by K0, then scales by BETA (Eq. 04).
        Index 0 is the most recent step.

        Args:
            past_prec: Last ``warmup_steps`` precipitation values in mm,
                ordered [t-1, t-2, ..., t-warmup_steps] (most recent first).

        Returns:
            Antecedent moisture coefficient clipped to [0, 5].

        """
        past_prec = list(past_prec)
        expected = self.params.warmup_steps
        if len(past_prec) != expected:
            msg = f"past_prec must have length {expected}, got {len(past_prec)}"
            raise ValueError(msg)

        beta = self.params.beta
        k0 = self.params.k0

        # Exponentially-weighted sum of antecedent precipitation
        ap = sum((k0**i) * float(p) for i, p in enumerate(past_prec))
        vj = 1.0 + beta * ap

        # Vj remains within the implementation's valid range
        vj = min(max(vj, 0.0), 100.0)
        self.last_vj.append(vj)
        return vj

    def cnv(self, vj: float) -> float:
        """
        Compute the adjusted Curve Number CNVj for the current antecedent condition.

        Applies the power-law regression (Eq. 09) derived from SCS CN tables,
        relating CN-I (dry) to CN for any moisture state Vj:
        CNVj = 0.925 * CNI^1.019 * Vj^(2.356 - 0.479 * ln(CNI))

        Args:
            vj: Antecedent moisture coefficient from :meth:`vj`.

        Returns:
            Adjusted Curve Number clamped to the valid range [0, 100].

        """
        cn_i = self.params.cn_i

        # Exponent varies with CNI — higher CNI yields a flatter response to Vj
        exponent = 2.356 - 0.479 * float(np.log(cn_i))
        cnv = 0.925 * cn_i**1.019 * vj**exponent

        # Clip to valid CN range
        return float(np.clip(cnv, 0.0, 99.999))

    def s(self, cnv: float) -> float:
        """
        Compute maximum potential retention S from the adjusted Curve Number.

        Converts the dimensionless CN to a retention depth using the SCS
        formula (Eq. 05), scaled from inches to millimetres (* 25.4).

        Args:
            cnv: Adjusted Curve Number from :meth:`cnv`.

        Returns:
            Maximum potential retention in mm (≥ 0), rounded to 2 decimal places.

        """
        # Standard SCS: S (in) = 1000/CN - 10; convert to mm by * 25.4
        s = ((1000.0 / cnv) - 10.0) * 25.4

        return max(s, 0.0)

    def q_up(self, prec: float, s: float) -> float:
        """
        Compute direct runoff depth Qup using the SCS runoff equation (Eq. 02).

        Returns zero when precipitation does not exceed the initial abstraction
        threshold (alfa * S). Above that threshold:
        Q = (P - alfa*S)² / (P + (1 - alfa)*S)

        Args:
            prec: Mean areal precipitation for the current month (mm).
            s: Maximum potential retention (mm) from :meth:`s`.

        Returns:
            Direct runoff depth in mm, rounded to 2 decimal places.

        """
        alfa = self.params.alfa

        # No runoff until precipitation exceeds the initial abstraction
        if prec < s * alfa:
            return 0.0

        try:
            q_up = (prec - s * alfa) ** 2.0 / (prec + (1.0 - alfa) * s)
        except ZeroDivisionError:
            print(prec, alfa, s)
            raise

        return float(q_up)

    def r1(self, prec: float, q_up: float, r0: float | None = None) -> float:
        """
        Compute groundwater storage after recharge, before baseflow depletion (Eq. 11).

        A fraction K1 of net rainfall (P - Qup) recharges the aquifer each month.

        Args:
            prec: Mean areal precipitation for the current month (mm).
            q_up: Direct runoff depth (mm) from :meth:`q_up`.
            r0: Groundwater storage at the start of this time step (mm).
                Falls back to ``params.r0`` when ``None``.

        Returns:
            Updated groundwater storage in mm, rounded to 2 decimal places.

        """
        effective_r0 = r0 if r0 is not None else self.params.r0
        k1 = self.params.k1

        r = effective_r0 + k1 * (prec - q_up)
        return r

    def q_low(self, r1: float) -> float:
        """
        Compute baseflow depth Qlow as a linear recession from storage (Eq. 12).

        Args:
            r1: Groundwater storage before depletion (mm) from :meth:`r1`.

        Returns:
            Baseflow depth in mm, rounded to 2 decimal places.

        """
        q_low = self.params.k2 * r1
        return q_low

    def r(self, r1: float, q_low: float) -> float:
        """
        Compute end-of-period groundwater storage after baseflow release (Eq. 13).

        Args:
            r1: Groundwater storage before baseflow depletion (mm).
            q_low: Baseflow depth (mm) from :meth:`q_low`.

        Returns:
            End-of-period groundwater storage in mm, rounded to 2 decimal places.

        """
        return r1 - q_low

    def q_calc_mm(self, q_up: float, q_low: float) -> float:
        """
        Compute total monthly runoff as the sum of direct runoff and baseflow (Eq. 14).

        Args:
            q_up: Direct runoff depth (mm).
            q_low: Baseflow depth (mm).

        Returns:
            Total runoff depth in mm, rounded to 2 decimal places.

        """
        return q_up + q_low

    def q_calc_m3s(self, q_mm: float) -> float:
        """
        Convert monthly runoff depth to mean monthly discharge in m³/s.

        Assumes a uniform 30-day month for the time-averaging step.

        Args:
            q_mm: Total monthly runoff depth in mm.

        Returns:
            Mean monthly discharge in m³/s, rounded to 2 decimal places.

        """
        # Convert drainage area from km² to m²
        area_m2 = self.params.area * 1e6

        # Convert depth: mm → m, scale by area, divide by seconds in a 30-day month
        days = 30 if self.freq == "M" else 1
        seconds_per_month = days * 24.0 * 3600.0
        q_m3s = (q_mm / 1000.0) * area_m2 / seconds_per_month

        return q_m3s

    # -------- PUBLIC METHODS -------- #
    def reset(self) -> None:
        """Reset any internal state or results from previous calculations."""
        self.results = pd.DataFrame()
        self.last_nse = None

    def step(self, prec: float, past_prec: Iterable[float] | None = None) -> pd.Series:
        """
        Perform a full monthly runoff calculation from antecedent and current precipitation.

        Args:
            past_prec: Iterable of the last ``warmup_steps`` precipitation totals in mm,
                ordered [t-1, t-2, ..., t-warmup_steps] (most recent first).
            prec: Mean areal precipitation for the current month (mm).

        Returns:
            Pandas Series containing the full set of step results, including mean monthly
            discharge in m³/s.

        """
        # Check if we have previous precipitation to run the model
        if past_prec is None and self.results.empty:
            msg = "No past_prec provided and no previous results to infer from."
            raise ValueError(msg)

        warmup_steps = self.params.warmup_steps

        if past_prec is None:
            # Build antecedent history for the next step from previous state.
            prev_past_prec = cast("list[float]", list(self.results["past_prec"].iloc[-1]))
            past_prec_aux = prev_past_prec[: max(warmup_steps - 1, 0)]
            past_prec = [float(self.results["prec"].iloc[-1]), *past_prec_aux]

        past_prec = cast("list[float]", list(past_prec))  # Type hint for mypy
        if len(past_prec) != warmup_steps:
            msg = f"past_prec must have length {warmup_steps}, got {len(past_prec)}"
            raise ValueError(msg)

        # Check if we have previous computation to get r0
        r0 = self.results["r"].iloc[-1] if not self.results.empty else None

        # Run the full sequence of calculations for this time step
        vj = self.vj(past_prec)
        cnv = self.cnv(vj)
        s = self.s(cnv)
        q_up = self.q_up(prec, s)
        r1 = self.r1(prec, q_up, r0)
        q_low = self.q_low(r1)
        r = self.r(r1, q_low)
        q_mm = self.q_calc_mm(q_up, q_low)
        q_m3s = self.q_calc_m3s(q_mm)

        # Store the results into a Pandas Series
        step_results: dict[str, float | list[float]] = {
            "prec": prec,
            "past_prec": past_prec,
            "vj": vj,
            "cnv": cnv,
            "s": s,
            "q_up": q_up,
            "r1": r1,
            "q_low": q_low,
            "r": r,
            "q_mm": q_mm,
            "q_m3s": q_m3s,
        }

        step_results_series = pd.Series(step_results)

        # Append the step results to the internal results dataframe
        self.results = pd.concat([self.results, step_results_series.to_frame().T])
        self.results = self.results.reset_index(drop=True)

        return step_results_series

    def run(self, prec_series: pd.Series, *, pbar: bool = True) -> None:
        """
        Run the model over a full time series of precipitation values.

        The series index is used to assign ``self.results.index`` after the run,
        shifted forward by ``params.act`` days (Average Concentration Time). The
        first ``params.warmup_steps`` entries are consumed as warm-up and excluded
        from the results.

        Args:
            prec_series: Precipitation values in mm ordered by time (oldest first),
                as a dated :class:`pandas.Series`.
            pbar: Whether to display a progress bar using tqdm.

        Returns:
            None. Results are stored internally in the `results` attribute.

        """
        self.last_vj = []
        warmup_steps = self.params.warmup_steps
        minimum_len = warmup_steps + 1
        if len(prec_series) < minimum_len:
            msg = (
                f"prec_series must have at least {minimum_len} values "
                f"(warmup_steps + 1), got {len(prec_series)}"
            )
            raise ValueError(msg)

        act_delta = pd.Timedelta(days=self.params.act)
        dated_index: pd.DatetimeIndex = prec_series.index + act_delta  # type: ignore[assignment]
        values = prec_series.tolist()

        self.reset()  # Clear any previous results

        # init past_prec for the first iteration
        past_prec = [values.pop(0) for _ in range(warmup_steps)]
        past_prec.reverse()

        # Run the first iteration only
        prec = values.pop(0)
        self.step(prec, past_prec)

        # If a progress bar is requested, wrap the remaining iterations with tqdm
        iterator = tqdm(values, desc="Running CN3S model", unit="step") if pbar else values

        # Run the remaining iterations with progress bar
        for prec in iterator:
            self.step(prec)

        self.results.index = dated_index[warmup_steps:]

    def evaluate(self, obs_q: pd.Series) -> float:
        """
        Score the model against observed discharge and attach the series to results.

        Joins ``obs_q`` to :attr:`results` on the shared index (stored as column
        ``obs_q_m3s``), then returns the Nash-Sutcliffe Efficiency (r² score)
        computed on all rows where both simulated and observed values are present.
        Calling this method again replaces any previously attached ``obs_q_m3s``.

        Args:
            obs_q: Observed discharge in m³/s, indexed by date.

        Returns:
            Nash-Sutcliffe Efficiency (r² score) on the aligned period.

        Raises:
            RuntimeError: If the model has not been run yet.
            ValueError: If fewer than 2 time steps align between results and obs_q.

        """
        if self.results.empty:
            msg = "Model has not been run yet. Call run() first."
            raise RuntimeError(msg)

        # Drop any existing obs column so this call is idempotent
        if "obs_q_m3s" in self.results.columns:
            self.results = self.results.drop(columns=["obs_q_m3s"])

        self.results = self.results.join(obs_q.rename("obs_q_m3s"), how="left")

        valid = self.results[["q_m3s", "obs_q_m3s"]].dropna()
        if len(valid) < 2:  # noqa: PLR2004
            msg = "Fewer than 2 aligned observations — cannot compute NSE."
            raise ValueError(msg)

        msg = f"Aligned {len(valid)} time steps between model results and observations.\n"
        msg += f"From {valid.index[0]} to {valid.index[-1]}."
        print(msg)

        nse = compute_nse(valid["obs_q_m3s"], valid["q_m3s"])
        self.last_nse = nse
        return nse

    def plot(
        self,
        *,
        split: int | None = None,
        q_headroom: float = 1.2,
        prec_headroom: float = 1.5,
        title: str = "CN3S: Simulated vs Observed",
        show: bool = False,
        height: int = 500,
        width: int = 1000,
    ) -> Figure:
        """
        Plot latest model results with discharge lines and inverted precipitation bars.

        Uses :attr:`results` from the most recent :meth:`run` call and, when
        available, overlays observed discharge from :meth:`evaluate`.

        Args:
            split: Optional integer index for the train/test separator line.
            q_headroom: Multiplier applied to max discharge to set y-axis upper bound.
            prec_headroom: Multiplier applied to max precipitation for y2 upper bound.
            title: Figure title.
            show: Whether to immediately render the figure with ``fig.show()``.
            height: Figure height in pixels.
            width: Figure width in pixels.

        Returns:
            Plotly Figure object.

        Raises:
            RuntimeError: If the model has not been run yet.
            ValueError: If required columns are missing or arguments are invalid.
            ImportError: If Plotly is not installed.

        """
        if self.results.empty:
            msg = "Model has not been run yet. Call run() first."
            raise RuntimeError(msg)

        if q_headroom <= 0.0 or prec_headroom <= 0.0:
            msg = "q_headroom and prec_headroom must be > 0."
            raise ValueError(msg)

        required_cols = {"q_m3s", "prec"}
        missing_cols = required_cols.difference(self.results.columns)
        if missing_cols:
            msg = f"results is missing required columns: {sorted(missing_cols)!r}"
            raise ValueError(msg)

        if split is not None and not (0 <= split < len(self.results)):
            msg = f"split must be in [0, {len(self.results) - 1}], got {split}"
            raise ValueError(msg)

        if go is None:
            msg = "Plotly is required for CN3S.plot(). Install with: pip install plotly"
            raise ImportError(msg)

        results = self.results.copy()
        has_observed = "obs_q_m3s" in results.columns

        def _fmt_param_value(value: object) -> str:
            if isinstance(value, float):
                out = f"{value:.3f}".rstrip("0").rstrip(".")
                return "0" if out in {"-0", ""} else out
            return str(value)

        params_repr = (
            "CN3SParams("
            + ", ".join(
                f"{field.name}={_fmt_param_value(getattr(self.params, field.name))}"
                for field in fields(self.params)
            )
            + ")"
        )
        nse_text = (
            f"NSE = {self.last_nse:.3f}" if self.last_nse is not None else "NSE = not evaluated"
        )
        title_text = f"{title}<br>{params_repr}<br>{nse_text}"

        discharge_cols = ["q_m3s", "obs_q_m3s"] if has_observed else ["q_m3s"]
        q_max = float(results[discharge_cols].max().max())
        prec_max = float(results["prec"].max())

        # Keep axis ranges valid even if data are all zeros or contain NaNs.
        q_upper = q_max * q_headroom if np.isfinite(q_max) and q_max > 0.0 else 1.0
        prec_upper = prec_max * prec_headroom if np.isfinite(prec_max) and prec_max > 0.0 else 1.0

        fig = go.Figure()

        if has_observed:
            fig.add_trace(
                go.Scatter(
                    x=results.index,
                    y=results["obs_q_m3s"],
                    name="Observed discharge",
                    line={"color": "green", "width": 2},
                    opacity=0.75,
                ),
            )

        fig.add_trace(
            go.Scatter(
                x=results.index,
                y=results["q_m3s"],
                name="Model discharge",
                line={"color": "orange", "width": 1.5},
                opacity=0.9,
            ),
        )

        if split is not None:
            split_date = results.index[split]
            fig.add_shape(
                type="line",
                x0=split_date,
                x1=split_date,
                y0=0,
                y1=1,
                yref="paper",
                line={"color": "red", "dash": "dash"},
            )
            fig.add_annotation(
                x=split_date,
                y=1,
                yref="paper",
                text="train/test split",
                showarrow=False,
                xanchor="left",
                yanchor="top",
                font={"color": "red"},
            )

        fig.add_trace(
            go.Bar(
                x=results.index,
                y=results["prec"],
                name="Precipitation",
                marker_color="steelblue",
                opacity=1.0,
                yaxis="y2",
            ),
        )

        axis_style = {"showline": True, "linewidth": 1, "linecolor": "black", "mirror": True}

        fig.update_layout(
            title={"text": title_text, "x": 0.5, "xanchor": "center", "font": {"size": 12}},
            xaxis={"title": "Date", **axis_style},
            yaxis={"title": "Discharge (m³/s)", "range": [0, q_upper], **axis_style},
            yaxis2={
                "title": "Precipitation (mm)",
                "overlaying": "y",
                "side": "right",
                "range": [prec_upper, 0],
                **axis_style,
            },
            legend={"x": 0.01, "y": 0.99},
            height=height,
            width=width,
            plot_bgcolor="white",
        )

        if show:
            fig.show()

        return fig
