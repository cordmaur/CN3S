"""Manual parameter experiments against a fixed, immutable calibration reference."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import asdict
from time import perf_counter
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pandas as pd

from cn3s.artifacts import CalibrationStore
from cn3s.evaluation import CalibrationEvaluation
from cn3s.metrics import flow_metrics
from cn3s.model import CN3S, CN3SParams

if TYPE_CHECKING:
    from collections.abc import Mapping


class ModelPlayground:
    """Run one simulation per explicit action, without constructing an optimizer."""

    PARAMETER_RANGES: ClassVar[dict[str, tuple[float, float]]] = {
        "r0": (0, 1e6),
        "cn_i": (1e-6, 130),
        "alfa": (0, 1),
        "beta": (0, 1),
        "k0": (0, 1),
        "k1": (0, 1),
        "k2": (0, 1),
        "act": (0, 365),
        "warmup_steps": (1, 366),
    }

    def __init__(self, reference: CalibrationEvaluation) -> None:
        """Fix forcing, observations, basin area and split to the selected run."""
        self.reference = reference
        self.trial: CalibrationEvaluation | None = None
        self.elapsed_seconds: float | None = None
        self.controls: dict[str, Any] = {}
        self._output: Any = None
        self._period: Any = None
        self._run_button: Any = None
        self._save_button: Any = None
        self._label: Any = None

    def parameter_values(self) -> dict[str, float | int]:
        """Return editable saved values for widgets or the plain Python interface."""
        return {key: self.reference.summary["params"][key] for key in self.PARAMETER_RANGES}

    def run(self, parameters: Mapping[str, float | int]) -> CalibrationEvaluation:
        """
        Apply overrides to saved parameters and simulate once; do not write files.

        Trial metrics retain the saved split. Use ``compare`` for identical paired
        dates when ACT or antecedent length changes. Edits are exploratory, not an
        independent validation or an optimized calibration.
        """
        reference = self.reference
        if reference.rain is None or reference.discharge is None:
            msg = (
                "Manual replay requires matching saved inputs; stale legacy inputs are unavailable"
            )
            raise ValueError(msg)
        values = self.parameter_values()
        for key, value in parameters.items():
            if key not in values:
                msg = f"Parameter is not editable: {key}"
                raise ValueError(msg)
            lower, upper = self.PARAMETER_RANGES[key]
            if isinstance(value, bool) or not math.isfinite(value) or not lower <= value <= upper:
                msg = f"{key} must be finite and between {lower} and {upper}"
                raise ValueError(msg)
            if key in ("act", "warmup_steps") and int(value) != value:
                msg = f"{key} must be an integer"
                raise ValueError(msg)
            values[key] = int(value) if key in ("act", "warmup_steps") else float(value)
        if reference.frequency == "M" and values["act"] != 0:
            msg = "Monthly simulation requires act=0"
            raise ValueError(msg)
        if values["warmup_steps"] >= len(reference.rain):
            msg = "Antecedent length must leave at least one simulated step"
            raise ValueError(msg)
        params = CN3SParams(**{**reference.summary["params"], **values})
        model = CN3S(params, cast("Any", reference.frequency))
        started = perf_counter()
        model.run(reference.rain, pbar=False)
        modeled = model.results.join(reference.discharge.rename("obs_q_m3s"), how="left")
        elapsed = perf_counter() - started
        summary = deepcopy(reference.summary)
        summary.update(
            run_id="unsaved-trial",
            kind="manual",
            status="manual",
            parent_run_id=reference.run_id,
            parent_summary_sha256=hashlib.sha256(
                json.dumps(reference.summary, sort_keys=True, default=str).encode(),
            ).hexdigest(),
            reference_params=deepcopy(reference.summary["params"]),
            max_act=None,
            params=asdict(params),
            warmup_steps=params.warmup_steps,
            converged=False,
            label="Manual experiment",
            objective="Not optimized",
            objective_config={},
            optimizer_options={},
            solver={},
            timings_seconds={"simulation": elapsed},
        )
        for part in ("train", "test"):
            subset = (
                modeled.loc[modeled.index < reference.cutoff]
                if part == "train"
                else modeled.loc[modeled.index >= reference.cutoff]
            )
            metrics = flow_metrics(subset, reference.frequency)
            nse = float(metrics["NSE"])
            summary[f"{part}_nse"] = nse if math.isfinite(nse) else None
            summary[f"{part}_objective"] = None
            summary[f"{part}_count"] = int(metrics["paired_steps"])
        trial = CalibrationEvaluation(
            summary,
            modeled,
            pd.DataFrame(),
            reference.rain,
            reference.discharge,
            reference.metadata,
            data_root=reference.data_root,
            input_note=reference.input_note,
            watershed_bytes=reference.watershed_bytes,
        )
        self.trial = trial
        self.elapsed_seconds = elapsed
        return trial

    def reset(self) -> CalibrationEvaluation:
        """Discard the trial and restore saved values without rerunning the model."""
        self.trial = None
        self.elapsed_seconds = None
        for key, value in self.parameter_values().items():
            if key in self.controls:
                self.controls[key].value = value
        return self.reference

    def comparison(self, period: str = "test") -> pd.DataFrame:
        """Compare trial and saved fit using common response dates and observations."""
        return self.reference.compare(self.trial or self.reference, period)

    def save(self, label: str) -> str:
        """Explicitly save a manual child run without changing latest or selected."""
        if self.trial is None:
            msg = "Run a trial before saving an experiment"
            raise ValueError(msg)
        if not label.strip():
            msg = "Give the experiment a label before saving"
            raise ValueError(msg)
        trial = self.trial
        assert trial.rain is not None
        assert trial.discharge is not None
        summary = deepcopy(trial.summary)
        summary["label"] = label.strip()
        summary.pop("run_id", None)
        saved = CalibrationStore(trial.data_root).save(
            summary,
            trial.modeled,
            trial.history,
            trial.rain,
            trial.discharge,
            trial.metadata,
            watershed_bytes=trial.watershed_bytes,
            copy_current_watershed=False,
        )
        return str(saved["run_id"])

    def widget(self, *, period: str = "test") -> Any:
        """Build an explicit Run/Reset/Save notebook interface with lazy widget imports."""
        import ipywidgets as widgets  # noqa: PLC0415

        self._period = widgets.Dropdown(
            options=["train", "test", "all"], value=period, description="Evaluate:"
        )
        for key, value in self.parameter_values().items():
            integer = key in ("act", "warmup_steps")
            control_type = widgets.IntText if integer else widgets.FloatText
            self.controls[key] = control_type(
                value=value, description=key, style={"description_width": "110px"}
            )
        self.controls["act"].disabled = self.reference.frequency == "M"
        self._output = widgets.Output()
        self._run_button = widgets.Button(description="Run simulation", button_style="primary")
        reset_button = widgets.Button(description="Reset to saved")
        save_button = widgets.Button(description="Save experiment", disabled=True)
        self._save_button = save_button
        self._label = widgets.Text(placeholder="Experiment label", description="Save as:")
        self._run_button.on_click(self._on_run)
        reset_button.on_click(self._on_reset)
        save_button.on_click(self._on_save)
        if self.reference.rain is None or self.reference.discharge is None:
            self._run_button.disabled = True
        panel = widgets.VBox(
            [
                widgets.HTML(
                    "<b>Parameter experiments</b><br>Change values, then click Run simulation. "
                    "One simulation; no optimization. The saved reference stays fixed. "
                    "Repeated test-period tuning is exploratory, not independent validation."
                ),
                widgets.HBox(
                    [
                        widgets.VBox(list(self.controls.values())[:5]),
                        widgets.VBox(list(self.controls.values())[5:]),
                    ]
                ),
                widgets.HBox([self._period, self._run_button, reset_button]),
                widgets.HBox([self._label, save_button]),
                self._output,
            ]
        )
        for control in self.controls.values():
            control.observe(self._on_parameter_change, names="value")
        self._period.observe(self._on_period_change, names="value")
        self._render()
        return panel

    def _render(self) -> None:
        import matplotlib.pyplot as plt  # noqa: PLC0415
        from IPython.display import display  # noqa: PLC0415

        assert self._output is not None
        with self._output:
            self._output.clear_output(wait=True)
            active = self.trial or self.reference
            print(f"Reference: {self.reference.run_id}. {self.reference.input_note}.")
            if self.trial is not None:
                print(f"Unsaved trial simulation: {self.elapsed_seconds:.2f} seconds")
            display(self.comparison(self._period.value))
            for fig in (
                active.hydrograph(
                    self._period.value, reference=self.reference if self.trial else None
                ),
                active.scatter(
                    self._period.value, reference=self.reference if self.trial else None
                ),
            ):
                display(fig)
                plt.close(fig)

    def _on_run(self, _: Any) -> None:
        self._run_button.disabled = True
        try:
            with self._output:
                self._output.clear_output(wait=True)
                print("Running one simulation…", flush=True)
            self.run({key: control.value for key, control in self.controls.items()})
            self._save_button.disabled = False
            self._render()
        except (ValueError, TypeError, ArithmeticError) as exc:
            with self._output:
                print(f"Trial was not applied: {exc}")
        finally:
            self._run_button.disabled = False

    def _on_reset(self, _: Any) -> None:
        self.reset()
        self._save_button.disabled = True
        self._render()

    def _on_save(self, _: Any) -> None:
        with self._output:
            try:
                print(f"Saved manual experiment: {self.save(self._label.value)}")
            except (ValueError, OSError) as exc:
                print(f"Experiment was not saved: {exc}")

    def _on_parameter_change(self, _: Any) -> None:
        """Require simulation of pending field edits before saving them."""
        self._save_button.disabled = True

    def _on_period_change(self, _: Any) -> None:
        """Redraw the display period without running another simulation."""
        self._render()
