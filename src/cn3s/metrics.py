"""Shared scoring utilities for CN3S model and optimizer."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal

from sklearn.metrics import r2_score

if TYPE_CHECKING:
    import pandas as pd

OnTooFew = Literal["raise", "neg_inf"]


def compute_nse(
    observed: pd.Series,
    simulated: pd.Series,
    *,
    on_too_few: OnTooFew = "raise",
) -> float:
    """Compute NSE (implemented as R2) from aligned observed and simulated series."""
    if len(observed) < 2:  # noqa: PLR2004
        if on_too_few == "neg_inf":
            return -math.inf
        msg = "Fewer than 2 aligned observations - cannot compute NSE."
        raise ValueError(msg)

    return float(r2_score(observed, simulated))


def compute_nse_from_frame(
    df: pd.DataFrame,
    *,
    observed_col: str,
    simulated_col: str,
    on_too_few: OnTooFew = "raise",
) -> float:
    """Compute NSE from a DataFrame subset with observed and simulated columns."""
    return compute_nse(
        df[observed_col],
        df[simulated_col],
        on_too_few=on_too_few,
    )


def split_by_cutoff(df: pd.DataFrame, *, cutoff: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a dated DataFrame into train and test subsets by cutoff date."""
    train = df.loc[:cutoff]
    test = df.loc[cutoff:]
    return train, test
