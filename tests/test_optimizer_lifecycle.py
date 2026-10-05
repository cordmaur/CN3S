"""Final-best simulation, refinement, and interruption lifecycle guarantees."""

# Literal vectors and evaluation counts are the expected lifecycle contract.
# ruff: noqa: PLR2004

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeResult

from cn3s import CN3S, CN3SOptimizer, CN3SParams

if TYPE_CHECKING:
    import pytest


def optimizer() -> CN3SOptimizer:
    """Use a small nonconstant record for lifecycle tests."""
    dates = pd.date_range("2001-01-01", periods=40)
    rain = pd.Series(20 + np.arange(40) % 12, index=dates)
    q = pd.Series(1 + np.arange(40) % 7, index=dates)
    return CN3SOptimizer(rain, q, CN3S(CN3SParams(area=10), "D"), max_act=5, objective="PlainNSE")


def test_final_simulated_once_and_metrics_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Metrics calls cannot repeat final simulation or use another candidate's state."""
    opt = optimizer()
    vector = np.asarray(opt.model.params.as_list())

    def de(**_: Any) -> OptimizeResult:
        return OptimizeResult(x=vector, fun=1.0, success=False, message="budget", nfev=4, nit=1)

    calls = []
    original = opt.model.run

    def run(*args: Any, **kwargs: Any) -> None:
        calls.append(1)
        original(*args, **kwargs)

    monkeypatch.setattr("cn3s.optim.differential_evolution", de)
    monkeypatch.setattr(opt.model, "run", run)
    opt.optimize(polish=False, progress=False)
    first = opt.evaluate_best()
    assert opt.evaluate_best() == first
    assert len(calls) == 1
    assert "final_simulation" in opt.timings


def test_interrupt_recovers_callback_best(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recovery uses callback parameters even when the last evaluated candidate differs."""
    opt = optimizer()
    vector = np.asarray(opt.model.params.as_list())
    vector[-1] = 2

    def de(**kwargs: Any) -> OptimizeResult:
        kwargs["callback"](OptimizeResult(x=vector, fun=1.0, nfev=10))
        worse = vector.copy()
        worse[0] = 999
        opt._run_model(worse)  # noqa: SLF001
        raise KeyboardInterrupt

    monkeypatch.setattr("cn3s.optim.differential_evolution", de)
    opt.optimize(polish=False, progress=False)
    assert opt.interrupted
    assert opt.result is not None
    assert opt.model.params.r0 == vector[0]
    assert opt.model.params.act == 2
    assert opt.evaluate_best()


def test_refinement_holds_act_and_reports_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refinement reports counts and saves only an accepted result with integral ACT."""
    opt = optimizer()
    vector = np.asarray(opt.model.params.as_list())
    vector[-1] = 3

    def de(**kwargs: Any) -> OptimizeResult:
        assert kwargs["polish"] is False
        return OptimizeResult(
            x=vector.copy(), fun=2.0, success=False, message="budget", nfev=4, nit=1
        )

    def refine(_: Any, x: Any, **kwargs: Any) -> OptimizeResult:
        assert kwargs["bounds"][-1] == (3, 3)
        assert kwargs["options"] == {"maxiter": 2, "maxfun": 20}
        x[0] = 200
        return OptimizeResult(x=x, fun=1.0, success=True, message="ok", nfev=8, nit=2)

    monkeypatch.setattr("cn3s.optim.differential_evolution", de)
    monkeypatch.setattr("cn3s.optim.minimize", refine)
    opt.optimize(polish=True, progress=False, polish_maxiter=2, polish_maxfun=20)
    assert opt.model.params.r0 == 200
    assert opt.model.params.act == 3
    assert opt.diagnostics["polish_nfev"] == 8
    assert opt.diagnostics["nfev"] == 12
    assert opt.diagnostics["polish_accepted"]


def test_refinement_cannot_exceed_hard_evaluation_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """A finite-difference optimizer cannot silently exceed the model-call budget."""
    opt = optimizer()
    vector = np.asarray(opt.model.params.as_list())

    def de(**_: Any) -> OptimizeResult:
        return OptimizeResult(
            x=vector.copy(), fun=2.0, success=False, message="budget", nfev=4, nit=1
        )

    def refine(fun: Any, x: Any, **_: Any) -> OptimizeResult:
        for _ in range(100):
            fun(x)
        msg = "Hard evaluation cap was not enforced"
        raise AssertionError(msg)

    monkeypatch.setattr("cn3s.optim.differential_evolution", de)
    monkeypatch.setattr("cn3s.optim.minimize", refine)
    opt.optimize(polish=True, progress=False, polish_maxiter=2, polish_maxfun=2)
    assert opt.diagnostics["polish_nfev"] == 2
    assert opt.diagnostics["nfev"] == 6
    assert not opt.diagnostics["polish_accepted"]
    assert "Hard evaluation budget" in opt.diagnostics["polish_message"]
