"""Objective function classes and namespace for CN3S optimization."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from cn3s.metrics import compute_nse_from_frame

if TYPE_CHECKING:
    from collections.abc import Callable

    import pandas as pd


class Objective:
    """
    Base class for CN3S objective functions.

    Subclass and override :meth:`evaluate` to define a new objective (Pattern A).
    Alternatively, wrap any plain callable at construction time (Pattern B):

    Pattern A — subclass::

        class MyObjective(Objective):
            def evaluate(self, df: pd.DataFrame) -> float:
                ...

    Pattern B — wrap a plain function::

        def my_fn(df: pd.DataFrame) -> float:
            ...

        CN3SOptimizer(objective=Objective(my_fn))

    The :attr:`name` property returns the class name for subclasses, or the
    wrapped function's ``__name__`` for the adapter form, and is used in plot
    titles.
    """

    def __init__(self, fn: Callable[[pd.DataFrame], float] | None = None) -> None:
        """Initialize the objective, optionally wrapping a plain callable."""
        self._fn = fn

    def evaluate(self, df: pd.DataFrame) -> float:
        """Compute the scalar objective value on an aligned train or test subset."""
        if self._fn is not None:
            return self._fn(df)

        msg = f"{type(self).__name__} must implement evaluate() or pass fn to __init__."
        raise NotImplementedError(msg)

    def __call__(self, df: pd.DataFrame) -> float:
        """Call :meth:`evaluate` on the given DataFrame subset."""
        return self.evaluate(df)

    @property
    def name(self) -> str:
        """Human-readable name for display in plot titles and history records."""
        if self._fn is not None:
            return getattr(self._fn, "__name__", repr(self._fn))
        return type(self).__name__

    def __repr__(self) -> str:
        """Return a short string representation using :attr:`name`."""
        return f"Objective({self.name})"


class PlainNSE(Objective):
    """Objective: 1 - NSE on all observations."""

    def evaluate(self, df: pd.DataFrame) -> float:
        """Return 1 - NSE computed over all rows of df."""
        nse = compute_nse_from_frame(
            df,
            observed_col="obs_q_m3s",
            simulated_col="q_m3s",
            on_too_few="neg_inf",
        )
        return 1 - nse


class NSETopBlend(Objective):
    """Objective: blend of 1 - NSE on all observations and 1 - NSE on top-10% flows."""

    def __init__(self, top_quantile: float = 0.9) -> None:
        """Initialize with configurable top-flow quantile threshold."""
        super().__init__()
        self.top_quantile = top_quantile

    def evaluate(self, df: pd.DataFrame) -> float:
        """Return blend of 1 - NSE (full) and 1 - NSE (top-quantile rows)."""
        nse = compute_nse_from_frame(
            df,
            observed_col="obs_q_m3s",
            simulated_col="q_m3s",
            on_too_few="neg_inf",
        )

        top = df[df["obs_q_m3s"] > df["obs_q_m3s"].quantile(self.top_quantile)]
        nse_top = compute_nse_from_frame(
            top,
            observed_col="obs_q_m3s",
            simulated_col="q_m3s",
            on_too_few="neg_inf",
        )

        return 0.5 * (1 - nse) + 0.5 * (1 - nse_top)


class ExtremeFlowBlend(Objective):
    """Weighted relative squared errors for observed low, middle, and high flows."""

    def __init__(
        self,
        low_quantile: float = 0.2,
        high_quantile: float = 0.9,
        weights: tuple[float, float, float] = (0.4, 0.2, 0.4),
        discharge_floor: float = 0.01,
        reference_observed: pd.Series | None = None,
    ) -> None:
        """
        Configure flow groups, their priorities, and discharge normalization.

        Args:
            low_quantile: Observed non-exceedance quantile defining low flows.
            high_quantile: Observed non-exceedance quantile defining high flows.
            weights: Nonnegative weights in low, middle, high order. Active
                weights are normalized to sum to one when evaluating.
            discharge_floor: Positive minimum normalization scale in m³/s.
                The default is a numerical starting value; select a meaningful
                basin-specific scale when zero or near-zero flows occur.
            reference_observed: Optional calibration discharge series in m³/s
                used to fix thresholds and normalization scales across evaluations.
                Otherwise, each evaluated subset supplies its own reference.

        Raises:
            ValueError: If quantiles, weights, the floor, or the reference are invalid.

        """
        super().__init__()
        if not 0 < low_quantile < high_quantile < 1:
            msg = "Quantiles must satisfy 0 < low_quantile < high_quantile < 1."
            raise ValueError(msg)
        if any(not math.isfinite(w) or w < 0 for w in weights) or sum(weights) <= 0:
            msg = "Weights must be finite, nonnegative, and have a positive sum."
            raise ValueError(msg)
        if not math.isfinite(discharge_floor) or discharge_floor <= 0:
            msg = "discharge_floor must be finite and positive (m³/s)."
            raise ValueError(msg)

        self.low_quantile = low_quantile
        self.high_quantile = high_quantile
        self.weights = weights
        self.discharge_floor = discharge_floor
        self.reference_observed = (
            reference_observed.dropna().copy() if reference_observed is not None else None
        )
        if self.reference_observed is not None and self.reference_observed.empty:
            msg = "reference_observed must contain at least one discharge observation."
            raise ValueError(msg)

    def evaluate(self, df: pd.DataFrame) -> float:
        """
        Compute a dimensionless loss with zero indicating a perfect fit.

        Errors remain paired by date. Each group's mean squared error is divided
        by its reference mean discharge squared, bounded below by the floor squared.
        This emphasizes relative errors without dividing by narrow tail variances.

        Args:
            df: Aligned, non-missing observations and simulations in m³/s,
                in columns ``obs_q_m3s`` and ``q_m3s``.

        Returns:
            Weighted normalized squared error, or infinity if no positively
            weighted group has observations. Empty groups are omitted.

        """
        observed = df["obs_q_m3s"]
        simulated = df["q_m3s"]
        reference = self.reference_observed if self.reference_observed is not None else observed
        low = float(reference.quantile(self.low_quantile))
        high = float(reference.quantile(self.high_quantile))

        # Low-flow membership takes precedence when tied quantiles coincide.
        groups = (
            (observed <= low, reference <= low),
            ((observed > low) & (observed < high), (reference > low) & (reference < high)),
            ((observed >= high) & (observed > low), (reference >= high) & (reference > low)),
        )
        loss = 0.0
        active_weight = 0.0
        for weight, (mask, reference_mask) in zip(self.weights, groups, strict=True):
            if weight == 0 or not mask.any():
                continue
            reference_group = reference[reference_mask]
            # A regime absent from the calibration reference uses the discharge floor.
            scale = self.discharge_floor
            if not reference_group.empty:
                scale = max(float(reference_group.mean()), scale)
            squared_relative_errors = ((simulated[mask] - observed[mask]) / scale) ** 2
            loss += weight * float(squared_relative_errors.mean())
            active_weight += weight

        # Tied or short records may lack a regime; retain the remaining priorities.
        return loss / active_weight if active_weight > 0 else math.inf


class Objectives:
    """Namespace of ready-to-use objective instances."""

    PlainNSE: Objective = PlainNSE()
    NSETopBlend: Objective = NSETopBlend()
    ExtremeFlowBlend: Objective = ExtremeFlowBlend()
