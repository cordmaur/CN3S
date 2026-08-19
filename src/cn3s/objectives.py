"""Objective function classes and namespace for CN3S optimization."""

from __future__ import annotations

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


class Objectives:
    """Namespace of ready-to-use objective instances."""

    PlainNSE: Objective = PlainNSE()
    NSETopBlend: Objective = NSETopBlend()
