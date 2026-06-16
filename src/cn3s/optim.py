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

    #: Parameter bounds: (min, max) for each of r0, cn_i, alfa, beta, k0, k1, k2
    _BOUNDS_LIST: ClassVar[list[tuple[float, float]]] = [
        (50.0, 1000.0),  # r0:   initial groundwater storage (mm)
        (1.0, 130.0),  # cn_i: Curve Number anchor
        (0.05, 100),  # alfa: initial abstraction ratio
        (1e-4, 20),  # beta: antecedent precipitation sensitivity
        (0.01, 30),  # k0:   exponential decay factor
        (0.01, 50),  # k1:   groundwater recharge fraction
        (0.01, 2),  # k2:   baseflow recession coefficient
    ]

    def __init__(
        self,
        prec: pd.Series,
        observed_q: pd.Series,
        model: CN3S,
        train_ratio: float = 0.7,
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

        """
        if not (0.0 < train_ratio < 1.0):
            msg = f"train_ratio must be in (0, 1), got {train_ratio!r}"
            raise ValueError(msg)

        self.model = model
        self.train_ratio = train_ratio
        self._area: float = model.params.area
        self._best_test_nse: float = -math.inf
        self._best_params_vec: npt.NDArray[np.float64] | None = None

        # Align on shared index, drop any row with missing values
        aligned = pd.concat(
            [prec.rename("prec"), observed_q.rename("observed_q")],
            axis=1,
            join="inner",
        ).dropna()

        if len(aligned) < 6:  # noqa: PLR2004
            msg = "Aligned series is too short to calibrate (fewer than 6 shared time steps)."
            raise ValueError(msg)

        self.aligned = aligned

        split_idx = int(len(aligned) * train_ratio)
        self.train_idx = split_idx  # first `split_idx` rows are train
        self._n_warmup = 3  # time steps consumed as warm-up by CN3S.run()

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _run_model(self, params_vec: npt.NDArray[np.float64]) -> pd.DataFrame:
        """
        Update model parameters, run it, and return results aligned with observed_q.

        Mutates ``self.model.params`` in place.  When called from parallel workers
        (``workers=-1``) each worker operates on its own pickled copy of ``self``,
        so there are no race conditions on the main-process model.

        Args:
            params_vec: Flat array of 7 parameter values in the order expected
                by :meth:`~cn3s.model.CN3SParams.from_vector`.

        Returns:
            DataFrame with columns ``q_m3s`` (modelled) and ``observed_q``,
            indexed by the original date index (warm-up rows excluded).

        """
        self.model.params = CN3SParams.from_vector(params_vec, area=self._area)
        prec_list = self.aligned["prec"].tolist()
        self.model.run(prec_list, pbar=False)

        results = self.model.results[["q_m3s"]].copy()
        results.index = self.aligned.index[self._n_warmup :]

        return results.join(self.aligned["observed_q"], how="inner")

    def _nse(self, df: pd.DataFrame, *, train: bool) -> float:
        """
        Compute Nash-Sutcliffe Efficiency on the train or test subset.

        Args:
            df: Aligned DataFrame with ``q_m3s`` and ``observed_q`` columns.
            train: If ``True`` evaluate on the train period; otherwise test.

        Returns:
            NSE (r² score). Returns ``-inf`` when the subset is too small.

        """
        # The warm-up shrinks the available data, so the effective split index
        # must be adjusted for the rows already dropped by _run_model.
        effective_split = self.train_idx - self._n_warmup
        if effective_split <= 0:
            return -math.inf

        subset = df.iloc[:effective_split] if train else df.iloc[effective_split:]

        if len(subset) < 2:  # noqa: PLR2004
            return -math.inf

        return float(r2_score(subset["observed_q"], subset["q_m3s"]))

    def _objective(self, params_vec: npt.NDArray[np.float64]) -> float:
        """
        Objective function: negative train NSE (to be minimised).

        Args:
            params_vec: Candidate parameter vector.

        Returns:
            ``-NSE_train``.

        """
        df = self._run_model(params_vec)
        return -self._nse(df, train=True)

    def _callback(self, xk: Any, _: Any) -> None:  # noqa: ANN401
        """
        Define the callback invoked by DE after every generation.

        Computes train and test NSE for the current best vector ``xk``, prints
        a one-line status, and updates :attr:`model` whenever a new best test
        NSE is found.

        Args:
            xk: Current best parameter vector (or DE intermediate result object).
            _: Ignored argument (convergence progress).

        """
        # differential_evolution may pass an OptimizeResult object instead of a
        # plain array when using certain workers modes — extract .x if needed.
        params_vec: npt.NDArray[np.float64] = xk.x if hasattr(xk, "x") else np.asarray(xk)

        df = self._run_model(params_vec)
        train_nse = self._nse(df, train=True)
        test_nse = self._nse(df, train=False)

        print(f"{self.step} - Train NSE: {train_nse:.4f} | Test NSE: {test_nse:.4f}")
        self.step += 1

        if test_nse > self._best_test_nse:
            self._best_test_nse = test_nse
            self._best_params_vec = params_vec.copy()
            self._persist_model(params_vec)

    def _persist_model(self, params_vec: npt.NDArray[np.float64]) -> None:
        """
        Update model parameters, run the full series, and attach observed_q.

        After this call ``self.model.results`` is ready for inspection:
        indexed by date with an ``observed_q`` column appended.

        Args:
            params_vec: Parameter vector to persist.

        """
        self.model.params = CN3SParams.from_vector(params_vec, area=self._area)
        prec_list = self.aligned["prec"].tolist()
        self.model.run(prec_list, pbar=False)

        self.model.results.index = self.aligned.index[self._n_warmup :]
        self.model.results = self.model.results.join(self.aligned["observed_q"], how="left")

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

        scipy_bounds: Any = self._BOUNDS_LIST  # scipy accepts list[tuple[float, float]]
        try:
            self.step = 1
            result = differential_evolution(
                func=self._objective,
                bounds=scipy_bounds,
                callback=self._callback,
                **defaults,
            )
            # DE finished normally — record the final optimal vector
            # (may differ from the best-test-NSE vector tracked in the callback)
            self._best_params_vec = np.asarray(result.x)

        except KeyboardInterrupt:
            print("\nOptimization interrupted — best model so far is in `optim.model`.")

        finally:
            # Always re-run self.model on the full series with the best known
            # parameters, regardless of how the run ended.
            if self._best_params_vec is not None:
                self._persist_model(self._best_params_vec)
