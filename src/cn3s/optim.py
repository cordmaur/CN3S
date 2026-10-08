
"""Calibration optimizer for the CN3S rainfall-runoff model."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from plotly.graph_objs import Figure

    from cn3s.model import CN3S

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.optimize import OptimizeResult, differential_evolution

from cn3s.metrics import compute_nse_from_frame
from cn3s.objectives import ExtremeFlowBlend, Objective, Objectives
from cn3s.params import CN3SParams


def _json_ready(value: Any) -> Any:
    """
    Convert calibration records into standard JSON values.

    Args:
        value: Parameters, metrics, or descriptive solver settings.

    Returns:
        JSON-compatible data with nonfinite scores represented as null. Solver
        execution objects are described by name rather than serialized as code.

    """
    if isinstance(value, np.ndarray):
        value = value.tolist()
    elif isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return getattr(value, "__name__", type(value).__name__)


class CN3SOptimizer:
    """
    Calibrate CN3S model parameters against observed discharge.

    Aligns precipitation and observed discharge by their shared index, splits the
    aligned record chronologically into train / test sets, then uses
    ``scipy.optimize.differential_evolution`` to minimize the selected objective
    on the training period.

    A callback is invoked after every generation to report progress and store
    a tabular history of the current best candidate.

    The optimiser mutates :attr:`model` in place throughout calibration — the
    model passed at construction is used both for objective evaluations and as the
    final result container.  Interrupting the run (``KeyboardInterrupt``) is safe:
    the ``finally`` block guarantees :attr:`model` always holds a fully-run model
    with the best parameters from the last completed generation, or the initial state
    if interrupted before the first generation completes.

    Typical usage::

        params = CN3SParams(area=34334.0)
        model = CN3S(params, freq="M")

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

    def __init__(
        self,
        prec: pd.Series,
        observed_q: pd.Series,
        model: CN3S,
        train_ratio: float = 0.7,
        objective: Objective | None = None,
        optimize_params: tuple[str, ...] | None = None,
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
            objective: Objective instance to minimize, defaulting to NSETopBlend.
                Wrap custom functions explicitly with Objective(fn).
            optimize_params: Names of free parameters, in candidate-vector order.
                Defaults to all names in model.params.bounds. Omitted parameters
                retain their values at the start of each optimization run.

        Raises:
            ValueError: If train_ratio, parameter selection, or record length is invalid.

        """
        if not 0 < train_ratio < 1:
            msg = f"train_ratio must be in (0, 1), got {train_ratio!r}"
            raise ValueError(msg)
        self.train_ratio = train_ratio
        self.objective = Objectives.NSETopBlend if objective is None else objective

        self.optimize_params = (
            tuple(model.params.bounds) if optimize_params is None else tuple(optimize_params)
        )
        calibration_names = CN3SParams().bounds
        if (
            not self.optimize_params
            or len(set(self.optimize_params)) != len(self.optimize_params)
            or any(name not in calibration_names for name in self.optimize_params)
        ):
            msg = "optimize_params must be nonempty and contain unique calibration parameter names."
            raise ValueError(msg)

        self.model = model
        self.history = pd.DataFrame()
        self.result: OptimizeResult | None = None
        self._final_params: CN3SParams | None = None
        self._final_step: int | None = None
        self._run_metadata: dict[str, Any] = {}
        self._initial_params = replace(model.params, bounds=model.params.bounds.copy())
        self._prec_raw = prec
        self._q_raw = observed_q

        # Align at ACT=0 to determine the reference train/test cutoff date
        self.aligned = pd.concat(
            [prec.rename("prec"), observed_q.rename("observed_q")],
            axis=1,
            join="inner",
        ).dropna()

        # Need enough values to run the model and still compute r2_score
        # on at least two aligned points.
        min_required = model.params.warmup_steps + 3
        if len(self.aligned) < min_required:
            msg = (
                "Aligned series is too short to calibrate "
                f"(requires at least {min_required} shared time steps for "
                f"warmup_steps={model.params.warmup_steps})."
            )
            raise ValueError(msg)

        # Determine where is the TRAIN/TEST split index (based on the unshifted alignment)
        split_idx = int(len(self.aligned) * self.train_ratio)
        self.train_idx = split_idx  # first `split_idx` rows are train (for display)

        # Use a date-based cutoff so the split is stable regardless of ACT shift
        self._train_cutoff = cast("pd.Timestamp", self.aligned.index[split_idx])

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #
    def _params_from_vector(self, vector: npt.NDArray[np.float64]) -> CN3SParams:
        """
        Combine free candidate values with the run's fixed parameter snapshot.

        Args:
            vector: Values in optimize_params order; ACT is an integer lag in days
                for daily runs or calendar months for monthly runs.

        Returns:
            Complete parameters with unchanged fixed values and basin descriptors.

        """
        updates: dict[str, Any] = {
            name: float(value) for name, value in zip(self.optimize_params, vector, strict=True)
        }
        if "act" in updates:
            updates["act"] = round(updates["act"])
        params: CN3SParams = replace(
            self._initial_params,
            bounds=self._initial_params.bounds.copy(),
            **updates,
        )
        return params

    def _run_model(self, params: CN3SParams) -> pd.DataFrame:
        """
        Update model parameters, run the full series, and return aligned results.

        Mutates ``self.model.params`` in place.  When called from parallel workers
        (``workers=-1``) each worker operates on its own pickled copy of ``self``,
        so there are no race conditions on the main-process model. Train/test
        splitting is handled later at scoring time so that model state is always
        propagated across the full chronology.

        Args:
            params: Complete calibration values and fixed basin descriptors.

        Returns:
            DataFrame with columns ``q_m3s`` (modelled) and ``obs_q_m3s``,
            indexed by the shifted date index (warm-up rows excluded).

        """
        self.model.params = replace(params, bounds=params.bounds.copy())

        self.model.run(self._prec_raw, pbar=False)

        self.model.results = self.model.results.join(
            self._q_raw.rename("obs_q_m3s"),
            how="left",
        )

        # Preserve all simulated dates for plots; only paired values enter scoring.
        paired: pd.DataFrame = self.model.results[["q_m3s", "obs_q_m3s"]].dropna()
        return paired

    def _select_subset(self, df: pd.DataFrame, *, train: bool) -> pd.DataFrame:
        """
        Select paired discharges using the fixed calendar cutoff.

        Args:
            df: Dated discharge observations and simulations in m³/s.
            train: Whether to select the calibration rather than test period.

        Returns:
            The requested chronological subset, using the existing inclusive cutoff.

        """
        return df.loc[: self._train_cutoff] if train else df.loc[self._train_cutoff :]

    def _nse(self, df: pd.DataFrame, *, train: bool) -> float:
        """
        Compute Nash-Sutcliffe Efficiency on the train or test subset.

        The split is based on :attr:`_train_cutoff` (a fixed calendar date)
        so that it remains stable regardless of the ACT shift applied to each
        candidate during optimisation.

        Args:
            df: Aligned DataFrame with ``q_m3s`` and ``obs_q_m3s`` columns.
            train: If ``True`` evaluate on the train period; otherwise test.

        Returns:
            NSE (r² score). Returns ``-inf`` when the subset is too small.

        """
        subset = self._select_subset(df, train=train)
        return float(
            compute_nse_from_frame(
                subset,
                observed_col="obs_q_m3s",
                simulated_col="q_m3s",
                on_too_few="neg_inf",
            ),
        )

    def _objective_value(self, df: pd.DataFrame, *, train: bool) -> float:
        """
        Compute the scalar objective on either the train or test subset.

        The objective implementation is selected at construction time.

        Args:
            df: Paired observed and simulated discharges in m³/s.
            train: Whether to evaluate the calibration rather than test period.

        Returns:
            Objective value on the requested chronological subset.

        """
        subset = self._select_subset(df, train=train)
        return float(self.objective(subset))

    def add_history(
        self,
        params: CN3SParams,
        *,
        step: int,
        train_objective: float,
        test_objective: float | None,
        df: pd.DataFrame | None,
        stage: str = "generation",
    ) -> None:
        """
        Store a complete parameter snapshot and metrics for an optimizer step.

        Args:
            params: Full parameters, including fixed values and basin descriptors.
            step: History index identifying the generation.
            train_objective: Dimensionless training loss.
            test_objective: Test loss, or None if not evaluated.
            df: Paired discharges in m³/s, or None if metrics are deferred.
            stage: Whether this is the initial guess, a generation, or final result.

        """
        params = replace(params, bounds=params.bounds.copy())

        row = {
            "stage": stage,
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

        params = row.get("params")
        if not isinstance(params, CN3SParams):
            # Older saved histories may contain full parameter columns only.
            required = tuple(CN3SParams().bounds)
            missing = [name for name in required if name not in row.index or pd.isna(row[name])]
            if missing:
                msg = f"History step {step} is missing parameter values: {missing}"
                raise ValueError(msg)
            params = CN3SParams.from_vector(
                [float(row[name]) for name in required],
                name=self._initial_params.name,
                area=self._initial_params.area,
                warmup_steps=self._initial_params.warmup_steps,
                bounds=self._initial_params.bounds.copy(),
            )
        else:
            # Pickled params from before bounds moved here may lack this new field.
            params = replace(
                params,
                bounds=getattr(params, "bounds", self._initial_params.bounds).copy(),
            )

        df = self._run_model(params)
        train_objective = self._objective_value(df, train=True)
        test_objective = self._objective_value(df, train=False)
        train_nse = self._nse(df, train=True)
        test_nse = self._nse(df, train=False)

        self.add_history(
            params,
            step=step,
            train_objective=train_objective,
            test_objective=test_objective,
            df=df,
            stage=str(row.get("stage", "generation")),
        )

        return {
            "train_objective": train_objective,
            "test_objective": test_objective,
            "train_nse": train_nse,
            "test_nse": test_nse,
        }

    def _objective(self, params_vec: npt.NDArray[np.float64]) -> float:
        """
        Compute the selected training loss for a free-parameter candidate.

        Args:
            params_vec: Candidate values in optimize_params order.

        Returns:
            Dimensionless objective value to minimize.

        """
        df = self._run_model(self._params_from_vector(params_vec))

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

        self._best_params = self._params_from_vector(params_vec)
        self.model.params = replace(self._best_params, bounds=self._best_params.bounds.copy())
        self.add_history(
            self._best_params,
            step=self.step,
            train_objective=train_objective,
            test_objective=None,
            df=None,
        )

        values = dict(zip(self.optimize_params, map(float, params_vec), strict=True))
        print(f"{self.step} - Train objective: {train_objective:.4f} - {values}")
        self.step += 1

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def populate_history(self) -> None:
        """
        Fill missing history metrics and restore the final calibrated model.

        Each incomplete step is simulated once to fill test objective and train/test
        NSE, also recomputing training objective. The final row includes any SciPy
        polishing and is not counted as another optimization generation.

        Raises:
            ValueError: If no completed or interrupted calibration is available.

        """
        if getattr(self, "_run_metadata", {}).get("status") == "failed":
            msg = "Optimization failed; only completed or interrupted runs can be saved."
            raise ValueError(msg)
        final_params: CN3SParams | None = getattr(self, "_final_params", None)
        if final_params is None:
            # Save existing in-memory runs without requiring another calibration.
            if self.result is None and self.history.empty:
                msg = "Run optimize() before populating or saving its history."
                raise ValueError(msg)
            params = getattr(self, "_best_params", self.model.params)
            final_params = replace(params, bounds=params.bounds.copy())
            self._final_params = final_params

        if "stage" not in self.history and not self.history.empty:
            self.history["stage"] = "generation"
        metrics = ("train_objective", "test_objective", "train_nse", "test_nse")
        try:
            for step in list(self.history.index):
                if any(pd.isna(self.history.loc[step].get(metric)) for metric in metrics):
                    self.evaluate_step(int(step))
        finally:
            # History inspection must not replace the final solution being exported.
            df = self._run_model(final_params)

        final_step: int | None = getattr(self, "_final_step", None)
        if final_step is None:
            final_step = int(self.history.index.max()) + 1 if not self.history.empty else 1
            self._final_step = final_step
        self.add_history(
            final_params,
            step=final_step,
            train_objective=self._objective_value(df, train=True),
            test_objective=self._objective_value(df, train=False),
            df=df,
            stage="final",
        )

    def save(self, path: str | Path) -> None:
        """
        Save final parameters, metadata, and complete scalar history as one JSON.

        Calls populate_history() before writing. Station name and drainage area
        belong to the saved parameters because discharge conversion depends on area.
        Nonfinite/unavailable metrics are written as null; custom objective code
        and input time series are not embedded in the artifact.

        Args:
            path: Destination JSON file. Parent directories are created as needed.

        Raises:
            ValueError: If no calibration is available to save.

        """
        if not self.history[["train_objective", "test_objective", "train_nse", "test_nse"]].all(
            axis=None
        ):
            self.populate_history()

        final_params = self._final_params
        assert final_params is not None
        assert self._final_step is not None

        settings = {
            name: value
            for name, value in vars(self.objective).items()
            if not name.startswith("_") and name != "reference_observed"
        }
        if isinstance(self.objective, ExtremeFlowBlend):
            reference = self.objective.reference_observed
            if reference is not None:
                low = float(reference.quantile(self.objective.low_quantile))
                high = float(reference.quantile(self.objective.high_quantile))
                groups = (
                    reference[reference <= low],
                    reference[(reference > low) & (reference < high)],
                    reference[(reference >= high) & (reference > low)],
                )
                settings["reference"] = {
                    "low_threshold": low,
                    "high_threshold": high,
                    "scales": [
                        max(float(group.mean()), self.objective.discharge_floor)
                        if not group.empty
                        else self.objective.discharge_floor
                        for group in groups
                    ],
                }

        # Older in-memory runs may not have recorded solver settings at run start.
        metadata: dict[str, Any] = {
            "status": "existing_run",
            "iterations": int((self.history["stage"] == "generation").sum()),
            "nfev": None,
            "frequency": self.model.freq,
            "act_units": "days" if self.model.freq == "D" else "calendar_months",
            "train_ratio": self.train_ratio,
            "train_cutoff": self._train_cutoff.isoformat(),
            "optimize_params": list(self.optimize_params),
            "objective": {"name": self.objective.name, "settings": settings},
        }
        if self.result is not None:
            metadata.update(
                iterations=int(self.result.nit),
                nfev=int(self.result.nfev),
                message=str(self.result.message),
                status="completed" if self.result.success else "stopped",
            )
        metadata.update(getattr(self, "_run_metadata", {}))
        metadata["saved_at"] = datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()
        metadata["final_step"] = self._final_step
        metadata["final_metrics"] = self.history.loc[
            self._final_step,
            ["train_objective", "test_objective", "train_nse", "test_nse"],
        ].to_dict()
        history = self.history.drop(columns="params").reset_index().to_dict(orient="records")
        payload = _json_ready(
            {"params": asdict(final_params), "metadata": metadata, "history": history},
        )
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )

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

        # evaluate_step already retains all simulated dates for plotting.
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
        current_title: str = fig.layout.title.text
        nse_line = f"Train NSE = {train_nse:.3f} | Test NSE = {test_nse:.3f}"
        new_title = current_title.rsplit("<br>", 1)[0] + f"<br>{nse_line}"
        fig.update_layout(
            title={"text": new_title, "x": 0.5, "xanchor": "center", "font": {"size": 12}},
        )

        if show:
            fig.show()

        return fig

    def optimize(self, **de_kwargs: Any) -> None:  # noqa: PLR0912, PLR0915
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
        * ``tol = 1e-4``
        * ``workers = -1``
        * ``disp = True``
        * ``x0`` from current model.params, in optimize_params order

        Args:
            **de_kwargs: Additional keyword arguments passed to
                ``scipy.optimize.differential_evolution``. Pass x0 to override
                the selected starting values, or x0=None to omit the initial guess.

        Raises:
            ValueError: If ACT bounds contain no integer, or x0 does not match
                the selected bounds or integer ACT.

        """
        # Freeze fixed values before candidate runs mutate the shared model.
        self._initial_params = replace(self.model.params, bounds=self.model.params.bounds.copy())
        self._best_params = self._initial_params
        bounds: Any = [self._initial_params.bounds[name] for name in self.optimize_params]
        if "act" in self.optimize_params:
            act_index = self.optimize_params.index("act")
            lower, upper = bounds[act_index]
            # ACT can only take integers inside the requested search interval.
            lower, upper = int(np.ceil(lower)), int(np.floor(upper))
            if lower > upper:
                msg = "ACT bounds must contain at least one integer lag."
                raise ValueError(msg)
            bounds[act_index] = (lower, upper)
        # Match the free-vector order, including when ACT is omitted or reordered.
        integrality = [name == "act" for name in self.optimize_params]
        defaults: dict[str, Any] = {
            "seed": 42,
            "maxiter": 100,
            "popsize": 15,
            "polish": True,
            "tol": 1e-4,
            "workers": -1,
            "disp": True,
            "x0": [getattr(self._initial_params, name) for name in self.optimize_params],
        }

        defaults.update(de_kwargs)

        if defaults["x0"] is not None:
            x0 = np.asarray(defaults["x0"], dtype=float)
            if x0.shape != (len(self.optimize_params),):
                msg = "x0 must contain one value per selected parameter, in optimize_params order."
                raise ValueError(msg)
            for name, value, (lower, upper) in zip(self.optimize_params, x0, bounds, strict=True):
                if not np.isfinite(value) or not lower <= value <= upper:
                    msg = f"x0 for {name} must be finite and within bounds {(lower, upper)}."
                    raise ValueError(msg)
                if name == "act" and value != round(float(value)):
                    msg = "x0 ACT must be integer (days for daily runs; months for monthly)."
                    raise ValueError(msg)
        self.history = pd.DataFrame()
        self.result = None
        self._final_params = None
        self._final_step = None
        self._run_metadata = {
            "solver_settings": _json_ready(defaults),
            "bounds": bounds,
            "integrality": integrality,
            "optimize_params": list(self.optimize_params),
            "frequency": self.model.freq,
            "act_units": "days" if self.model.freq == "D" else "calendar_months",
            "train_ratio": self.train_ratio,
            "train_cutoff": self._train_cutoff.isoformat(),
            "status": "failed",
        }

        try:
            self.step = 1
            if defaults["x0"] is not None:
                self._best_params = self._params_from_vector(
                    np.asarray(defaults["x0"], dtype=float),
                )
                df = self._run_model(self._best_params)
                self.add_history(
                    self._best_params,
                    step=0,
                    train_objective=self._objective_value(df, train=True),
                    test_objective=None,
                    df=None,
                    stage="initial",
                )
            self.result = differential_evolution(
                func=self._objective,
                bounds=bounds,
                callback=self._callback,
                integrality=integrality,
                **defaults,
            )

        except KeyboardInterrupt:
            self._run_metadata.update(
                status="interrupted",
                iterations=self.step - 1,
                nfev=None,
                message="Interrupted; retained the last completed generation or initial guess.",
            )
            print("\nOptimization interrupted — best model so far is in `optim.model`.")

        else:
            self._run_metadata.update(
                status="completed" if self.result.success else "stopped",
                iterations=int(self.result.nit),
                nfev=int(self.result.nfev),
                message=str(self.result.message),
            )

        finally:
            # Restore the returned solution or last completed generation on interruption.
            if self.result is not None:
                self._best_params = self._params_from_vector(
                    np.asarray(self.result.x, dtype=np.float64),
                )
            df = self._run_model(self._best_params)
            if self._run_metadata["status"] != "failed":
                self._final_params = replace(
                    self._best_params,
                    bounds=self._best_params.bounds.copy(),
                )
                self._final_step = self.step
                self.add_history(
                    self._final_params,
                    step=self._final_step,
                    train_objective=self._objective_value(df, train=True),
                    test_objective=self._objective_value(df, train=False),
                    df=df,
                    stage="final",
                )
