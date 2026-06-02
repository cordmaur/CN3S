"""Core implementation of the CN3S rainfall-runoff model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import numpy as np
import pandas as pd
from tqdm.auto import tqdm

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass
class CN3SParams:
    """Parameters for the CN3S rainfall-runoff model.

    Stores both basin descriptors and the six calibration parameters.
    All numeric fields default to values calibrated for the Porto Uruaçu basin.
    """

    bacia: str = "Porto Uruaçu"
    """Basin name (identifier only, not used in calculations)."""

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


class CN3S:
    """CN3S (Curve Number with Three-Step Antecedent Precipitation) model.

    Computes mean monthly discharge from mean areal precipitation. The model
    separates total runoff into direct runoff (Qup, surface) and baseflow (Qlow,
    subsurface), with the Curve Number adjusted each time step by a weighted
    index of the three preceding monthly precipitation totals.


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

    def __init__(self, params: CN3SParams) -> None:
        """Store calibration parameters for later use in each computation step.

        Args:
            params: Basin and model calibration parameters.

        """
        self.params = params

        # Init results dataframe
        self.results = pd.DataFrame()

    # -------- CORE METHODS -------- #
    def vj(self, past_prec: Iterable[float]) -> float:
        """Compute antecedent precipitation coefficient Vj, clamped to [1, 3].

        Weights the three previous monthly precipitation totals using an
        exponential decay controlled by K0, then scales by BETA (Eq. 04).
        Index 0 is the most recent month, index 2 the oldest.

        Args:
            past_prec: Last 3 monthly precipitation values in mm,
                ordered [t-1, t-2, t-3] (most recent first).

        Returns:
            Antecedent moisture coefficient rounded to 2 decimal places.
            Value of 1 = dry, 3 = wet.

        """
        past_prec = list(past_prec)  # Ensure we can index the input
        beta = self.params.beta
        k0 = self.params.k0

        # Exponentially-weighted sum of antecedent precipitation
        ap = float(past_prec[0]) + k0 * float(past_prec[1]) + k0**2 * float(past_prec[2])
        vj = 1.0 + beta * ap

        # Vj must remain within the valid [1, 3] range
        return round(min(max(vj, 1.0), 3.0), 2)

    def cnv(self, vj: float) -> float:
        """Compute the adjusted Curve Number CNVj for the current antecedent condition.

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
        return float(np.clip(cnv, 0.0, 100.0))

    def s(self, cnv: float) -> float:
        """Compute maximum potential retention S from the adjusted Curve Number.

        Converts the dimensionless CN to a retention depth using the SCS
        formula (Eq. 05), scaled from inches to millimetres (* 25.4).

        Args:
            cnv: Adjusted Curve Number from :meth:`cnv`.

        Returns:
            Maximum potential retention in mm (≥ 0), rounded to 2 decimal places.

        """
        # Standard SCS: S (in) = 1000/CN - 10; convert to mm by * 25.4
        s = ((1000.0 / cnv) - 10.0) * 25.4
        return round(max(s, 0.0), 2)

    def q_up(self, prec: float, s: float) -> float:
        """Compute direct runoff depth Qup using the SCS runoff equation (Eq. 02).

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

        q_up = (prec - s * alfa) ** 2.0 / (prec + (1.0 - alfa) * s)
        return round(q_up, 2)

    def r1(self, prec: float, q_up: float, r0: float | None = None) -> float:
        """Compute groundwater storage after recharge, before baseflow depletion (Eq. 11).

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
        return round(r, 2)

    def q_low(self, r1: float) -> float:
        """Compute baseflow depth Qlow as a linear recession from storage (Eq. 12).

        Args:
            r1: Groundwater storage before depletion (mm) from :meth:`r1`.

        Returns:
            Baseflow depth in mm, rounded to 2 decimal places.

        """
        q_low = self.params.k2 * r1
        return round(q_low, 2)

    def r(self, r1: float, q_low: float) -> float:
        """Compute end-of-period groundwater storage after baseflow release (Eq. 13).

        Args:
            r1: Groundwater storage before baseflow depletion (mm).
            q_low: Baseflow depth (mm) from :meth:`q_low`.

        Returns:
            End-of-period groundwater storage in mm, rounded to 2 decimal places.

        """
        return round(r1 - q_low, 2)

    def q_calc_mm(self, q_up: float, q_low: float) -> float:
        """Compute total monthly runoff as the sum of direct runoff and baseflow (Eq. 14).

        Args:
            q_up: Direct runoff depth (mm).
            q_low: Baseflow depth (mm).

        Returns:
            Total runoff depth in mm, rounded to 2 decimal places.

        """
        return round(q_up + q_low, 2)

    def q_calc_m3s(self, q_mm: float) -> float:
        """Convert monthly runoff depth to mean monthly discharge in m³/s.

        Assumes a uniform 30-day month for the time-averaging step.

        Args:
            q_mm: Total monthly runoff depth in mm.

        Returns:
            Mean monthly discharge in m³/s, rounded to 2 decimal places.

        """
        # Convert drainage area from km² to m²
        area_m2 = self.params.area * 1e6

        # Convert depth: mm → m, scale by area, divide by seconds in a 30-day month
        seconds_per_month = 24.0 * 3600.0 * 30.0
        q_m3s = (q_mm / 1000.0) * area_m2 / seconds_per_month

        return round(q_m3s, 2)

    # -------- PUBLIC METHODS -------- #
    def reset(self) -> None:
        """Reset any internal state or results from previous calculations."""
        self.results = pd.DataFrame()

    def step(self, prec: float, past_prec: Iterable[float] | None = None) -> pd.Series:
        """Perform a full monthly runoff calculation from antecedent and current precipitation.

        Args:
            past_prec: Iterable of the last 3 monthly precipitation totals in mm,
                ordered [t-1, t-2, t-3] (most recent first).
            prec: Mean areal precipitation for the current month (mm).

        Returns:
            Pandas Series containing the full set of step results, including mean monthly discharge in m³/s.

        """
        # Check if we have previous precipitation to run the model
        if past_prec is None and self.results.empty:
            msg = "No past_prec provided and no previous results to infer from."
            raise ValueError(msg)

        if past_prec is None:
            # Past prec will be formed by the last prec and the two preceding values from the last step
            past_prec_aux = self.results.iloc[-1]["past_prec"][:2]
            past_prec = [self.results.iloc[-1]["prec"], *past_prec_aux]

        past_prec = cast("list[float]", list(past_prec))  # Type hint for mypy

        # Check if we have previous computation to get r0
        r0 = self.results.iloc[-1]["r"] if not self.results.empty else None

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

    def run(self, prec_series: list[float]) -> None:
        """Run the model over a full time series of monthly precipitation values.

        Args:
            prec_series: List of mean areal precipitation values in mm,
                ordered by time (most recent first).

        Returns:
            None. Results are stored internally in the `results` attribute.

        """
        self.reset()  # Clear any previous results

        # init past_prec for the first iteration
        past_prec = [prec_series.pop(0) for _ in range(3)]
        past_prec.reverse()

        # Run the first iteration only
        prec = prec_series.pop(0)
        self.step(prec, past_prec)

        # Run the remaining iterations with progress bar
        for prec in tqdm(prec_series, desc="Running CN3S model", unit="step"):
            self.step(prec)
