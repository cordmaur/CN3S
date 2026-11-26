"""Monthly CN3S preparation, calibration and inference in the SHC workspace."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from threading import Thread
from typing import Any
from zoneinfo import ZoneInfo

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.io as pio
import xarray as xr
from flask import (
    Blueprint,
    Flask,
    Response,
    abort,
    current_app,
    g,
    jsonify,
    render_template,
    request,
    send_file,
    session,
)
from matplotlib.figure import Figure
from mergedownloader.downloader import Downloader
from mergedownloader.file_downloader import DownloadMode, FileDownloader
from mergedownloader.inpeparser import InpeParsers
from shapely.geometry import box

from cn3s import CN3S, CN3SOptimizer, CN3SParams
from cn3s.metrics import compute_nse_from_frame
from cn3s.objectives import ExtremeFlowBlend, NSETopBlend, Objectives
from hydro.inference import Inference
from hydro.rainfall import MODEL_NAMES
from hydro.station import Station, watershed_path
from utils.user_sql_connector import UserSqlConnector

bp = Blueprint("cn3s", __name__, url_prefix="/shc/cn3s")
TTL = 3600
PARAMETERS = tuple(CN3SParams().bounds)
MAX_WARMUP = 24
DEFAULT_ITERATIONS = 20
MAX_ITERATIONS = 1000
BOUND_SIZE = 2
CALIBRATION_RESULTS = {"calibrate", "manual-calibration"}
MAX_CALIBRATION_NAME = 100


def data_root() -> Path:
    """
    Return the configured CN3S root containing stations, forecasts and downloads.

    Returns:
        Configured data root, without creating directories.

    """
    return Path(current_app.config["SHC_CN3S_DATA_DIR"])


def station_folder(code: int) -> Path:
    """
    Return a station folder under the configured root for a numeric ANA code.

    Args:
        code: Historical ANA station code.

    Returns:
        Station path under the configured stations directory.

    """
    return data_root() / "stations" / str(code)


def table(frame: pd.DataFrame, limit: int = 6) -> dict[str, Any]:
    """
    Return the last rows as JSON-safe values, with ISO dates and missing values as null.

    Args:
        frame: Monthly data with timestamp index and physical-unit columns.
        limit: Maximum number of preview rows.

    Returns:
        JSON-compatible table with ISO dates and null missing values.

    """
    result: dict[str, Any] = json.loads(
        frame.tail(limit).to_json(orient="split", date_format="iso")
    )
    return result


def monthly_rain(station: Station) -> pd.Series:
    """
    Read finite, consecutive month-start rainfall in mm without filling missing months.

    Args:
        station: Prepared station owning saved monthly rainfall.

    Returns:
        Consecutive finite precipitation totals in mm/month.

    """
    rain = pd.read_parquet(station.station_dir / "Monthly/rain.parquet")["prec_mm"]
    if (
        rain.empty
        or not rain.index.equals(pd.date_range(rain.index.min(), rain.index.max(), freq="MS"))
        or not np.isfinite(rain.to_numpy(dtype=float)).all()
    ):
        msg = "A chuva deve conter meses consecutivos, no início do mês, sem valores ausentes."
        raise ValueError(msg)
    return rain


def calibrations(folder: Path) -> list[dict[str, Any]]:
    """
    Inspect canonical and legacy artifacts, identifying monthly compatibility explicitly.

    Args:
        folder: Prepared station directory.

    Returns:
        Artifact descriptions, including explicit compatibility flags.

    """
    rows = []
    for directory in (folder / "Monthly/optim", folder / "optim"):
        for path in sorted(directory.glob("*.json")):
            item = {"id": path.relative_to(folder).as_posix(), "compatible": False}
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                metadata = saved["metadata"]
                params = saved["params"]
                if not metadata.get("final_metrics"):
                    final: dict[str, Any] = next(
                        (
                            r
                            for r in saved.get("history", [])
                            if r.get("step") == metadata.get("final_step")
                            and r.get("step") is not None
                        ),
                        {},
                    )
                    metadata["final_metrics"] = {
                        k: final.get(k)
                        for k in ("train_nse", "test_nse", "train_objective", "test_objective")
                    }
                compatible = (
                    metadata.get("frequency") == "M"
                    and metadata.get("act_units") == "calendar_months"
                    and math.isfinite(float(params["area"]))
                    and float(params["area"]) > 0
                )
                changed = any(
                    not (folder / "Monthly" / filename).exists()
                    or (folder / "Monthly" / filename).stat().st_mtime_ns != recorded
                    for filename in ("rain.parquet", "discharge.parquet")
                    if (recorded := metadata.get("input_mtime_ns", {}).get(filename)) is not None
                )
                item.update(
                    metadata=metadata,
                    params=params,
                    compatible=compatible,
                    inputs_changed=changed,
                    has_chart="chart" in saved,
                )
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                item["error"] = f"Arquivo inválido: {exc}"
            rows.append(item)
    return rows


def selected_calibration(folder: Path, identifier: str) -> Path:
    """
    Resolve an explicitly selected compatible artifact from the server-side catalog.

    Args:
        folder: Prepared station directory.
        identifier: Catalog ID relative to the station directory.

    Returns:
        Path of the selected monthly artifact.

    """
    for item in calibrations(folder):
        if item["id"] == identifier and item["compatible"]:
            return folder / identifier
    msg = "Selecione uma calibração mensal válida (ACT em meses)."
    raise ValueError(msg)


def station_summary(code: int) -> dict[str, Any]:
    """
    Read the published station identity and last daily summary without taking the worker lock.

    Args:
        code: Historical station code.

    Returns:
        Station fields, geographic availability and the last completed statistics snapshot.

    """
    folder = station_folder(code)
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    path = folder / "overview.json"
    overview = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    metadata.setdefault("station_name", (overview or {}).get("name") or f"Estação {code}")
    if metadata.get("drainage_area") is None:
        # Legacy metadata can omit the area even when the saved inventory has it.
        area = metadata.get("area_station_km2")
        if area is None:
            area = ((overview or {}).get("inventory") or {}).get("AreaDrenagem")
        metadata["drainage_area"] = area
    metadata.setdefault("drainage_area_geo", metadata.get("area_nuareacont_km2"))
    return {"metadata": metadata, "overview": overview, "basin": watershed_path(folder).exists()}


def station_info(code: int, *, availability: bool = False) -> dict[str, Any]:
    """
    Inspect station metadata and monthly coverage without SQL or rainfall downloads.

    Args:
        availability: Include observed months for checking the requested window.
        code: Historical ANA station code.

    Returns:
        Metadata, coverage, preview rows and calibration choices.

    """
    folder = station_folder(code)
    rows: dict[str, Any] = {}
    for name in ("rain", "discharge"):
        path = folder / "Monthly" / f"{name}.parquet"
        if path.exists():
            frame = pd.read_parquet(path)
            rows[name] = {
                "start": str(frame.index.min().date()) if not frame.empty else None,
                "end": str(frame.index.max().date()) if not frame.empty else None,
                "rows": len(frame),
                "missing": int(frame.isna().sum().sum()),
                "months": pd.DatetimeIndex(frame.dropna().index).strftime("%Y-%m").tolist()
                if availability
                else [],
                "preview": table(frame),
            }
    return {
        **station_summary(code),
        "states_available": Path(current_app.config["SHC_STATES_PATH"]).exists(),
        "series": rows,
        "calibrations": [] if availability else calibrations(folder),
    }


def cycles() -> list[dict[str, Any]]:
    """
    Inspect required CDS files and lead calendars without loading their rainfall grids.

    Returns:
        Cycle readiness and actual month-start lead labels.

    """
    folder = data_root() / "forecasts"
    stamps = {
        match[1]
        for path in folder.glob("*/*.nc2")
        if (match := re.fullmatch(r"[a-z_]+_(\d{6})\.nc2", path.name))
    }
    rows = []
    for stamp in sorted(stamps, reverse=True):
        missing, errors, calendars = [], [], []
        for centre in MODEL_NAMES:
            for variable in ("prec", "hindcast"):
                path = folder / variable / f"{centre}_{stamp}.nc2"
                if not path.exists():
                    missing.append(f"{variable}/{path.name}")
                    continue
                try:
                    with xr.open_dataset(path) as ds:
                        initialization = pd.Timestamp(f"{stamp[:4]}-{stamp[4:]}-01")
                        ends = initialization + pd.to_timedelta(ds.step.values)
                        months = (ends - pd.Timedelta(days=1)).to_period("M").to_timestamp()
                        calendars.append(months.strftime("%Y-%m-%d").tolist())
                        if "tprate" not in ds:
                            errors.append(f"{path.name}: variável tprate ausente")
                except (OSError, ValueError, KeyError, AttributeError) as exc:
                    errors.append(f"{path.name}: {exc}")
        if calendars and any(dates != calendars[0] for dates in calendars):
            errors.append("Os calendários dos modelos/produtos diferem.")
        rows.append(
            {
                "id": stamp,
                "months": calendars[0] if calendars else [],
                "missing": missing,
                "errors": errors,
                "ready": bool(calendars) and not missing and not errors,
            }
        )
    return rows


def progress(job_id: str, phase: str, completed: int = 0) -> None:
    """
    Record an operation phase without exposing credentials or estimating completion.

    Args:
        job_id: Opaque operation identifier tied to the initiating login.
        phase: Human-readable processing phase.
        completed: Completed preparation stages.

    """
    cache = current_app.config["SESSION_CACHELIB"]
    job = cache.get("cn3s:" + job_id)
    if job:
        job["phase"] = phase
        job["completed_steps"] = completed
        cache.set("cn3s:" + job_id, job, timeout=TTL)


def plot_artifact(figure: Any) -> bytes:
    """
    Serialize a Plotly figure with its native encoder, preserving scientific values.

    Args:
        figure: Plotly figure produced by the scientific workflow.

    Returns:
        UTF-8 Plotly JSON bytes.

    """
    figure.update_layout(autosize=True, width=None)
    serialized: str = pio.to_json(figure)
    return serialized.encode()


def fingerprint(path: Path) -> dict[str, Any]:
    """
    Record a file's SHA-256 and size for identifying the actual scientific input.

    Args:
        path: Local input file.

    Returns:
        Content hash and byte count.

    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": digest, "bytes": path.stat().st_size}


