"""Calibration optimizer for the CN3S rainfall-runoff model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from plotly.graph_objs import Figure

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.optimize import OptimizeResult, differential_evolution

from cn3s.metrics import compute_nse_from_frame
from cn3s.model import CN3S, CN3SParams
from cn3s.objectives import Objective, Objectives


class CN3SOptimizer:
    """
    Calibrate CN3S model parameters against observed discharge.

    Aligns precipitation and observed discharge by their shared index, splits the
    aligned record chronologically into train / test sets, then uses
    ``scipy.optimize.differential_evolution`` to minimise negative Nash-Sutcliffe
    Efficiency (NSE) on the training period.

    A callback is invoked after every generation to report progress and store
    a tabular history of the current best candidate.

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
            After at least one callback generation its parameters reflect the
            best candidate reported so far by SciPy.
        train_ratio: Fraction of the aligned record used for calibration.

    """

    #: Parameter bounds: (min, max) for each of r0, cn_i, alfa, beta, k0, k1, k2, act.
    #: The act bound upper limit is set dynamically in __init__ via max_act.
    _BASE_BOUNDS: ClassVar[list[tuple[float, float]]] = [
        (50.0, 1000.0),  # r0:   initial groundwater storage (mm)
        (1.0, 130.0),  # cn_i: Curve Number anchor
        (0.05, 1),  # alfa: initial abstraction ratio
        (1e-4, 1),  # beta: antecedent precipitation sensitivity
        (0.01, 1),  # k0:   exponential decay factor
        (0.01, 1),  # k1:   groundwater recharge fraction
        (0.01, 1),  # k2:   baseflow recession coefficient
        # act bound appended dynamically: (0, max_act)
    ]

    _INTEGRALITY: ClassVar[list[bool]] = [False] * 7 + [True]  # act is integral

    def __init__(
        self,
        prec: pd.Series,
        observed_q: pd.Series,
        model: CN3S,
        train_ratio: float = 0.7,
        max_act: int = 30,
        objective: str | Objective | None = None,
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
            objective: Objective to minimise.  Accepts an :class:`~cn3s.objectives.Objective`
                instance, a plain callable (wrapped automatically), or a string
                (class name matched against built-in objectives). Defaults to
                :class:`~cn3s.objectives.NSETopBlend`.

        """
        # Validate and store input parameters
        self._validate_and_assign_inputs(train_ratio, max_act)

        # Store inputs and prepare for calibration
        self.model = model  # The main model
        self.history = pd.DataFrame()
        self.result: OptimizeResult | None = None

        # Internal state
        self._area: float = model.params.area  # Basin area
        self._warmup_steps = model.params.warmup_steps  # Number of past precipitations to be used
        self.objective = self._resolve_objective(objective)

        # Keep raw series for per-candidate model evaluations
        self._prec_raw = prec
        self._q_raw = observed_q

        # Build the bounds list, appending the act bound
        self._bounds_list: list[tuple[float, float]] = [
            *self._BASE_BOUNDS,
            (0, int(self._max_act)),  # act: Average Concentration Time (days)
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

    def _resolve_objective(self, objective: str | Objective | None) -> Objective:
        """Resolve objective from str name, Objective instance, or None (default)."""
        if objective is None:
            return Objectives.NSETopBlend
        if isinstance(objective, Objective):
            return objective
        if callable(objective):
            return Objective(objective)
        if isinstance(objective, str):
            # Match by class name against all Objective subclass instances on Objectives
            for attr in vars(Objectives).values():
                if isinstance(attr, Objective) and type(attr).__name__ == objective:
                    return attr
            available = [
                type(v).__name__ for v in vars(Objectives).values() if isinstance(v, Objective)
            ]
            msg = f"No built-in objective named '{objective}'. Available: {available}"
            raise ValueError(msg)
        msg = f"objective must be a str, Objective instance, or callable; got {type(objective)!r}"
        raise TypeError(msg)

    def _run_model(self, params_vec: npt.NDArray[np.float64]) -> pd.DataFrame:
        """
        Update model parameters, run the full series, and return aligned results.

        Mutates ``self.model.params`` in place.  When called from parallel workers
        (``workers=-1``) each worker operates on its own pickled copy of ``self``,
        so there are no race conditions on the main-process model. Train/test
        splitting is handled later at scoring time so that model state is always
        propagated across the full chronology.

        Args:
            params_vec: Flat array of 8 parameter values in the order expected
                by :meth:`~cn3s.model.CN3SParams.from_vector`.

        Returns:
            DataFrame with columns ``q_m3s`` (modelled) and ``obs_q_m3s``,
            indexed by the shifted date index (warm-up rows excluded).

        """
        # Update model parameters
        self.model.params = CN3SParams.from_vector(
            params_vec,
            area=self._area,
            warmup_steps=self._warmup_steps,
        )

        self.model.run(self._prec_raw, pbar=False)

        self.model.results = self.model.results.join(
            self._q_raw.rename("obs_q_m3s"),
            how="left",
        ).dropna()

        return self.model.results[["q_m3s", "obs_q_m3s"]]

    def _select_subset(self, df: pd.DataFrame, *, train: bool) -> pd.DataFrame:
        """Select the train or test subset using the fixed calendar cutoff."""
        return df.loc[: self._train_cutoff] if train else df.loc[self._train_cutoff :]

    def _nse_on_subset(self, subset: pd.DataFrame) -> float:
        """Compute NSE on an already-selected subset."""
        return compute_nse_from_frame(
            subset,
            observed_col="obs_q_m3s",
            simulated_col="q_m3s",
            on_too_few="neg_inf",
        )

    def _nse(self, df: pd.DataFrame, *, train: bool) -> float:
        """
        Compute Nash-Sutcliffe Efficiency on the train or test subset.

        The split is based on :attr:`_train_cutoff` (a fixed calendar date)
        so that it remains stable regardless of the ACT shift applied to each
        candidate during optimisation.

        Args:
            df: Aligned DataFrame with ``q_m3s`` and ``observed_q`` columns.
            train: If ``True`` evaluate on the train period; otherwise test.

        Returns:
            NSE (r² score). Returns ``-inf`` when the subset is too small.

        """
        subset = self._select_subset(df, train=train)
        return self._nse_on_subset(subset)

    def _objective_value(self, df: pd.DataFrame, *, train: bool) -> float:
        """
        Compute the scalar objective on either the train or test subset.

        The objective implementation is selected at construction time.
        """
        subset = self._select_subset(df, train=train)
        return self.objective(subset)

    def add_history(
        self,
        params_vec: npt.NDArray[np.float64],
        *,
        step: int,
        train_objective: float,
        test_objective: float | None,
        df: pd.DataFrame | None,
    ) -> None:
        """Append or update one optimizer-history row keyed by step."""
        params = CN3SParams.from_vector(
            params_vec,
            area=self._area,
            warmup_steps=self._warmup_steps,
        )

        row = {
            "train_objective": train_objective,
            "test_objective": test_objective,
            "train_nse": self._nse(df, train=True) if df is not None else None,
            "test_nse": self._nse(df, train=False) if df is not None else None,
            "r0": params.r0,
            "cn_i": params.cn_i,
            "alfa": params.alfa,
            "beta": params.beta,
            "k0": params.k0,
            "k1": params.k1,
            "k2": params.k2,
            "act": params.act,
            "params": params,
        }

        # Keep history keyed by optimizer step for stable lookups and plotting.
        self.history.loc[step, list(row.keys())] = list(row.values())
        self.history.index.name = "step"

    def evaluate_step(self, step: int) -> dict[str, float]:
        """
        Re-evaluate a stored optimizer step and return train/test metrics.

        Re-runs CN3S on the full precipitation series for the parameters stored
        at ``step`` and computes objective and NSE values on train and test splits.
        The computed metrics are also persisted back into :attr:`history`.

        Args:
            step: Step index in :attr:`history`.

        Returns:
            Dict with ``train_objective``, ``test_objective``, ``train_nse``,
            and ``test_nse``.

        Raises:
            ValueError: If history is empty or parameter fields are missing.
            KeyError: If the requested step does not exist.

        """
        if self.history.empty:
            msg = "History is empty. Run optimize() before evaluating a step."
            raise ValueError(msg)

        if step not in self.history.index:
            msg = f"Step {step} not found in history index."
            raise KeyError(msg)

        row = self.history.loc[step]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]

        params_obj = row.get("params")
        if isinstance(params_obj, CN3SParams):
            params_vec = np.asarray(params_obj.as_list(), dtype=np.float64)
        else:
            required = ["r0", "cn_i", "alfa", "beta", "k0", "k1", "k2", "act"]
            missing = [name for name in required if name not in row.index or pd.isna(row[name])]
            if missing:
                msg = f"History step {step} is missing parameter values: {missing}"
                raise ValueError(msg)

            params_vec = np.asarray([float(row[name]) for name in required], dtype=np.float64)

        df = self._run_model(params_vec)
        train_objective = self._objective_value(df, train=True)
        test_objective = self._objective_value(df, train=False)
        train_nse = self._nse(df, train=True)
        test_nse = self._nse(df, train=False)

        self.add_history(
            params_vec,
            step=step,
            train_objective=train_objective,
            test_objective=test_objective,
            df=df,
        )

        return {
            "train_objective": train_objective,
            "test_objective": test_objective,
            "train_nse": train_nse,
            "test_nse": test_nse,
        }

    def _objective(self, params_vec: npt.NDArray[np.float64]) -> float:
        """
        Objective function: negative train NSE (to be minimised).

        Args:
            params_vec: Candidate parameter vector.

        Returns:
            ``-NSE_train``.

        """
        df = self._run_model(params_vec)

        return self._objective_value(df, train=True)

    def _callback(self, intermediate_result: OptimizeResult) -> None:
        """
        Define the callback invoked by DE after every generation.

        Uses SciPy's best-so-far candidate for the generation, prints a one-line
        status, and stores a history row.

        Args:
            intermediate_result: SciPy ``OptimizeResult`` carrying the current
                best parameter vector in ``x`` and its objective value in ``fun``.

        """
        params_vec = np.asarray(intermediate_result.x, dtype=np.float64)
        train_objective = float(intermediate_result.fun)

        self.add_history(
            params_vec,
            step=self.step,
            train_objective=train_objective,
            test_objective=None,
            df=None,
        )

        params_vec = [round(float(p), 2) for p in params_vec]

        print(f"{self.step} - Train objective: {train_objective:.4f} - {params_vec}")
        self.step += 1

    def _persist_model(self, params_vec: npt.NDArray[np.float64]) -> None:
        """
        Update model parameters, run the full series, and attach observed_q.

        After this call ``self.model.results`` is ready for inspection:
        indexed by date with an ``observed_q`` column appended.

        Args:
            params_vec: Parameter vector to persist.

        """
        self._run_model(params_vec)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def plot_step(
        self,
        step: int,
        *,
        q_headroom: float = 1.2,
        prec_headroom: float = 1.5,
        title: str = "CN3S: Simulated vs Observed",
        show: bool = False,
        height: int = 500,
        width: int = 1000,
    ) -> Figure:
        """
        Plot model results for a specific optimisation step.

        Calls :meth:`evaluate_step` to re-run the model with the stored parameters,
        then delegates to :meth:`~cn3s.model.CN3S.plot` with the train/test split
        marker and train / test NSE values shown in the title.

        Args:
            step: Step index in :attr:`history`.
            q_headroom: Multiplier applied to max discharge to set y-axis upper bound.
            prec_headroom: Multiplier applied to max precipitation for y2 upper bound.
            title: Figure title prefix.
            show: Whether to immediately render the figure with ``fig.show()``.
            height: Figure height in pixels.
            width: Figure width in pixels.

        Returns:
            Plotly Figure object.

        Raises:
            ValueError: If history is empty or parameter fields are missing.
            KeyError: If the requested step does not exist.
            ImportError: If Plotly is not installed.

        """
        # Evaluate the step: updates model params, runs model, returns metrics
        metrics = self.evaluate_step(step)
        train_nse = metrics["train_nse"]
        test_nse = metrics["test_nse"]

        # Re-run the model without dropna so the full series is available for plotting.
        # (evaluate_step internally calls _run_model which drops rows without obs_q.)
        row = self.history.loc[step]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]

        params_obj = row.get("params")
        if isinstance(params_obj, CN3SParams):
            params_vec = np.asarray(params_obj.as_list(), dtype=np.float64)
        else:
            required = ["r0", "cn_i", "alfa", "beta", "k0", "k1", "k2", "act"]
            params_vec = np.asarray([float(row[name]) for name in required], dtype=np.float64)

        self.model.params = CN3SParams.from_vector(
            params_vec,
            area=self._area,
            warmup_steps=self._warmup_steps,
        )
        self.model.run(self._prec_raw, pbar=False)
        self.model.results = self.model.results.join(
            self._q_raw.rename("obs_q_m3s"),
            how="left",
        )
        self.model.last_nse = train_nse

        # Locate the train/test split position in model.results by date.
        split_pos = int((self.model.results.index < self._train_cutoff).sum())
        split_pos = max(0, min(split_pos, len(self.model.results) - 1))

        # Generate the base figure via CN3S.plot
        fig = self.model.plot(
            split=split_pos,
            q_headroom=q_headroom,
            prec_headroom=prec_headroom,
            title=title,
            show=False,
            height=height,
            width=width,
        )

        # Replace the trailing NSE line added by CN3S.plot with a train/test breakdown.
        current_title: str = fig.layout.title.text  # type: ignore[union-attr]
        nse_line = f"Train NSE = {train_nse:.3f} | Test NSE = {test_nse:.3f}"
        new_title = current_title.rsplit("<br>", 1)[0] + f"<br>{nse_line}"
        fig.update_layout(
            title={"text": new_title, "x": 0.5, "xanchor": "center", "font": {"size": 12}},
        )

        if show:
            fig.show()

        return fig

    def optimize(self, **de_kwargs: Any) -> None:
        """
        Run differential evolution to calibrate CN3S parameters.

        Keyword arguments are forwarded to
        :func:`scipy.optimize.differential_evolution` and override the
        defaults set below.

        The run can be interrupted at any time with ``Ctrl+C``
        (``KeyboardInterrupt``). On successful completion the final SciPy result
        is persisted to :attr:`model`; during the run, callback updates keep
        :attr:`model` aligned with the latest callback-best candidate.

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
        self.history = pd.DataFrame()
        self.result = None

        try:
            self.step = 1
            self.result = differential_evolution(
                func=self._objective,
                bounds=scipy_bounds,
                callback=self._callback,
                integrality=self._INTEGRALITY,
                **defaults,
            )

        except KeyboardInterrupt:
            print("\nOptimization interrupted — best model so far is in `optim.model`.")

        finally:
            # Persist the final SciPy best solution when the optimizer returns one.
            if self.result is not None:
                self._persist_model(np.asarray(self.result.x, dtype=np.float64))
