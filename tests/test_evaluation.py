"""Artifact integrity, offline evaluation, and independent manual experiments."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from matplotlib.dates import num2date

from cn3s import CN3S, CalibrationEvaluation, CalibrationStore, CN3SParams, ModelPlayground
from cn3s.artifacts import file_hash, write_json
from cn3s.metrics import flow_metrics

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(params=["D", "M"])
def saved_run(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[CalibrationStore, str]:
    """Persist an ACT-aware synthetic run with one missing observation."""
    freq = request.param
    index = pd.date_range("2000-01-01", periods=120, freq="D" if freq == "D" else "MS")
    rain = pd.Series(20 + 15 * np.sin(np.arange(120)), index=index, name="prec")
    params = CN3SParams(area=100, act=2 if freq == "D" else 0)
    model = CN3S(params, freq)
    model.run(rain, pbar=False)
    obs = model.results.q_m3s.astype(float).rename("Vazao") * 1.1
    obs.iloc[20] = np.nan
    modeled = model.results.join(obs.rename("obs_q_m3s"))
    cutoff = str(index[80].date())
    summary: dict[str, Any] = {
        "station_code": "101",
        "frequency": freq,
        "split_date": cutoff,
        "params": asdict(params),
        "input_revision": "original",
        "status": "completed",
        "train_nse": 0.5,
        "test_nse": 0.5,
        "warmup_steps": 3,
    }
    metadata = {"input_revisions": {freq: "original"}}
    store = CalibrationStore(tmp_path)
    station = tmp_path / "stations/101"
    station.mkdir(parents=True)
    pd.DataFrame({"network": ["original"]}).to_parquet(station / "watershed.parquet")
    saved = store.save(
        summary, modeled, pd.DataFrame({"train_objective": [0.7, 0.5]}), rain, obs, metadata
    )
    return store, saved["run_id"]


def load_fixture(saved_run: tuple[CalibrationStore, str]) -> CalibrationEvaluation:
    """Resolve the fixture's frequency without relying on its parameterization name."""
    store, run_id = saved_run
    path = next(store.data_root.glob(f"stations/101/calibration/*/runs/{run_id}/summary.json"))
    return CalibrationEvaluation.from_run(
        store.data_root,
        station_code="101",
        frequency=json.loads(path.read_text())["frequency"],
        run_id=run_id,
    )


def test_runs_coexist_selection_and_integrity(saved_run: tuple[CalibrationStore, str]) -> None:
    """New runs cannot overwrite old ones or move an explicit selection."""
    evaluation = load_fixture(saved_run)
    store, first = saved_run
    store.select("101", evaluation.frequency, first)
    assert evaluation.rain is not None
    assert evaluation.discharge is not None
    args = (
        evaluation.summary,
        evaluation.modeled,
        evaluation.history,
        evaluation.rain,
        evaluation.discharge,
        evaluation.metadata,
    )
    second = store.save(*args)["run_id"]
    assert second != first
    assert store.resolve("101", evaluation.frequency).name == second
    assert store.resolve("101", evaluation.frequency, "selected").name == first
    assert len(store.list_runs("101", evaluation.frequency)) == len((first, second))
    with pytest.raises(FileExistsError):
        store.save(*args, run_id=first)
    with pytest.raises(ValueError, match="Invalid run ID"):
        store.resolve("101", evaluation.frequency, "../escape")
    root = store.resolve("101", evaluation.frequency, first)
    (root / "modeled.parquet").write_bytes(b"damaged")
    with pytest.raises(ValueError, match="checksum"):
        store.load("101", evaluation.frequency, first)