def provenance(paths: list[Path]) -> dict[str, Any]:
    """
    Identify inputs and source revision without including tokens or user credentials.

    Args:
        paths: Scientific inputs under the configured CN3S root.

    Returns:
        Input fingerprints, creation time and source identity.

    """
    repo = Path(__file__).resolve().parents[1]
    revision = current_app.config["SHC_CODE_REVISION"]
    dirty: bool | None = None
    git = shutil.which("git")
    if git and (repo / ".git").is_dir():
        revision = subprocess.run(  # noqa: S603 -- resolved Git binary, fixed read-only arguments
            [git, "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(  # noqa: S603 -- resolved Git binary, fixed read-only arguments
                [git, "status", "--porcelain"],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
        )
    sources = [repo / "web/cn3s.py", repo / "web/app.py"]
    sources.extend((repo / "src/cn3s").glob("*.py"))
    sources.extend((repo / "src/hydro").glob("*.py"))
    return {
        "source_sha256": {str(p.relative_to(repo)): fingerprint(p)["sha256"] for p in sources},
        "created_at": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
        "code_revision": revision or "unknown",
        "working_tree_dirty": dirty,
        "inputs": {str(p.relative_to(data_root())): fingerprint(p) for p in paths},
    }


def observation_artifacts(
    inference: Inference, token: str, as_of: pd.Timestamp
) -> dict[str, bytes]:
    """
    Load user-authenticated discharge and render historical comparisons through as_of.

    Args:
        inference: Prepared monthly inference instance.
        token: Delegated Azure SQL token of the initiating user; never persisted in results.
        as_of: Last allowed observation date; not a historical data snapshot.

    Returns:
        Comparison charts and numerical observations/statistics in m³/s.

    """
    conn = UserSqlConnector(token, cache=current_app.extensions["shc_sql_cache"])
    try:
        live = Station.from_folder(inference.station.station_dir, connector=conn)
        live.load_series()
        daily = live.get_series("hidro/telemetria", "vazao")["val"].loc[:as_of]
    finally:
        conn.close()
    if daily.dropna().empty:
        msg = "Não há observações de vazão para a comparação."
        raise ValueError(msg)
    inference.discharge_daily = daily
    artifacts = {
        "monthly.json": plot_artifact(inference.plot_monthly_discharge()),
        "daily.json": plot_artifact(inference.plot_discharge()),
        "observed-discharge.csv": daily.to_csv().encode(),
        "monthly-observations.csv": inference.discharge_monthly.to_csv().encode(),
        "monthly-statistics.csv": inference.discharge_monthly_stats.to_csv().encode(),
    }
    return artifacts


def raw_rainfall_image(inference: Inference) -> bytes:
    """
    Render and close the notebook's raw rainfall figure under the shared plotting lock.

    Args:
        inference: Prepared monthly inference instance.

    Returns:
        PNG image of raw 30-day-equivalent forecasts and monthly observations.

    """
    with current_app.extensions["shc_render_lock"]:
        figure = inference.rainfall.plot_raw_rainfall()
        try:
            image = io.BytesIO()
            figure.savefig(image, format="png", bbox_inches="tight")
            return image.getvalue()
        finally:
            plt.close(figure)


def forecast(code: int, payload: dict[str, Any], token: str, job_id: str) -> dict[str, Any]:
    """
    Run both monthly rainfall scenarios, retaining model results if online SQL fails.

    Args:
        code: Historical ANA station code.
        payload: Submitted monthly configuration; numerical units follow the notebook APIs.
        token: Delegated Azure SQL token of the initiating user; never persisted in results.
        job_id: Opaque operation identifier tied to the initiating login.

    Returns:
        Scenario previews, figures, downloadable numerical data and provenance.

    """
    folder = station_folder(code)
    path = selected_calibration(folder, str(payload.get("calibration", "")))
    cycle = str(payload.get("cycle", ""))
    available = next((c for c in cycles() if c["id"] == cycle and c["ready"]), None)
    if available is None:
        msg = "Ciclo CDS incompleto ou indisponível. Prepare os arquivos no notebook 03."
        raise ValueError(msg)
    as_of = pd.Timestamp(payload["as_of"])
    first = as_of.to_period("M").to_timestamp()
    months = int(payload["months"])
    requested: list[str] = (
        pd.date_range(first, periods=months, freq="MS").strftime("%Y-%m-%d").tolist()
        if months > 0
        else []
    )
    if not requested or not all(month in available["months"] for month in requested):
        msg = "O horizonte solicitado não está disponível neste ciclo."
        raise ValueError(msg)
    station = Station.from_folder(folder)
    rain = monthly_rain(station)
    if first - pd.DateOffset(months=1) not in rain.index:
        msg = "Atualize a chuva salva até o mês anterior à referência antes de executar."
        raise ValueError(msg)
    inference = Inference(station, data_root(), "M", path.relative_to(folder).as_posix())
    progress(job_id, "Preparando chuva observada, climatologia e nove modelos CDS…")
    started = time.monotonic()
    inference.prepare_data(cycle[4:], year=int(cycle[:4]), as_of=str(as_of.date()), months=months)
    rainfall_seconds = time.monotonic() - started
    if not np.isfinite(inference.rainfall.data["forecast"]["basin_corrected"].to_numpy()).all():
        msg = "A chuva corrigida de um dos modelos contém valores não finitos."
        raise ValueError(msg)
    progress(job_id, "Executando os dois cenários CN3S…")
    inference.run_model()
    if not np.isfinite(inference.discharge_scenarios.to_numpy(dtype=float)).all():
        msg = "A simulação produziu vazões não finitas; revise os dados e parâmetros."
        raise ValueError(msg)
    artifacts = {
        "rain.csv": inference.rain_scenarios.to_csv().encode(),
        "discharge.csv": inference.discharge_scenarios.to_csv().encode(),
        "calibration.json": path.read_bytes(),
        "rainfall.json": plot_artifact(inference.rainfall.plot_forecast_rainfall()),
        "anomaly.json": plot_artifact(inference.rainfall.plot_rainfall_anomaly()),
    }
    artifacts["raw-rainfall.png"] = raw_rainfall_image(inference)
    rainfall = inference.rainfall.data
    for key in ("forecast", "observed", "climatology"):
        # Export basin summaries instead of the full regional grids retained for maps.
        names = [name for name in rainfall[key] if name.startswith("basin_")]
        artifacts[f"{key}-rainfall.csv"] = rainfall[key][names].to_dataframe().to_csv().encode()
    progress(job_id, "Consultando vazão com a conta conectada…")
    warnings = []
    try:
        artifacts.update(observation_artifacts(inference, token, as_of))
    except Exception:
        # Numerical forecasts remain usable when only the optional online comparison fails.
        current_app.logger.exception("CN3S observation comparison failed")
        warnings.append(
            "Comparação observada indisponível. Verifique o acesso SQL e os dados da estação."
        )
    source_paths = [
        folder / "metadata.json",
        station.upstream_watershed_path,
        folder / "Monthly/rain.parquet",
        path,
    ]
    source_paths.extend(
        data_root() / "forecasts" / v / f"{m}_{cycle}.nc2"
        for v in ("prec", "hindcast")
        for m in MODEL_NAMES
    )
    record = provenance(source_paths)
    record.update(
        station=code,
        frequency="M",
        calibration=path.relative_to(folder).as_posix(),
        params=asdict(inference.params),
        forecast=rainfall["forecast"].attrs,
        rainfall_seconds=rainfall_seconds,
        elapsed_seconds=time.monotonic() - started,
        warnings=warnings,
        units={"rain": "mm/month", "discharge": "m3/s"},
        note="as_of não congela fontes online. P10-P90 é variabilidade histórica.",
    )
    artifacts["settings.json"] = json.dumps(record, ensure_ascii=False, indent=2).encode()
    return {
        "artifacts": artifacts,
        "warnings": warnings,
        "charts": [
            n
            for n in ("monthly.json", "daily.json", "rainfall.json", "anomaly.json")
            if n in artifacts
        ],
        "rain": table(inference.rain_scenarios, months + inference.params.act),
        "discharge": table(inference.discharge_scenarios, months + inference.params.act),
        "summary": record,
    }


def calibration_inputs(
    station: Station, payload: dict[str, Any]
) -> tuple[pd.DataFrame, CN3SParams]:
    """
    Select the monthly simulation origin and configure the search domain.

    Args:
        station: Station with saved monthly inputs.
        payload: Requested inclusive months, warmup and parameter bounds.

    Returns:
        Rainfall-indexed observations and configured CN3S parameters.

    """
    saved_inputs = station.get_optim_data("M")
    start = pd.Timestamp(payload.get("start", saved_inputs.index.min()))
    end = pd.Timestamp(payload["end"])
    inputs = saved_inputs.loc[start:end]
    if (
        inputs.empty
        or not start.is_month_start
        or not end.is_month_start
        or not inputs.index.equals(pd.date_range(start, end, freq="MS"))
        or not np.isfinite(inputs["prec_mm"]).all()
    ):
        msg = "O intervalo escolhido precisa de chuva contínua, sem meses ausentes."
        raise ValueError(msg)
    # Keep the rainfall origin: r0 and the storage history are calibrated together.
    metadata = station_summary(station.code)["metadata"]
    saved_area = metadata["drainage_area"]
    area = float(saved_area) if saved_area is not None else math.nan
    if not math.isfinite(area) or area <= 0:
        msg = "A área de drenagem do inventário deve ser positiva (km²)."
        raise ValueError(msg)
    params = CN3SParams(name=metadata["station_name"], area=area)
    params.warmup_steps = int(payload.get("warmup_steps", 3))
    if not 1 <= params.warmup_steps <= MAX_WARMUP:
        msg = "Use entre 1 e 24 meses de aquecimento."
        raise ValueError(msg)
    for name, limits in payload.get("bounds", {}).items():
        if name not in PARAMETERS or len(limits) != BOUND_SIZE:
            msg = "Limites de calibração inválidos."
            raise ValueError(msg)
        low, high = map(float, limits)
        if not math.isfinite(low + high) or low < 0 or low >= high:
            msg = f"Limites inválidos para {name}."
            raise ValueError(msg)
        if name == "act" and not (low.is_integer() and high.is_integer()):
            msg = "ACT exige limites inteiros em meses."
            raise ValueError(msg)
        params.bounds[name] = (low, high)
    return inputs, params


def calibration_chart(model: CN3S, rain: pd.Series, cutoff: str | None) -> bytes:
    """
    Plot discharge and rainfall on separate panels with a shared monthly axis.

    Args:
        model: Simulated model, with observations aligned to ACT-adjusted dates.
        rain: Input precipitation in mm/month on its original calendar.
        cutoff: First test month, if archived.

    Returns:
        Serialized Plotly figure.

    """
    figure = model.plot(height=740, q_headroom=1.1, prec_headroom=1.08)
    figure.update_traces(x=rain.index, y=rain, name="Chuva MERGE", selector={"type": "bar"})
    for trace in figure.select_traces(selector={"type": "scatter"}):
        trace.name = "Vazão observada" if trace.name == "Observed discharge" else "Vazão simulada"
    figure.update_layout(
        width=None,
        autosize=True,
        title=None,
        hovermode="x unified",
        xaxis_title="Mês",
        yaxis_title="Vazão (m³/s)",
        yaxis_domain=[0, 0.57],
        yaxis2_title="Chuva (mm/mês)",
        yaxis2_domain=[0.62, 1],
        yaxis2_overlaying=None,
        yaxis2_side="left",
        yaxis2_range=[max(1, float(rain.max()) * 1.08), 0],
        legend={"x": 0, "y": 1.08, "orientation": "h"},
        margin={"l": 76, "r": 18, "t": 60, "b": 52},
    )
    if cutoff and model.results.index.min() <= pd.Timestamp(cutoff) <= model.results.index.max():
        figure.add_shape(
            type="line",
            x0=cutoff,
            x1=cutoff,
            xref="x",
            y0=0,
            y1=1,
            yref="paper",
            line={"dash": "dash", "color": "#647481"},
        )
        figure.add_annotation(
            x=cutoff,
            xref="x",
            y=0.596,
            yref="paper",
            text="Início do teste",
            showarrow=False,
            xanchor="right",
        )
    return plot_artifact(figure)


def calibration_generation(
    job_id: str, generation: int, objective: float, params: dict[str, float], iterations: int
) -> bool:
    """
    Publish a generation for the live chart, retaining samples missed between polls.

    Args:
        job_id: Initiating operation.
        generation: Completed generation number.
        objective: Best training objective in this generation.
        params: Best candidate parameter values.
        iterations: Effective generation limit.

    Returns:
        True when the initiating visitor requested a stop.

    """
    cache = current_app.config["SESSION_CACHELIB"]
    key = "cn3s:" + job_id
    job = cache.get(key)
    if job:
        job.setdefault("generations", []).append(
            [generation, objective if math.isfinite(objective) else None]
        )
        job["best_params"] = params
        job["phase"] = f"Geração {generation} de até {iterations}"
        cache.set(key, job, timeout=TTL)
    return bool(cache.get("cn3s-stop:" + job_id))


def calibrate(code: int, payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    """
    Calibrate saved monthly inputs offline with a bounded, single-worker solver.

    Args:
        code: Historical ANA station code.
        payload: Submitted monthly configuration; numerical units follow the notebook APIs.
        job_id: Opaque operation identifier tied to the initiating login.

    Returns:
        New artifact identity, calibration diagnostics and original monthly inputs.

    """
    station = Station.from_folder(station_folder(code))
    inputs, params = calibration_inputs(station, payload)
    until_convergence = payload.get("until_convergence") is True
    iterations = (
        MAX_ITERATIONS if until_convergence else int(payload.get("maxiter", DEFAULT_ITERATIONS))
    )
    tol = float(payload.get("tol", 1e-4))
    atol = float(payload.get("atol", 0))
    ratio = float(payload.get("train_ratio", 0.9))
    if (
        min(tol, atol) < 0
        or not math.isfinite(tol + atol)
        or ratio not in {i / 100 for i in range(10, 100, 5)}
    ):
        msg = "Confira as tolerâncias e a relação treino/teste em incrementos de 5%."
        raise ValueError(msg)
    if not until_convergence and not 1 <= iterations <= MAX_ITERATIONS:
        msg = f"Informe de 1 a {MAX_ITERATIONS} gerações."
        raise ValueError(msg)
    objectives = {"PlainNSE": Objectives.PlainNSE, "ExtremeFlowBlend": Objectives.ExtremeFlowBlend}
    objective = objectives[str(payload.get("objective", "PlainNSE"))]
    name = str(payload.get("name", "mensal_" + secrets.token_hex(8)))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        msg = "Nome da calibração: use de 1 a 64 letras, números, hífen ou sublinhado."
        raise ValueError(msg)
    destination = station.station_dir / "Monthly/optim" / f"{name}.json"
    optim = CN3SOptimizer(
        inputs["prec_mm"],
        inputs["q_m3s"],
        CN3S(params, freq="M"),
        train_ratio=ratio,
        disjoint_split=True,
        on_generation=lambda generation, value, candidate: calibration_generation(
            job_id, generation, value, candidate, iterations
        ),
        objective=objective,
    )
    progress(job_id, f"Calibrando com um trabalhador; limite de {iterations} iterações…")
    optim.optimize(
        maxiter=iterations,
        tol=tol,
        atol=atol,
        x0=None,
        workers=1,
        popsize=5,
        seed=int(payload.get("seed", 42)),
        disp=False,
        polish=False,
    )
    # Save only after the solver and complete artifact serialization succeed.
    with tempfile.TemporaryDirectory() as temporary:
        saved = Path(temporary) / "calibration.json"
        optim.save(saved)
        artifact = json.loads(saved.read_text())
    paired = optim.model.results.dropna(subset=["obs_q_m3s", "q_m3s"])
    cutoff = pd.Timestamp(artifact["metadata"]["train_cutoff"])
    artifact["metadata"].update(
        until_convergence=until_convergence,
        split_convention="test_starts_at_cutoff",
        input_mtime_ns={
            f: (station.station_dir / "Monthly" / f).stat().st_mtime_ns
            for f in ("rain.parquet", "discharge.parquet")
        },
    )
    for subset, pairs in (
        ("train", paired.loc[paired.index < cutoff]),
        ("test", paired.loc[paired.index >= cutoff]),
    ):
        artifact["metadata"][subset + "_period"] = (
            [str(pairs.index.min().date()), str(pairs.index.max().date())] if len(pairs) else None
        )
        artifact["metadata"][subset + "_pairs"] = len(pairs)
    artifact["metadata"]["input_start"] = str(inputs.index.min().date())
    artifact["metadata"]["input_end"] = str(inputs.index.max().date())
    artifact["metadata"]["provenance"] = provenance(
        [
            station.station_dir / "Monthly/rain.parquet",
            station.station_dir / "Monthly/discharge.parquet",
        ]
    )
    chart = calibration_chart(optim.model, inputs["prec_mm"], artifact["metadata"]["train_cutoff"])
    contents = json.dumps(artifact, ensure_ascii=False, allow_nan=False, indent=2).encode()
    return {
        "artifacts": {
            "calibration.json": contents,
            "calibration-chart.json": chart,
            "calibration-inputs.csv": inputs.to_csv().encode(),
        },
        "charts": ["calibration-chart.json"],
        "summary": artifact["metadata"],
        "calibration": destination.relative_to(station.station_dir).as_posix(),
        "warnings": ["Uma execução limitada não comprova convergência nem habilidade preditiva."],
    }


def original_calibration_inputs(folder: Path, artifact: dict[str, Any]) -> pd.DataFrame:
    """
    Recover exactly the inputs used by a calibration.

    Args:
        folder: Prepared station directory.
        artifact: Saved calibration, with original CSV or input checksums.

    Returns:
        Monthly rainfall and discharge from the original simulation window.

    """
    if "inputs_csv" in artifact:
        return pd.read_csv(
            io.StringIO(artifact["inputs_csv"]),
            index_col=0,
            parse_dates=True,
            float_precision="round_trip",
        )
    metadata = artifact["metadata"]
    recorded = metadata.get("provenance", {}).get("inputs", {})
    files = [folder / "Monthly" / name for name in ("rain.parquet", "discharge.parquet")]
    # Older web results can use local files only after their contents are verified.
    if (
        not metadata.get("input_start")
        or not metadata.get("input_end")
        or any(
            not path.is_file()
            or recorded.get(path.relative_to(data_root()).as_posix(), {}).get("sha256")
            != fingerprint(path)["sha256"]
            for path in files
        )
    ):
        msg = "Os dados mensais originais desta calibração não estão disponíveis."
        raise ValueError(msg)
    rain, discharge = (pd.read_parquet(path) for path in files)
    return rain.join(discharge).loc[metadata["input_start"] : metadata["input_end"]]


def manual_calibration(code: int, payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    """
    Evaluate edited parameters using the archived forcing and chronological split.

    Args:
        code: Historical ANA station code.
        payload: Saved calibration identity and edited parameter values.
        job_id: Initiating operation for progress reporting.

    Returns:
        Private review artifacts and the proposed new calibration identity.

    """
    folder = station_folder(code)
    parent = str(payload.get("calibration", ""))
    path = selected_calibration(folder, parent)
    artifact = json.loads(path.read_text(encoding="utf-8"))
    base = CN3SParams.from_file(path)
    metadata = artifact["metadata"]
    cutoff = metadata.get("train_cutoff")
    if not cutoff:
        msg = "A calibração original não registra o corte de treino e teste."
        raise ValueError(msg)
    updates = payload.get("params")
    if not isinstance(updates, dict) or not updates or not updates.keys() <= set(PARAMETERS):
        msg = "Informe parâmetros válidos para o ajuste manual."
        raise ValueError(msg)
    if any(type(value) not in {int, float} for value in updates.values()):
        msg = "Informe valores numéricos para os parâmetros alterados."
        raise ValueError(msg)
    values = {key: float(value) for key, value in updates.items()}
    if any(not math.isfinite(value) or value < 0 for value in values.values()) or (
        "act" in values and not values["act"].is_integer()
    ):
        msg = "Use parâmetros finitos e não negativos. ACT deve ser um número inteiro de meses."
        raise ValueError(msg)
    if "act" in values:
        values["act"] = int(values["act"])
    changes = {
        key: {"original": getattr(base, key), "adjusted": value}
        for key, value in values.items()
        if value != getattr(base, key)
    }
    if not changes:
        msg = "Altere pelo menos um parâmetro para recalcular."
        raise ValueError(msg)
    inputs = original_calibration_inputs(folder, artifact)
    progress(job_id, "Recalculando gráfico e indicadores…")
    model = CN3S(replace(base, **values), freq="M")
    model.run(inputs["prec_mm"], pbar=False)
    if not np.isfinite(model.results["q_m3s"].to_numpy(dtype=float)).all():
        msg = "O ajuste produziu vazões não finitas. Revise os parâmetros."
        raise ValueError(msg)
    model.results = model.results.join(inputs["q_m3s"].rename("obs_q_m3s"), how="left")
    period_metrics = manual_metrics(model.results, metadata, pd.Timestamp(cutoff))
    original_files = metadata.get("provenance", {}).get("inputs", {})
    result_metadata = {
        **metadata,
        **period_metrics,
        "status": "manual",
        "saved_at": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
        "parent_calibration": parent,
        "parent_name": metadata.get("display_name") or path.stem,
        "parent_metrics": metadata.get("final_metrics", {}),
        "parameter_changes": changes,
        "iterations": None,
        "nfev": None,
        "final_step": None,
        "message": None,
        "solver_settings": None,
        "provenance": {**provenance([]), "inputs": original_files},
    }
    for key in ("display_name", "until_convergence", "optimize_params", "integrality", "bounds"):
        result_metadata.pop(key, None)
    chart = calibration_chart(model, inputs["prec_mm"], cutoff)
    contents = json.dumps(
        {"params": asdict(model.params), "metadata": result_metadata, "history": []},
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return {
        "artifacts": {
            "calibration.json": contents,
            "calibration-chart.json": chart,
            "calibration-inputs.csv": inputs.to_csv().encode(),
        },
        "charts": ["calibration-chart.json"],
        "summary": result_metadata,
        "calibration": f"Monthly/optim/mensal_{secrets.token_hex(8)}.json",
    }


def manual_metrics(
    results: pd.DataFrame, metadata: dict[str, Any], cutoff: pd.Timestamp
) -> dict[str, Any]:
    """
    Evaluate fixed train/test groups with the original objective configuration.

    Args:
        results: Simulated and observed monthly discharge in m³/s.
        metadata: Original objective settings and cutoff convention.
        cutoff: Original chronological split date.

    Returns:
        Objective and NSE per split, effective date ranges and pair counts.

    """
    config = metadata.get("objective", {})
    settings = config.get("settings") or {}
    match config.get("name"):
        case "PlainNSE":
            objective = Objectives.PlainNSE
        case "NSETopBlend":
            objective = NSETopBlend(**settings)
        case "ExtremeFlowBlend" if "reference" not in settings:
            objective = ExtremeFlowBlend(**settings)
        case _:
            msg = "A função objetivo original não pode ser reproduzida para o ajuste manual."
            raise ValueError(msg)

    paired = results[["q_m3s", "obs_q_m3s"]].dropna()
    # Historical optimizer files included the cutoff date in both samples.
    train = (
        paired.loc[paired.index < cutoff]
        if metadata.get("split_convention") == "test_starts_at_cutoff"
        else paired.loc[:cutoff]
    )
    result: dict[str, Any] = {"final_metrics": {}}
    for key, subset in (("train", train), ("test", paired.loc[cutoff:])):
        nse = float(
            compute_nse_from_frame(
                subset,
                observed_col="obs_q_m3s",
                simulated_col="q_m3s",
                on_too_few="neg_inf",
            )
        )
        value = float(objective(subset)) if not subset.empty else math.inf
        result["final_metrics"].update(
            {
                key + "_objective": value if math.isfinite(value) else None,
                key + "_nse": nse if math.isfinite(nse) else None,
            }
        )
        result[key + "_period"] = (
            [str(subset.index.min().date()), str(subset.index.max().date())]
            if len(subset)
            else None
        )
        result[key + "_pairs"] = len(subset)
    return result


def inventory_fields(station: Station) -> dict[str, Any]:
    """
    Read Hidro location labels and serialize the inventory for the station card.

    Args:
        station: Historical station with an authenticated Hidro inventory row.

    Returns:
        Inventory, municipality, UF, river, and observed coordinates in decimal degrees.

    """
    location = station.hidro.read(
        "SELECT m.Nome AS city, e.Sigla AS uf, r.Nome AS river "
        "FROM hidro.estacao AS s "
        "LEFT JOIN hidro.municipio AS m ON m.Codigo = s.MunicipioCodigo "
        "LEFT JOIN hidro.estado AS e ON e.Codigo = s.EstadoCodigo "
        "LEFT JOIN hidro.rio AS r ON r.Codigo = s.RioCodigo "
        "WHERE s.Codigo = :code",
        {"code": station.code},
    ).iloc[0]
    # SQL returns geom_wkb as binary. Use lossless hex in the complete inventory.
    row = station.info.iloc[0].map(
        lambda value: "0x" + bytes(value).hex()
        if isinstance(value, (bytes, bytearray, memoryview))
        else value
    )
    inventory = json.loads(row.to_json(date_format="iso"))
    return {
        "name": station.name,
        "inventory": inventory,
        "latitude": inventory["Latitude"],
        "longitude": inventory["Longitude"],
        **json.loads(location.to_json()),
    }


def prepare_overview(code: int, token: str, kind: str, temporary: str, job_id: str) -> Station:
    """
    Stage station geometry and a snapshot of complete per-source daily statistics.

    Args:
        code: Historical ANA station code.
        token: Initiating user's delegated SQL token, used only for the query.
        kind: Prepare a new station or refresh an existing overview.
        temporary: Staging directory on the station filesystem for atomic publication.
        job_id: Identifier for publishing progress.

    Returns:
        Station with staged files and coordinates in geographic degrees.

    """
    network = Path(current_app.config["SHC_HYDROGRAPHY_DIR"])

    # Manual refresh reads the sources again and seeds the cache for later consumers.
    conn = UserSqlConnector(
        token, cache=current_app.extensions["shc_sql_cache"], use_cache=kind != "overview"
    )
    try:
        progress(job_id, "Consultando inventário…")
        station = Station(code, connector=conn)
        fields = inventory_fields(station)
        if kind == "prepare":
            progress(job_id, "Preparando bacia contribuinte…", 1)
            station.prepare_station(
                network / "geoft_bho_2017_50k_area_drenagem.parquet", output_dir=temporary
            )
        else:
            station.station_dir = Path(temporary) / str(code)
            station.station_dir.mkdir()
        snapshot = station.station_dir / "overview.json"
        if kind == "overview":
            # Publish the inventory before the slower daily queries. Keep the timestamp
            # and values of the last successful series refresh if observations fail.
            destination = station_folder(code) / "overview.json"
            previous = (
                json.loads(destination.read_text(encoding="utf-8")) if destination.exists() else {}
            )
            snapshot.write_text(
                json.dumps(previous | fields, ensure_ascii=False, allow_nan=False), encoding="utf-8"
            )
            snapshot.replace(destination)
        progress(job_id, "Consultando séries de cota e vazão…", 2)
        station.load_series()
        overview = {
            **fields,
            "updated_at": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
            "columns": [list(column) for column in station.stats.columns],
            "index": station.stats.index.tolist(),
            "data": json.loads(station.stats.to_json(orient="values")),
        }
        snapshot.write_text(
            json.dumps(overview, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
    finally:
        conn.close()
    return station


def preserve_outside_window(
    destination: Path, staged: Path, start: pd.Timestamp, end: pd.Timestamp
) -> None:
    """
    Keep previously prepared months outside the requested update.

    Args:
        destination: Published monthly Parquet.
        staged: Newly prepared file awaiting publication.
        start: Inclusive first month.
        end: Inclusive last date.

    """
    new = pd.read_parquet(staged)
    # Keep the requested calendar even when SQL has no discharge near its endpoints.
    # NaN marks a queried month without observations and is excluded from scoring.
    if staged.name == "discharge.parquet":
        calendar = pd.date_range(start, end, freq="MS", name=new.index.name)
        new = new.reindex(calendar)
    if destination.exists():
        old = pd.read_parquet(destination)
        outside = old.loc[(old.index < start) | (old.index > end)]
        new = pd.concat([outside, new]).sort_index()
    new.to_parquet(staged)


def prepare_monthly_inputs(
    code: int,
    payload: dict[str, Any],
    token: str,
    temporary: str,
    job_id: str,
) -> tuple[Station, str]:
    """
    Stage updated monthly inputs and report the active source.

    Args:
        code: Historical ANA station code.
        payload: Source and inclusive month interval.
        token: Delegated SQL token.
        temporary: Same-volume staging directory.
        job_id: Operation identifier for progress.

    Returns:
        Staged station and relative Parquet path.

    """
    folder = station_folder(code)
    station = Station.from_folder(folder)
    station.station_dir = Path(temporary) / str(code)
    start, end = pd.Timestamp(payload["start"]), pd.Timestamp(payload["end"])
    if pd.isna(start) or pd.isna(end) or start > end:
        msg = "Informe um período válido para os dados mensais."
        raise ValueError(msg)
    series = payload["series"]
    if series == "rain":
        progress(job_id, "Baixando e processando chuva MERGE…")
        downloader = Downloader(
            file_downloader=FileDownloader(download_mode=DownloadMode.NO_UPDATE),
            local_folder=str(data_root() / "downloads"),
            parsers=InpeParsers,
        )
        station.download_rain(downloader, freq="M", start=str(start.date()), end=str(end.date()))
    elif series == "discharge":
        progress(job_id, "Consultando e agregando vazão mensal no SQL…")
        # Include the whole last month when averaging the available daily discharge.
        end = end + pd.offsets.MonthEnd(0)
        conn = UserSqlConnector(token, cache=current_app.extensions["shc_sql_cache"])
        try:
            station.download_discharge(conn, freq="M", start=str(start.date()), end=str(end.date()))
        finally:
            conn.close()
    else:
        msg = "Selecione chuva ou vazão."
        raise ValueError(msg)
    name = f"Monthly/{series}.parquet"
    progress(job_id, f"Publicando {name}…")
    preserve_outside_window(folder / name, station.station_dir / name, start, end)
    return station, name


def prepare(
    code: int, payload: dict[str, Any], token: str, kind: str, job_id: str
) -> dict[str, Any]:
    """
    Prepare geometry or monthly series, staging completed files before replacement.

    Args:
        code: Historical ANA station code.
        payload: Submitted monthly configuration; numerical units follow the notebook APIs.
        token: Delegated Azure SQL token of the initiating user; never persisted in results.
        kind: Requested operation or artifact name from the fixed route choices.
        job_id: Identifier for reporting preparation progress.

    Returns:
        Written file names and a reminder to review dependent calibrations.

    """
    folder = station_folder(code)
    if kind == "overview" and not (folder / "metadata.json").exists():
        msg = "Selecione uma estação preparada para atualizar as estatísticas."
        raise ValueError(msg)
    if kind == "prepare" and folder.exists():
        msg = "Esta estação já existe. Selecione-a para visualizar ou atualizar as estatísticas."
        raise ValueError(msg)
    if kind == "inputs" and payload.get("replace") is not True:
        msg = "Confirme na página a substituição dos arquivos indicados."
        raise ValueError(msg)
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder.parent) as temporary:
        if kind in {"prepare", "overview"}:
            station = prepare_overview(code, token, kind, temporary, job_id)
            name = "overview.json"
        else:
            station, name = prepare_monthly_inputs(code, payload, token, temporary, job_id)
        files = [name]
        if kind == "prepare":
            # Publish geometry, metadata and observations in one filesystem operation.
            progress(job_id, "Salvando estação…", 3)
            station.station_dir.rename(folder)
            files.extend(["metadata.json", "upstream_watershed.parquet"])
        else:
            destination = folder / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Both paths share a filesystem, so readers always see a complete snapshot.
            staged = station.station_dir / name
            staged.replace(destination)
    return {
        "summary": {"files": files},
        "artifacts": {},
        "charts": [],
        "warnings": ["Dados atualizados. Revise a compatibilidade das calibrações existentes."]
        if kind == "inputs"
        else [],
    }


def run_operation(
    app: Flask, job_id: str, code: int, token: str, kind: str, payload: dict[str, Any]
) -> None:
    """
    Execute one authorized operation outside HTTP and always release the CN3S lock.

    Args:
        app: Flask application supplying caches, locks and server-side settings.
        job_id: Opaque operation identifier tied to the initiating login.
        code: Historical ANA station code.
        token: Delegated Azure SQL token of the initiating user; never persisted in results.
        kind: Requested operation or artifact name from the fixed route choices.
        payload: Submitted monthly configuration; numerical units follow the notebook APIs.

    """
    with app.app_context():
        cache = app.config["SESSION_CACHELIB"]
        job = cache.get("cn3s:" + job_id)
        try:
            if kind == "forecast":
                result = forecast(code, payload, token, job_id)
            elif kind == "calibrate":
                result = calibrate(code, payload, job_id)
            elif kind == "manual-calibration":
                result = manual_calibration(code, payload, job_id)
            else:
                result = prepare(code, payload, token, kind, job_id)
            job = cache.get("cn3s:" + job_id) or job
            job.update(status="completed", result=result)
        except Exception as exc:
            app.logger.exception("CN3S operation failed: %s", kind)
            message = (
                str(exc)
                if isinstance(exc, (ValueError, FileNotFoundError))
                else (
                    "Não foi possível concluir. Verifique os dados, o acesso SQL "
                    "e o registro do servidor."
                )
            )
            job = cache.get("cn3s:" + job_id) or job
            job.update(status="failed", error=message)
        finally:
            job["elapsed_seconds"] = time.time() - job["started"]
            cache.set("cn3s:" + job_id, job, timeout=TTL)
            app.extensions["cn3s_lock"].release()


@bp.get("", defaults={"step": "estacao"})
@bp.get("/<any(estacao,calibrar,previsao):step>")
def index(step: str) -> str:
    """
    Render one workflow step with a local prepared-station catalog.

    Args:
        step: Station overview, calibration or forecast page.

    Returns:
        Portuguese monthly CN3S page.

    """
    stations = []
    for path in sorted((data_root() / "stations").glob("*/metadata.json")):
        if path.parent.name.isdecimal():
            try:
                code = int(path.parent.name)
                metadata = json.loads(path.read_text(encoding="utf-8"))
                name = (
                    metadata.get("station_name")
                    or station_summary(code)["metadata"]["station_name"]
                )
                stations.append({"code": code, "name": name})
            except (OSError, ValueError, KeyError):
                stations.append({"code": int(path.parent.name), "name": "Metadados inválidos"})
    return render_template(
        "cn3s.html",
        active="cn3s",
        step=step,
        title={"estacao": "Estação", "calibrar": "Calibrar Estação", "previsao": "Previsão"}[step],
        stations=stations,
        models=MODEL_NAMES,
        bounds=CN3SParams().bounds,
        default_iterations=DEFAULT_ITERATIONS,
        max_iterations=MAX_ITERATIONS,
        max_calibration_name=MAX_CALIBRATION_NAME,
        operation=session.get("cn3s_operation", ""),
    )


@bp.get("/stations/<int:code>")
def station_route(code: int) -> Response | tuple[Response, int]:
    """
    Return one station's readiness; avoid reading artifacts during a writer operation.

    Args:
        code: Historical ANA station code.

    Returns:
        Readiness JSON or a clear data/concurrency error.

    """
    view = request.args.get("view")
    if view in {"calibrations", "station"}:
        # Geometry is immutable and overview.json is replaced atomically.
        try:
            summary = station_summary(code)
            if view == "calibrations":
                summary["calibrations"] = calibrations(station_folder(code))
            return jsonify(summary)
        except (OSError, ValueError) as exc:
            return jsonify(error=f"Ficha indisponível: {exc}"), 400
    lock = current_app.extensions["cn3s_lock"]
    if not lock.acquire(blocking=False):
        return jsonify(error="Aguarde a operação CN3S terminar."), 409
    try:
        return jsonify(station_info(code, availability=view == "availability"))
    except (OSError, ValueError, KeyError) as exc:
        return jsonify(error=f"Estação incompleta: {exc}"), 400
    finally:
        lock.release()


@bp.get("/cycles")
def cycles_route() -> Response | tuple[Response, int]:
    """
    List local forecast cycles without overlapping NetCDF reads with an inference thread.

    Returns:
        Cycle JSON or a concurrency error.

    """
    lock = current_app.extensions["cn3s_lock"]
    if not lock.acquire(blocking=False):
        return jsonify(error="Aguarde a operação CN3S terminar."), 409
    try:
        return jsonify(cycles())
    finally:
        lock.release()


def basin_image(code: int, overview: dict[str, Any] | None) -> bytes:
    """
    Draw the saved basin over IBGE boundaries with a national locator.

    Args:
        code: Historical station code.
        overview: Last inventory snapshot with coordinates in decimal degrees.

    Returns:
        PNG in geographic coordinates (EPSG:4326).

    """
    with current_app.extensions["shc_render_lock"]:
        figure = Figure(figsize=(7, 4.4))
        axis = figure.add_axes((0, 0, 1, 1))
        basin = gpd.read_parquet(watershed_path(station_folder(code))).to_crs(4326)
        xmin, ymin, xmax, ymax = basin.total_bounds
        padding = max(xmax - xmin, ymax - ymin) * 0.12
        extent = box(xmin - padding, ymin - padding, xmax + padding, ymax + padding)
        # The bundled generalized IBGE layer also works without a shapefile driver.
        bundled = Path(__file__).parent / "static/br-uf-2022.geojson"
        national = gpd.GeoDataFrame.from_features(
            json.loads(bundled.read_text())["features"], crs=4326
        )
        regional = national
        states_path = Path(current_app.config["SHC_STATES_PATH"])
        if states_path.exists():
            try:
                regional = gpd.read_file(states_path).to_crs(4326)
            except (ImportError, OSError, ValueError):
                current_app.logger.warning("Usando limites estaduais simplificados do IBGE.")
        regional = regional.cx[
            extent.bounds[0] : extent.bounds[2], extent.bounds[1] : extent.bounds[3]
        ]
        if not regional.empty:
            regional.plot(ax=axis, facecolor="#f2f2ea", edgecolor="#adb9b3", linewidth=0.6)
        basin.plot(ax=axis, facecolor="#a4d7d2", edgecolor="#197977", linewidth=1)
        if "SIGLA_UF" in regional:
            for _, state in regional.iterrows():
                part = state.geometry.intersection(extent)
                if part.area > extent.area * 0.04:
                    point = part.representative_point()
                    axis.text(point.x, point.y, str(state["SIGLA_UF"]), color="#576b65", fontsize=8)
        axis.set_xlim(extent.bounds[0], extent.bounds[2])
        axis.set_ylim(extent.bounds[1], extent.bounds[3])
        axis.set_axis_off()
        inset = figure.add_axes((0.025, 0.035, 0.18, 0.31))
        national.plot(ax=inset, facecolor="#dce6e0", edgecolor="#9eafa7", linewidth=0.3)
        inset.set(xticks=[], yticks=[])
        x, y = (overview or {}).get("longitude"), (overview or {}).get("latitude")
        if x is not None and y is not None:
            axis.scatter(float(x), float(y), color="#a84725", edgecolor="white", zorder=5)
            inset.scatter(float(x), float(y), color="#a84725", s=10)
        else:
            # Locate the basin itself until observed station coordinates are available.
            inset.plot(*extent.exterior.xy, color="#197977", linewidth=1)
        image = io.BytesIO()
        figure.savefig(image, format="png")
        return image.getvalue()


@bp.get("/stations/<int:code>/<kind>")
def station_artifact(code: int, kind: str) -> Response:
    """
    Serve a prepared-input CSV or basin image to an authenticated visitor.

    Args:
        code: Historical ANA station code.
        kind: Requested operation or artifact name from the fixed route choices.

    Returns:
        CSV attachment or PNG response.

    """
    if kind not in {"inputs.csv", "basin.png"}:
        abort(404)
    if kind == "inputs.csv":
        lock = current_app.extensions["cn3s_lock"]
        if not lock.acquire(blocking=False):
            abort(409)
        try:
            station = Station.from_folder(station_folder(code))
            contents = station.get_optim_data("M").to_csv().encode()
        finally:
            lock.release()
    else:
        # Existing geometry is never overwritten here, and overview replacement is atomic.
        # Map reads must not reserve the operation lock or prevent station selection.
        overview_path = station_folder(code) / "overview.json"
        overview = (
            json.loads(overview_path.read_text(encoding="utf-8"))
            if overview_path.exists()
            else None
        )
        contents = basin_image(code, overview)
    return send_file(
        io.BytesIO(contents),
        mimetype="image/png" if kind.endswith("png") else "text/csv",
        as_attachment=kind.endswith("csv"),
        download_name=f"{code}-{kind}",
    )


@bp.post("/stations/<int:code>/<kind>")
def start_operation(code: int, kind: str) -> tuple[Response, int]:
    """
    Start a serialized monthly operation using the current user's delegated SQL token.

    Args:
        code: Historical ANA station code.
        kind: Requested operation or artifact name from the fixed route choices.

    Returns:
        Accepted operation ID or input/concurrency error.

    """
    if kind not in CALIBRATION_RESULTS | {"prepare", "overview", "inputs", "forecast"} or code <= 0:
        return jsonify(error="Operação ou estação inválida."), 400
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Configuração inválida."), 400
    lock = current_app.extensions["cn3s_lock"]
    if not lock.acquire(blocking=False):
        return jsonify(error="Uma operação CN3S está em andamento. Aguarde sua conclusão."), 409
    job_id = secrets.token_urlsafe(24)
    cache = current_app.config["SESSION_CACHELIB"]
    job = {
        "owner": session["login_id"],
        "status": "running",
        "code": code,
        "kind": kind,
        "phase": "Preparando operação…",
        "started": time.time(),
        "run_id": current_app.extensions["shc_run_id"],
        "settings": payload,
    }
    try:
        cache.set("cn3s:" + job_id, job, timeout=TTL)
        session["cn3s_operation"] = job_id
        Thread(
            target=run_operation,
            args=(
                current_app._get_current_object(),  # type: ignore[attr-defined]  # noqa: SLF001 -- Flask proxy API
                job_id,
                code,
                g.login["access_token"],
                kind,
                payload,
            ),
            daemon=True,
        ).start()
    except Exception:
        lock.release()
        raise
    return jsonify(operation_id=job_id), 202


def owned_operation(job_id: str) -> dict[str, Any]:
    """
    Find an owner-scoped operation, marking an interrupted worker as failed.

    Args:
        job_id: Opaque operation identifier tied to the initiating login.

    Returns:
        Owner-checked operation state, including interrupted status.

    """
    cache = current_app.config["SESSION_CACHELIB"]
    job: dict[str, Any] | None = cache.get("cn3s:" + job_id)
    if not job or job["owner"] != session.get("login_id"):
        abort(404)
    if job["status"] == "running" and job["run_id"] != current_app.extensions["shc_run_id"]:
        job.update(
            status="failed",
            error="Servidor reiniciado. Execute novamente; não há retomada automática.",
        )
        cache.set("cn3s:" + job_id, job, timeout=TTL)
    return job


@bp.get("/operations/<job_id>")
def operation_status(job_id: str) -> Response:
    """
    Return public operation state without credentials or binary artifacts.

    Args:
        job_id: Opaque operation identifier tied to the initiating login.

    Returns:
        Public JSON with download names, excluding binary contents.

    """
    job = owned_operation(job_id)
    public = {k: v for k, v in job.items() if k not in {"owner", "run_id", "result"}}
    if job["kind"] == "calibrate" and job["status"] == "running":
        public["stop_requested"] = bool(
            current_app.config["SESSION_CACHELIB"].get("cn3s-stop:" + job_id)
        )
    if "result" in job:
        public["result"] = {k: v for k, v in job["result"].items() if k != "artifacts"}
        public["result"]["downloads"] = list(job["result"]["artifacts"])
    return jsonify(public)


@bp.get("/operations/<job_id>/download/<kind>")
def download(job_id: str, kind: str) -> Response:
    """
    Serve a completed artifact only to the initiating authenticated session.

    Args:
        job_id: Opaque operation identifier tied to the initiating login.
        kind: Requested operation or artifact name from the fixed route choices.

    Returns:
        Owner-checked result attachment or inline chart response.

    """
    job = owned_operation(job_id)
    artifacts = job.get("result", {}).get("artifacts", {})
    if kind not in artifacts:
        abort(404)
    types = {".json": "application/json", ".csv": "text/csv", ".png": "image/png"}
    return send_file(
        io.BytesIO(artifacts[kind]),
        mimetype=types[Path(kind).suffix],
        as_attachment=request.args.get("inline") != "1",
        download_name=f"CN3S-{job['code']}-{kind}",
    )


@bp.post("/operations/<job_id>/stop")
def stop_calibration(job_id: str) -> tuple[Response, int]:
    """
    Request a cooperative stop after the current generation.

    Args:
        job_id: Owner-scoped calibration operation.

    Returns:
        Whether the stop was requested while training was still active.

    """
    job = owned_operation(job_id)
    if job["kind"] != "calibrate":
        return jsonify(error="A operação não é um treino de calibração."), 409
    requested = job["status"] == "running"
    if requested:
        # Keep this signal separate so a concurrent worker update cannot overwrite it.
        current_app.config["SESSION_CACHELIB"].set("cn3s-stop:" + job_id, value=True, timeout=TTL)
    return jsonify(stop_requested=requested), 200


@bp.post("/operations/<job_id>/save")
def save_calibration(job_id: str) -> tuple[Response, int]:
    """
    Atomically publish the reviewed result for the initiating session.

    Args:
        job_id: Owner-scoped completed training job.

    Returns:
        Saved calibration identifier or a conflict.

    """
    lock = current_app.extensions["cn3s_lock"]
    if not lock.acquire(blocking=False):
        return jsonify(error="Aguarde a operação CN3S em andamento."), 409
    try:
        job = owned_operation(job_id)
        if job["kind"] not in CALIBRATION_RESULTS or job["status"] != "completed":
            return jsonify(error="Calibração indisponível para salvar."), 409
        result = job["result"]
        identifier = result["calibration"]
        destination = station_folder(job["code"]) / identifier
        if job.get("published") and not destination.exists():
            return jsonify(error="A calibração publicada foi apagada."), 409
        destination.parent.mkdir(parents=True, exist_ok=True)
        artifact = json.loads(result["artifacts"]["calibration.json"])
        payload = request.get_json(silent=True)
        raw_name = payload.get("name") if isinstance(payload, dict) else None
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not 1 <= len(name) <= MAX_CALIBRATION_NAME or not name.isprintable():
            return jsonify(error=f"Informe um nome de 1 a {MAX_CALIBRATION_NAME} caracteres."), 400
        artifact["metadata"]["display_name"] = name
        artifact["inputs_csv"] = result["artifacts"]["calibration-inputs.csv"].decode()
        artifact["chart"] = json.loads(result["artifacts"]["calibration-chart.json"])
        contents = json.dumps(artifact, ensure_ascii=False, allow_nan=False).encode()
        if destination.exists():
            if destination.read_bytes() != contents:
                return jsonify(error="Já existe uma calibração com esse nome."), 409
        else:
            with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
                staged = Path(temporary) / "calibration.json"
                staged.write_bytes(contents)
                destination.hardlink_to(staged)
        cache = current_app.config["SESSION_CACHELIB"]
        job["published"] = True
        cache.set("cn3s:" + job_id, job, timeout=TTL)
        return jsonify(calibration=identifier), 200
    finally:
        lock.release()


@bp.post("/operations/<job_id>/discard")
def discard_calibration(job_id: str) -> tuple[Response, int]:
    """
    Release an unpublished calibration from the current session.

    Args:
        job_id: Owner-scoped training job.

    Returns:
        Discard status.

    """
    lock = current_app.extensions["cn3s_lock"]
    if not lock.acquire(blocking=False):
        return jsonify(error="Aguarde a operação CN3S em andamento."), 409
    try:
        job = owned_operation(job_id)
        if (
            job["kind"] not in CALIBRATION_RESULTS
            or job["status"] != "completed"
            or job.get("published")
        ):
            return jsonify(error="Calibração indisponível para descartar."), 409
        current_app.config["SESSION_CACHELIB"].delete("cn3s:" + job_id)
        return jsonify(discarded=True), 200
    finally:
        lock.release()


@bp.post("/stations/<int:code>/calibrations/delete")
def delete_calibration(code: int) -> tuple[Response, int]:
    """
    Delete one selected calibration from the station's shared catalog.

    Args:
        code: Historical ANA station code.

    Returns:
        Deletion status or a clear conflict.

    """
    lock = current_app.extensions["cn3s_lock"]
    if not lock.acquire(blocking=False):
        return jsonify(error="Aguarde a operação CN3S em andamento."), 409
    try:
        payload = request.get_json(silent=True)
        identifier = str(payload.get("calibration", "")) if isinstance(payload, dict) else ""
        path = selected_calibration(station_folder(code), identifier)
        path.unlink()
        return jsonify(deleted=True), 200
    except (OSError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    finally:
        lock.release()


@bp.get("/stations/<int:code>/calibrations/chart")
def saved_calibration_chart(code: int) -> Response | tuple[Response, int]:
    """
    Return the archived figure or rebuild it using the current monthly files.

    Args:
        code: Historical ANA station code.

    Returns:
        Plotly chart for the selected parameters, or an input error.

    """
    folder = station_folder(code)
    try:
        path = selected_calibration(folder, request.args.get("calibration", ""))
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if "chart" in artifact and request.args.get("refresh") != "1":
            return jsonify(artifact["chart"])
        metadata = artifact["metadata"]
        rain = pd.read_parquet(folder / "Monthly/rain.parquet")["prec_mm"]
        flow = pd.read_parquet(folder / "Monthly/discharge.parquet")["q_m3s"]
        start = pd.Timestamp(metadata.get("input_start") or rain.index.min())
        end = pd.Timestamp(metadata.get("input_end") or rain.index.max())
        rain = rain.loc[start:end]
        if (
            not rain.index.equals(pd.date_range(start, end, freq="MS"))
            or not np.isfinite(rain).all()
        ):
            msg = "A chuva no período da calibração precisa ser contínua."
            return jsonify(error=msg), 400
        model = CN3S(CN3SParams.from_file(path), freq="M")
        model.run(rain, pbar=False)
        # The chart can show simulated discharge even in months with no observations.
        model.results = model.results.join(flow.loc[start:end].rename("obs_q_m3s"), how="left")
        chart = calibration_chart(model, rain, metadata.get("train_cutoff"))
        return current_app.response_class(chart, mimetype="application/json")
    except (OSError, ValueError, KeyError) as exc:
        return jsonify(error=str(exc)), 400
