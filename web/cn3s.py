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
from dataclasses import asdict
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
from cn3s.objectives import Objectives
from hydro.inference import Inference
from hydro.rainfall import MODEL_NAMES
from hydro.station import Station
from hydrography import Hydrography
from utils.user_sql_connector import UserSqlConnector

bp = Blueprint("cn3s", __name__, url_prefix="/shc/cn3s")
TTL = 3600
PARAMETERS = tuple(CN3SParams().bounds)
MAX_WARMUP = 24
MAX_ITERATIONS = 20
BOUND_SIZE = 2


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
                compatible = (
                    metadata.get("frequency") == "M"
                    and metadata.get("act_units") == "calendar_months"
                    and math.isfinite(float(params["area"]))
                    and float(params["area"]) > 0
                )
                item.update(metadata=metadata, params=params, compatible=compatible)
            except (OSError, ValueError, KeyError, TypeError) as exc:
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


def station_info(code: int) -> dict[str, Any]:
    """
    Inspect station metadata and monthly coverage without SQL or rainfall downloads.

    Args:
        code: Historical ANA station code.

    Returns:
        Metadata, coverage, preview rows and calibration choices.

    """
    folder = station_folder(code)
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
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
                "preview": table(frame),
            }
    return {
        "metadata": metadata,
        "overview": json.loads((folder / "overview.json").read_text(encoding="utf-8"))
        if (folder / "overview.json").exists()
        else None,
        "states_available": Path(current_app.config["SHC_STATES_PATH"]).exists(),
        "series": rows,
        "basin": (folder / "upstream_watershed.parquet").exists(),
        "calibrations": calibrations(folder),
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


def progress(job_id: str, phase: str) -> None:
    """
    Record an operation phase without exposing credentials or estimating completion.

    Args:
        job_id: Opaque operation identifier tied to the initiating login.
        phase: Human-readable processing phase.

    """
    cache = current_app.config["SESSION_CACHELIB"]
    job = cache.get("cn3s:" + job_id)
    if job:
        job["phase"] = phase
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
        folder / "upstream_watershed.parquet",
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
    monthly_rain(station)
    inputs = station.get_optim_data("M").loc[: pd.Timestamp(payload["end"])]
    # Keep the rainfall origin: r0 and the storage history are calibrated together.
    params = CN3SParams(name=station.name, area=float(station.metadata["drainage_area"]))
    if not math.isfinite(params.area) or params.area <= 0:
        msg = "A área de drenagem do inventário deve ser positiva (km²)."
        raise ValueError(msg)
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
        params.bounds[name] = (low, high)
    iterations = int(payload.get("maxiter", 5))
    if not 1 <= iterations <= MAX_ITERATIONS:
        msg = "A prova de conceito permite de 1 a 20 iterações."
        raise ValueError(msg)
    objectives = {"PlainNSE": Objectives.PlainNSE, "ExtremeFlowBlend": Objectives.ExtremeFlowBlend}
    objective = objectives[str(payload.get("objective", "PlainNSE"))]
    name = str(payload.get("name", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        msg = "Nome da calibração: use de 1 a 64 letras, números, hífen ou sublinhado."
        raise ValueError(msg)
    destination = station.station_dir / "Monthly/optim" / f"{name}.json"
    if destination.exists():
        msg = "Já existe uma calibração com esse nome. Escolha outro nome."
        raise ValueError(msg)
    optim = CN3SOptimizer(
        inputs["prec_mm"],
        inputs["q_m3s"],
        CN3S(params, freq="M"),
        train_ratio=float(payload.get("train_ratio", 0.9)),
        objective=objective,
    )
    progress(job_id, f"Calibrando com um trabalhador; limite de {iterations} iterações…")
    optim.optimize(
        maxiter=iterations,
        tol=1e-4,
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
    artifact["metadata"]["input_start"] = str(inputs.index.min().date())
    artifact["metadata"]["input_end"] = str(inputs.index.max().date())
    artifact["metadata"]["provenance"] = provenance(
        [
            station.station_dir / "Monthly/rain.parquet",
            station.station_dir / "Monthly/discharge.parquet",
        ]
    )
    figure = optim.plot_step(
        int(artifact["metadata"]["final_step"]), title="Calibração mensal CN3S"
    )
    contents = json.dumps(artifact, ensure_ascii=False, allow_nan=False, indent=2).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also prevents accidental replacement by another local writer.
    with destination.open("xb") as stream:
        stream.write(contents)
    return {
        "artifacts": {
            "calibration.json": contents,
            "calibration-chart.json": plot_artifact(figure),
            "calibration-inputs.csv": inputs.to_csv().encode(),
        },
        "charts": ["calibration-chart.json"],
        "summary": artifact["metadata"],
        "calibration": destination.relative_to(station.station_dir).as_posix(),
        "warnings": ["Uma execução limitada não comprova convergência nem habilidade preditiva."],
    }


def prepare_overview(code: int, token: str, kind: str, temporary: str) -> Station:
    """
    Stage station geometry and a snapshot of complete per-source daily statistics.

    Args:
        code: Historical ANA station code.
        token: Initiating user's delegated SQL token, used only for the query.
        kind: Prepare a new station or refresh an existing overview.
        temporary: Staging directory; caller publishes only after successful queries.

    Returns:
        Station with staged files and coordinates in geographic degrees.

    """
    network = Path(current_app.config["SHC_HYDROGRAPHY_DIR"])

    conn = UserSqlConnector(token, cache=current_app.extensions["shc_sql_cache"])
    try:
        station = Station(code, connector=conn)
        if kind == "prepare":
            hydrography = Hydrography(
                watersheds_path=network / "geoft_bho_2017_5k_area_drenagem.parquet",
                reaches_path=network / "geoft_bho_2017_5k_trecho_drenagem.parquet",
            )
            station.prepare_station(hydrography, output_dir=temporary)
        else:
            station.station_dir = Path(temporary) / str(code)
            station.station_dir.mkdir()
        # Preserve original per-source statistics instead of monthly merged coverage.
        station.load_series()
        inventory = station.info.iloc[0]
        overview = {
            "updated_at": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(),
            "latitude": float(inventory["Latitude"]),
            "longitude": float(inventory["Longitude"]),
            "columns": [list(column) for column in station.stats.columns],
            "index": station.stats.index.tolist(),
            "data": json.loads(station.stats.to_json(orient="values")),
        }
        (station.station_dir / "overview.json").write_text(
            json.dumps(overview, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
    finally:
        conn.close()
    return station


def prepare(code: int, payload: dict[str, Any], token: str, kind: str) -> dict[str, Any]:
    """
    Prepare geometry or monthly series, staging completed files before replacement.

    Args:
        code: Historical ANA station code.
        payload: Submitted monthly configuration; numerical units follow the notebook APIs.
        token: Delegated Azure SQL token of the initiating user; never persisted in results.
        kind: Requested operation or artifact name from the fixed route choices.

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
    with tempfile.TemporaryDirectory() as temporary:
        if kind in {"prepare", "overview"}:
            station = prepare_overview(code, token, kind, temporary)
            files = ["overview.json"]
            if kind == "prepare":
                files += ["metadata.json", "upstream_watershed.parquet"]
        else:
            station = Station.from_folder(folder)
            station.station_dir = Path(temporary) / str(code)
            start, end = pd.Timestamp(payload["start"]), pd.Timestamp(payload["end"])
            if pd.isna(start) or pd.isna(end) or start > end:
                msg = "Informe um período válido para os dados mensais."
                raise ValueError(msg)
            series = payload["series"]
            if series == "rain":
                downloader = Downloader(
                    file_downloader=FileDownloader(download_mode=DownloadMode.NO_UPDATE),
                    local_folder=str(data_root() / "downloads"),
                    parsers=InpeParsers,
                )
                station.download_rain(
                    downloader, freq="M", start=str(start.date()), end=str(end.date())
                )
            elif series == "discharge":
                # Include the whole last month when averaging the available daily discharge.
                end = end + pd.offsets.MonthEnd(0)
                conn = UserSqlConnector(token, cache=current_app.extensions["shc_sql_cache"])
                try:
                    station.download_discharge(
                        conn, freq="M", start=str(start.date()), end=str(end.date())
                    )
                finally:
                    conn.close()
            else:
                msg = "Selecione chuva ou vazão."
                raise ValueError(msg)
            files = [f"Monthly/{series}.parquet"]
        for name in files:
            destination = folder / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            # A same-directory temporary file makes replacement atomic for each artifact.
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as staged:
                staged.write((station.station_dir / name).read_bytes())
            Path(staged.name).replace(destination)
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
            else:
                result = prepare(code, payload, token, kind)
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
                metadata = json.loads(path.read_text(encoding="utf-8"))
                stations.append({"code": int(path.parent.name), "name": metadata["station_name"]})
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
    lock = current_app.extensions["cn3s_lock"]
    if not lock.acquire(blocking=False):
        return jsonify(error="Aguarde a operação CN3S terminar."), 409
    try:
        return jsonify(station_info(code))
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


def basin_image(station: Station, overview: dict[str, Any] | None) -> bytes:
    """
    Render a loaded basin over IBGE states in geographic coordinates (EPSG:4326).

    Args:
        station: Station snapshot containing the saved watershed geometry.
        overview: Saved inventory coordinates in decimal degrees, when available.

    Returns:
        PNG image with state boundaries, abbreviations and the station location.

    """
    with current_app.extensions["shc_render_lock"]:
        figure = Figure(figsize=(7, 5))
        axis = figure.subplots()
        basin = station.upstream_watershed.to_crs(4326)
        xmin, ymin, xmax, ymax = basin.total_bounds
        padding = max(xmax - xmin, ymax - ymin) * 0.15 + 0.2
        states_path = Path(current_app.config["SHC_STATES_PATH"])
        if states_path.exists():
            states = gpd.read_file(states_path).to_crs(4326)
            states = states.cx[xmin - padding : xmax + padding, ymin - padding : ymax + padding]
            states.plot(ax=axis, facecolor="#f5f5f0", edgecolor="#888", linewidth=0.6)
            if "SIGLA_UF" in states:
                for _, state in states.iterrows():
                    point = state.geometry.intersection(
                        box(xmin - padding, ymin - padding, xmax + padding, ymax + padding)
                    ).representative_point()
                    axis.text(point.x, point.y, str(state["SIGLA_UF"]), color="#666", fontsize=8)
        basin.plot(ax=axis, facecolor="#deedf4", edgecolor="#286386", alpha=0.8)
        if overview is not None:
            axis.scatter(
                overview["longitude"],
                overview["latitude"],
                color="#b43f32",
                edgecolor="white",
                zorder=5,
                label="Estação",
            )
            axis.legend(loc="lower left")
        axis.set_xlim(xmin - padding, xmax + padding)
        axis.set_ylim(ymin - padding, ymax + padding)
        axis.set_title(f"{station.name} ({station.code}) — bacia contribuinte")
        axis.set_axis_off()
        image = io.BytesIO()
        figure.savefig(image, format="png", bbox_inches="tight")
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
        station = Station.from_folder(station_folder(code))
        overview_path = station_folder(code) / "overview.json"
        overview = (
            json.loads(overview_path.read_text(encoding="utf-8"))
            if overview_path.exists()
            else None
        )
        contents = basin_image(station, overview)
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
    if kind not in {"prepare", "overview", "inputs", "calibrate", "forecast"} or code <= 0:
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