def test_failed_commit_preserves_latest(
    saved_run: tuple[CalibrationStore, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write failure cannot promote a partial bundle."""
    evaluation = load_fixture(saved_run)
    store, original = saved_run

    def fail(*_: Any, **__: Any) -> None:
        msg = "simulated disk failure"
        raise OSError(msg)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail)
    with pytest.raises(OSError, match="disk failure"):
        store.save(
            evaluation.summary,
            evaluation.modeled,
            evaluation.history,
            evaluation.rain,
            evaluation.discharge,
            evaluation.metadata,
        )
    assert store.resolve("101", evaluation.frequency).name == original
    assert not list(store.folder("101", evaluation.frequency).glob(".staging-*"))


def test_snapshot_survives_refresh_and_manual_trials(
    saved_run: tuple[CalibrationStore, str],
) -> None:
    """Changing inputs or playing with parameters never changes the saved reference."""
    evaluation = load_fixture(saved_run)
    store, run_id = saved_run
    folder = store.resolve("101", evaluation.frequency, run_id)
    before = {str(p): file_hash(p) for p in folder.rglob("*") if p.is_file()}
    write_json(
        store.data_root / "stations/101/metadata.json",
        {"input_revisions": {evaluation.frequency: "new-revision"}},
    )
    reloaded = load_fixture(saved_run)
    pd.DataFrame({"network": ["refreshed"]}).to_parquet(
        store.data_root / "stations/101/watershed.parquet",
    )
    player = ModelPlayground(reloaded)
    trial = player.run({"k1": 0.1})
    assert not np.allclose(
        trial.modeled.q_m3s.astype(float), evaluation.modeled.q_m3s.astype(float)
    )
    counts = player.comparison().paired_steps
    assert counts.eq(counts.iloc[0]).all()
    manual_id = player.save("lower recharge")
    manual = CalibrationEvaluation.from_run(
        store.data_root, station_code="101", frequency=evaluation.frequency, run_id=manual_id
    )
    assert manual.summary["kind"] == "manual"
    assert manual.watershed_bytes == evaluation.watershed_bytes
    assert manual.summary["parent_run_id"] == run_id
    assert store.resolve("101", evaluation.frequency).name == run_id
    with pytest.raises(ValueError, match="completed calibration"):
        store.select("101", evaluation.frequency, manual_id)
    assert player.reset() is reloaded
    assert player.trial is None
    assert before == {str(p): file_hash(p) for p in folder.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="not editable"):
        player.run({"area": 500})
    with pytest.raises(ValueError, match="finite"):
        player.run({"k0": float("nan")})
    with pytest.raises(ValueError, match="integer"):
        player.run({"act": 1.5})
    if evaluation.frequency == "M":
        with pytest.raises(ValueError, match="act=0"):
            player.run({"act": 2})


def test_evaluation_plots_rain_and_metrics(saved_run: tuple[CalibrationStore, str]) -> None:
    """Rain stays on forcing dates; missing pairs and figure outputs remain explicit."""
    evaluation = load_fixture(saved_run)
    metrics = evaluation.metrics("train")
    expected = flow_metrics(evaluation.frame("train"), evaluation.frequency)
    assert metrics.loc["CN3S (all pairs)", "NSE"] == pytest.approx(expected["NSE"])
    assert evaluation.coverage().excluded_steps.sum() >= 1
    fig = evaluation.hydrograph()
    rain_axis = fig.axes[1]
    assert rain_axis.yaxis_inverted()
    assert evaluation.rain is not None
    assert len(rain_axis.patches) > 0

    first_bar = rain_axis.patches[0]
    first_date = pd.Timestamp(num2date(first_bar.get_x() + first_bar.get_width() / 2)).tz_localize(
        None
    )
    expected_rain = evaluation.rain.loc[evaluation.frame("all").index.min() :]
    assert first_date == expected_rain.index[0]
    figures = [
        fig,
        evaluation.scatter(),
        evaluation.residuals(),
        evaluation.flow_duration(),
        evaluation.seasonality(),
        evaluation.optimization_history(),
    ]
    for figure in figures:
        figure.canvas.draw()
        plt.close(figure)


def test_constant_empty_and_volume_metrics() -> None:
    """Constant flows are undefined for NSE/KGE; monthly volume uses calendar duration."""
    frame = pd.DataFrame(
        {"obs_q_m3s": [2.0, 2.0], "q_m3s": [2.0, 2.0]},
        index=pd.to_datetime(["2020-02-01", "2020-03-01"]),
    )
    metrics = flow_metrics(frame, "M")
    assert np.isnan(metrics["NSE"])
    assert np.isnan(metrics["KGE"])
    assert "constant" in metrics["undefined_reason"]
    frame["q_m3s"] = [3.0, 2.0]
    assert flow_metrics(frame, "M")["volume_bias_pct"] == pytest.approx(100 * 29 / (2 * 60))
    assert flow_metrics(frame.iloc[:0], "M")["paired_steps"] == 0


def test_legacy_stale_loads_but_cannot_replay(saved_run: tuple[CalibrationStore, str]) -> None:
    """A stale legacy fit remains inspectable without borrowing a newer input revision."""
    evaluation = load_fixture(saved_run)
    store, _ = saved_run
    root = store.folder("101", evaluation.frequency)
    summary = dict(evaluation.summary)
    summary.pop("run_id")
    write_json(root / "summary.json", summary)
    evaluation.modeled.to_parquet(root / "modeled.parquet")
    evaluation.history.to_parquet(root / "history.parquet")
    write_json(
        store.data_root / "stations/101/metadata.json",
        {"input_revisions": {evaluation.frequency: "different"}},
    )
    legacy = CalibrationEvaluation.from_run(
        store.data_root, station_code="101", frequency=evaluation.frequency, run_id="legacy"
    )
    assert legacy.rain is None
    assert not legacy.metrics().empty
    with pytest.raises(ValueError, match="stale legacy"):
        ModelPlayground(legacy).run({})


def test_widget_buttons_run_and_reset(saved_run: tuple[CalibrationStore, str]) -> None:
    """Widget callbacks update a trial only on Run, then restore the reference."""
    player = ModelPlayground(load_fixture(saved_run))
    panel = player.widget()
    assert panel is not None
    player.controls["k1"].value = 0.1
    assert player.trial is None
    panel.children[2].children[1].click()
    assert player.trial is not None
    panel.children[2].children[2].click()
    assert player.trial is None
    assert player.controls["k1"].value == player.parameter_values()["k1"]


def test_common_month_comparison_excludes_incomplete_days(tmp_path: Path) -> None:
    """Cross-frequency scores use only months with complete paired daily coverage."""
    index = pd.date_range("2020-01-01", "2020-03-31", freq="D")
    daily = pd.DataFrame(
        {"q_m3s": 10 + np.arange(len(index)) % 7, "obs_q_m3s": 11 + np.arange(len(index)) % 7},
        index=index,
        dtype=float,
    )
    monthly = daily.resample("MS").mean()
    daily.loc["2020-02-15", "obs_q_m3s"] = np.nan
    common = {"station_code": "101", "split_date": "2019-12-31", "params": asdict(CN3SParams())}
    d = CalibrationEvaluation(
        dict(common, frequency="D", run_id="daily"),
        daily,
        pd.DataFrame(),
        None,
        None,
        {},
        data_root=tmp_path,
    )
    m = CalibrationEvaluation(
        dict(common, frequency="M", run_id="monthly"),
        monthly,
        pd.DataFrame(),
        None,
        None,
        {},
        data_root=tmp_path,
    )
    result = d.compare(m, monthly=True)
    assert result.paired_steps.tolist() == [2, 2]
    assert result.NSE.iloc[0] == pytest.approx(result.NSE.iloc[1])
    with pytest.raises(ValueError, match="monthly=True"):
        d.compare(m)


def test_persistence_requires_previous_calendar_day(tmp_path: Path) -> None:
    """A missing yesterday cannot be replaced by the previous stored row."""
    index = pd.date_range("2020-01-01", periods=10)
    modeled = pd.DataFrame(
        {"q_m3s": np.arange(10) + 1.0, "obs_q_m3s": np.arange(10) + 2.0}, index=index
    )
    observed = modeled.obs_q_m3s.drop(index[7])
    summary = {
        "station_code": "101",
        "frequency": "D",
        "split_date": "2020-01-06",
        "params": asdict(CN3SParams()),
        "run_id": "test",
    }
    e = CalibrationEvaluation(
        summary, modeled, pd.DataFrame(), None, observed, {}, data_root=tmp_path
    )
    scores = e.metrics("test")
    # Missing Jan 8 removes itself and Jan 9 (missing persistence input) from common pairs.
    assert scores.loc["CN3S (all pairs)", "paired_steps"] == len(index[5:]) - 1
    assert scores.loc["one_day_persistence (common pairs)", "paired_steps"] == len(index[5:]) - 2


def test_evaluation_and_trial_do_not_construct_optimizer_or_providers(
    saved_run: tuple[CalibrationStore, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Evaluation and manual replay stay offline and bypass calibration machinery."""

    def forbidden(*_: Any, **__: Any) -> None:
        msg = "Unexpected optimizer or provider construction"
        raise AssertionError(msg)

    monkeypatch.setattr("cn3s.optim.CN3SOptimizer.__init__", forbidden)
    monkeypatch.setattr("cn3s.workflow.MergeRainSource.__init__", forbidden)
    monkeypatch.setattr("cn3s.workflow.HydroDischargeSource.__init__", forbidden)
    reference = load_fixture(saved_run)
    assert not reference.metrics().empty
    assert not ModelPlayground(reference).run({"k2": 0.2}).metrics().empty
