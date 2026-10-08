"""Basin descriptors, calibration values, and search bounds for CN3S."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass
class CN3SParams:
    """
    Parameters for the CN3S rainfall-runoff model.

    Stores both basin descriptors and the eight calibration parameters.
    Parameter values default to values calibrated for the Porto Uruaçu basin.
    Bounds are configurable calibration search ranges, not physical validity limits.
    """

    name: str = "Unnamed"
    """Basin name (used for labeling plots and outputs)."""

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
    """Average Concentration Time — integer lag between precipitation and discharge.

    Shifts the precipitation index forward by days for daily runs and calendar
    months for monthly runs before aligning with observed discharge. Must be a
    non-negative integer. Only applied when
    :meth:`CN3S.run` receives a :class:`pandas.Series` (index-aware mode).
    """

    warmup_steps: int = 3
    """Number of antecedent precipitation steps used by :meth:`CN3S.vj`.

    Also defines the burn-in length excluded from `results` indexing in
    :meth:`CN3S.run`.
    """

    bounds: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "r0": (0.0, 1000.0),
            "cn_i": (1.0, 130.0),
            "alfa": (0.01, 1.0),
            "beta": (1e-4, 1.0),
            "k0": (0.01, 1.0),
            "k1": (0.01, 1.0),
            "k2": (0.01, 1.0),
            "act": (0, 5),
        },
        repr=False,
    )
    """Per-instance search bounds, ordered as the full calibration vector.

    Units follow each parameter: r0 in mm, act in integer days (daily runs) or
    calendar months (monthly runs), and the remaining parameters dimensionless.
    Basin descriptors are always fixed.
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

    @classmethod
    def from_file(cls, path: str | Path) -> CN3SParams:
        """
        Load calibrated parameters and basin descriptors from an optimization JSON.

        Args:
            path: File written by CN3SOptimizer.save().

        Returns:
            Parameters including the station/basin name, drainage area in km²,
            integer ACT, antecedent steps, and calibration bounds.

        Raises:
            KeyError: If the file omits parameters, station name, or drainage area.

        """
        with Path(path).open(encoding="utf-8") as stream:
            params = json.load(stream)["params"]
        params["bounds"] = {name: tuple(limits) for name, limits in params["bounds"].items()}
        # Basin descriptors must come from the calibration, never constructor defaults.
        return cls(name=params.pop("name"), area=params.pop("area"), **params)
