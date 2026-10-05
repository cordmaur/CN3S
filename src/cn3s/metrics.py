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
    train = df.loc[df.index < cutoff]
    test = df.loc[df.index >= cutoff]
    return train, test


def flow_metrics(frame: pd.DataFrame, frequency: str) -> dict[str, float | int | str]:
    """
    Evaluate finite flow pairs; positive bias denotes overprediction.

    KGE uses the original variability-ratio formulation with population standard
    deviations. Volume bias weights flow by actual calendar interval duration.
    Undefined metrics are NaN with an explicit reason, never coerced to a good score.
    """
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    pairs = frame[["obs_q_m3s", "q_m3s"]].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    result: dict[str, float | int | str] = dict.fromkeys(
        [
            "NSE",
            "KGE",
            "correlation",
            "variability_ratio",
            "mean_ratio",
            "RMSE",
            "MAE",
            "bias",
            "volume_bias_pct",
        ],
        math.nan,
    )
    result["paired_steps"] = len(pairs)
    reasons = []
    if pairs.empty:
        result["undefined_reason"] = "No finite observed/simulated pairs"
        return result
    obs = pairs.obs_q_m3s.to_numpy(dtype=float)
    sim = pairs.q_m3s.to_numpy(dtype=float)
    error = sim - obs
    result.update(
        RMSE=float(np.sqrt(np.mean(error**2))),
        MAE=float(np.mean(abs(error))),
        bias=float(error.mean()),
    )
    duration = (
        pd.DatetimeIndex(pairs.index).days_in_month.to_numpy(dtype=float)
        if frequency == "M"
        else np.ones(len(pairs))
    ) * 86400
    observed_volume = float(np.sum(obs * duration))
    if observed_volume != 0:
        result["volume_bias_pct"] = float(100 * np.sum(error * duration) / observed_volume)
    else:
        reasons.append("Zero observed volume: volume bias undefined")
    variance_sum = float(np.sum((obs - obs.mean()) ** 2))
    if len(pairs) >= 2 and variance_sum > 0:  # noqa: PLR2004
        result["NSE"] = float(1 - np.sum(error**2) / variance_sum)
    else:
        reasons.append("Fewer than two pairs or constant observations: NSE undefined")
    if obs.mean() != 0:
        result["mean_ratio"] = float(sim.mean() / obs.mean())
    if obs.std() > 0:
        result["variability_ratio"] = float(sim.std() / obs.std())
    if len(pairs) >= 2 and obs.std() > 0 and sim.std() > 0:  # noqa: PLR2004
        result["correlation"] = float(np.corrcoef(obs, sim)[0, 1])
    components = [float(result[k]) for k in ("correlation", "variability_ratio", "mean_ratio")]
    if all(math.isfinite(v) for v in components):
        result["KGE"] = float(1 - np.sqrt(sum((v - 1) ** 2 for v in components)))
    else:
        reasons.append("Undefined correlation, variability or mean ratio: KGE undefined")
    result["undefined_reason"] = "; ".join(reasons)
    return result
