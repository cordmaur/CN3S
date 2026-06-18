"""Calibration optimizer for the CN3S rainfall-runoff model."""

from __future__ import annotations

import math
from typing import Any, ClassVar

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.optimize import differential_evolution
from sklearn.metrics import r2_score

from cn3s.model import CN3S, CN3SParams


class CN3SOptimizer:
    """
    Calibrate CN3S model parameters against observed discharge.

    Aligns precipitation and observed discharge by their shared index, splits the
    aligned record chronologically into train / test sets, then uses
    ``scipy.optimize.differential_evolution`` to minimise negative Nash-Sutcliffe
    Efficiency (NSE) on the training period.

    A callback is invoked after every generation to report both train and test NSE
    and to persist the best model (by test NSE) in :attr:`model`.

    The optimiser mutates :attr:`model` in place throughout calibration — the
    model passed at construction is used both for objective evaluations and as the
    final result container.  Interrupting the run (``KeyboardInterrupt``) is safe:
    the ``finally`` block guarantees :attr:`model` always holds a fully-run model
    with the best parameters found so far.

    Typical usage::

        params = CN3SParams(area=34334.0)
        model = CN3S(params)

        optim = CN3SOptimizer(
            prec=prec_series,
            observed_q=q_series,
            model=model,
        )
        optim.optimize(maxiter=100, workers=-1)

        # Access the best calibrated model
        best = optim.model

    Attributes:
        model: The :class:`~cn3s.model.CN3S` instance being calibrated.
            After at least one generation its parameters reflect the best
            test-NSE candidate found so far.
        train_ratio: Fraction of the aligned record used for calibration.

    """

    #: Parameter bounds: (min, max) for each of r0, cn_i, alfa, beta, k0, k1, k2, act.
    #: The act bound upper limit is set dynamically in __init__ via max_act.
    _BASE_BOUNDS: ClassVar[list[tuple[float, float]]] = [
        (50.0, 1000.0),  # r0:   initial groundwater storage (mm)
        (1.0, 130.0),  # cn_i: Curve Number anchor
        (0.05, 100),  # alfa: initial abstraction ratio
        (1e-4, 20),  # beta: antecedent precipitation sensitivity
        (0.01, 30),  # k0:   exponential decay factor
        (0.01, 50),  # k1:   groundwater recharge fraction
        (0.01, 2),  # k2:   baseflow recession coefficient
        # act bound appended dynamically: (0, max_act)
    ]

    _BASE_BOUNDS_NEW: ClassVar[list[tuple[float, float]]] = [
        (0.0, 1000.0),  # r0:   initial groundwater storage (mm)
        (1.0, 100.0),  # cn_i: Curve Number anchor
        (0.05, 0.3),  # alfa: initial abstraction ratio
        (1e-4, 0.01),  # beta: antecedent precipitation sensitivity
        (0.01, 1),  # k0:   exponential decay factor
        (0.01, 1),  # k1:   groundwater recharge fraction
        (0.01, 1),  # k2:   baseflow recession coefficient
        # act bound appended dynamically: (0, max_act)
    ]

    def __init__(
        self,
        prec: pd.Series,
        observed_q: pd.Series,
        model: CN3S,
        train_ratio: float = 0.7,
        max_act: int = 30,
        weights_power: float = 1.0,
    ) -> None:
        """
        Initialise the optimiser and prepare train / test splits.

        Args:
            prec: Precipitation time series (mm), indexed by date.
            observed_q: Observed discharge time series (m³/s), indexed by date.
            model: :class:`~cn3s.model.CN3S` instance to calibrate.  Its
                ``params.area`` is used as the fixed drainage area.  The
                instance is mutated in place during optimisation.
            train_ratio: Fraction of the aligned record used for calibration.
                Must be in (0, 1). Defaults to 0.7 (70 / 30 split).
            max_act: Upper bound (in days) for the Average Concentration Time
                parameter search.  Must be a non-negative integer.  Increase
                this for large basins with long travel times.  Defaults to 30.
            weights_power: Exponent for weighting observations in the NSE calculation.

        """
        # Validate and store input parameters
        self._validate_and_assign_inputs(train_ratio, max_act)

        # Store inputs and prepare for calibration
        self.model = model  # The main model
        self.params_dict: dict[int, CN3SParams] = {}  # Dict with the params for each iteration

        # Internal state
        self._area: float = model.params.area  # Basin area
        self._best_nse: float = -math.inf  # Best NSE found so far
        self._best_params_vec: npt.NDArray[np.float64] | None = None
        self._warmup_steps = model.params.warmup_steps  # Number of past precipitations to be used
        self._weights_power = (
            weights_power  # Exponent for weighting observations in the NSE calculation
        )

        # Keep raw series for per-candidate model evaluations
        self._prec_raw = prec
        self._q_raw = observed_q

        # Build the bounds list, appending the act bound
        self._bounds_list: list[tuple[float, float]] = [
            *self._BASE_BOUNDS,
            (0.0, float(self._max_act)),  # act: Average Concentration Time (days)
        ]

        # Align at ACT=0 to determine the reference train/test cutoff date
        self.aligned = pd.concat(
            [prec.rename("prec"), observed_q.rename("observed_q")],
            axis=1,
            join="inner",
        ).dropna()

        # Need enough values to run the model and still compute r2_score
        # on at least two aligned points.
        min_required = self._warmup_steps + 3
        if len(self.aligned) < min_required:
            msg = (
                "Aligned series is too short to calibrate "
                f"(requires at least {min_required} shared time steps for "
                f"warmup_steps={self._warmup_steps})."
            )
            raise ValueError(msg)

        # Determine where is the TRAIN/TEST split index (based on the unshifted alignment)
        split_idx = int(len(self.aligned) * self.train_ratio)
        self.train_idx = split_idx  # first `split_idx` rows are train (for display)

        # Use a date-based cutoff so the split is stable regardless of ACT shift
        self._train_cutoff: pd.Timestamp = self.aligned.index[split_idx]

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #
    def _validate_and_assign_inputs(self, train_ratio: float, max_act: int) -> None:
        """
        Validate and assign constructor inputs to instance attributes.

        Args:
            train_ratio: Fraction of aligned record for training.
            max_act: Upper bound for Average Concentration Time parameter search.

        Raises:
            ValueError: If train_ratio not in (0, 1) or max_act < 0.

        """
        if not (0.0 < train_ratio < 1.0):
            msg = f"train_ratio must be in (0, 1), got {train_ratio!r}"
            raise ValueError(msg)
        if max_act < 0:
            msg = f"max_act must be >= 0, got {max_act!r}"
            raise ValueError(msg)

        self.train_ratio = train_ratio
        self._max_act = max_act

    def _run_model(self, params_vec: npt.NDArray[np.float64]) -> pd.DataFrame:
        """
        Update model parameters, run it, and return results aligned with observed_q.

        Mutates ``self.model.params`` in place.  When called from parallel workers
        (``workers=-1``) each worker operates on its own pickled copy of ``self``,
        so there are no race conditions on the main-process model.

        Args:
            params_vec: Flat array of 8 parameter values in the order expected
                by :meth:`~cn3s.model.CN3SParams.from_vector`.

        Returns:
            DataFrame with columns ``q_m3s`` (modelled) and ``observed_q``,
            indexed by the shifted date index (warm-up rows excluded).

        """
        # Update model parameters
        self.model.params = CN3SParams.from_vector(
            params_vec,
            area=self._area,
            warmup_steps=self._warmup_steps,
        )

        self.model.run(self._prec_raw, pbar=False)

        return (
            self.model.results[["q_m3s"]]
            .join(self._q_raw.rename("observed_q"), how="inner")
            .dropna()
        )

    def _nse(self, df: pd.DataFrame, *, use_weights: bool, train: bool) -> float:
        """
        Compute Nash-Sutcliffe Efficiency on the train or test subset.

        The split is based on :attr:`_train_cutoff` (a fixed calendar date)
        so that it remains stable regardless of the ACT shift applied to each
        candidate during optimisation.

        Args:
            df: Aligned DataFrame with ``q_m3s`` and ``observed_q`` columns.
            use_weights: Whether to use the weights for each observation.
            train: If ``True`` evaluate on the train period; otherwise test.

        Returns:
            NSE (r² score). Returns ``-inf`` when the subset is too small.

        """
        subset = df.loc[: self._train_cutoff] if train else df.loc[self._train_cutoff :]

        if len(subset) < 2:  # noqa: PLR2004
            return -math.inf

        weights = (
            subset["observed_q"] ** self._weights_power / subset["observed_q"].mean()
            if use_weights
            else None
        )

        return float(r2_score(subset["observed_q"], subset["q_m3s"], sample_weight=weights))

    def _objective(self, params_vec: npt.NDArray[np.float64]) -> float:
        """
        Objective function: negative train NSE (to be minimised).

        Args:
            params_vec: Candidate parameter vector.

        Returns:
            ``-NSE_train``.

        """
        df = self._run_model(params_vec)

        nse = self._nse(df, use_weights=False, train=True)
        # nse_weighted = self._nse(df, use_weights=True, train=True)

        # To calculate NSE on top flows, let's get discharges higher than the 90th percentile of the observed discharge
        df_top = df[df["observed_q"] > df["observed_q"].quantile(0.9)]
        nse_top = self._nse(df_top, use_weights=False, train=True)

        return 0.5 * (1 - nse) + 0.5 * (1 - nse_top)

    def _callback(self, xk: Any, _: Any) -> None:  # noqa: ANN401
        """
        Define the callback invoked by DE after every generation.

        Computes train and test NSE for the current best vector ``xk``, prints
        a one-line status, and updates :attr:`model` whenever a new best NSE is found.

        Args:
            xk: Current best parameter vector (or DE intermediate result object).
            _: Ignored argument (convergence progress).

        """
        # differential_evolution may pass an OptimizeResult object instead of a
        # plain array when using certain workers modes — extract .x if needed.
        params_vec: npt.NDArray[np.float64] = xk.x if hasattr(xk, "x") else np.asarray(xk)

        # Estimate MEAN NSE (average of test and train)
        df = self._run_model(params_vec)
        train_nse = self._nse(df, use_weights=False, train=True)
        test_nse = self._nse(df, use_weights=False, train=False)
        mean_nse = (train_nse + test_nse) / 2

        msg = f"{self.step} - Train NSE: {train_nse:.4f} | Test NSE: {test_nse:.4f}"
        self.step += 1

        # Regardless of the result, add the params to the dict for later inspection
        self.params_dict[self.step] = CN3SParams.from_vector(
            params_vec,
            area=self._area,
            warmup_steps=self._warmup_steps,
        )

        if mean_nse > self._best_nse:
            self._best_nse = mean_nse
            self._best_params_vec = params_vec.copy()
            self._persist_model(params_vec)
            msg += " <-- new best NSE!"

        print(msg + f" ({self.model.params})")

    def _persist_model(self, params_vec: npt.NDArray[np.float64]) -> None:
        """
        Update model parameters, run the full series, and attach observed_q.

        After this call ``self.model.results`` is ready for inspection:
        indexed by date with an ``observed_q`` column appended.

        Args:
            params_vec: Parameter vector to persist.

        """
        self.model.params = CN3SParams.from_vector(
            params_vec,
            area=self._area,
            warmup_steps=self._warmup_steps,
        )
        self.model.run(self._prec_raw, pbar=False)

        self.model.results = self.model.results.join(self._q_raw.rename("observed_q"), how="left")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def optimize(self, **de_kwargs: Any) -> None:  # noqa: ANN401
        """
        Run differential evolution to calibrate CN3S parameters.

        Keyword arguments are forwarded to
        :func:`scipy.optimize.differential_evolution` and override the
        defaults set below.

        The run can be interrupted at any time with ``Ctrl+C``
        (``KeyboardInterrupt``).  The ``finally`` block ensures :attr:`model`
        is fully run on the entire aligned series with the best parameters
        found so far and is immediately available after interruption.

        Default DE settings (override via ``**de_kwargs``):

        * ``seed = 42``
        * ``maxiter = 100``
        * ``tol = 1e-3``
        * ``workers = -1``
        * ``disp = True``

        Args:
            **de_kwargs: Additional keyword arguments passed to
                ``scipy.optimize.differential_evolution``.

        """
        defaults: dict[str, Any] = {
            "seed": 42,
            "maxiter": 100,
            "tol": 1e-4,
            "workers": -1,
            "disp": True,
        }

        defaults.update(de_kwargs)

        scipy_bounds: Any = self._bounds_list  # scipy accepts list[tuple[float, float]]
        try:
            self.step = 1
            differential_evolution(
                func=self._objective,
                bounds=scipy_bounds,
                callback=self._callback,
                **defaults,
            )

        except KeyboardInterrupt:
            print("\nOptimization interrupted — best model so far is in `optim.model`.")

        finally:
            # Always re-run self.model on the full series with the best known
            # parameters, regardless of how the run ended.
            if self._best_params_vec is not None:
                self._persist_model(self._best_params_vec)
