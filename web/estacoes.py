"""Station catalogue and local Hidro and Telemetria observations."""

from __future__ import annotations

import gzip
import json
from contextlib import closing
from datetime import datetime
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
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
    url_for,
)

from hydro.station import Station
from utils.user_sql_connector import UserSqlConnector

bp = Blueprint("estacoes", __name__, url_prefix="/shc/estacoes")
LOCAL = ZoneInfo("America/Sao_Paulo")
MAX_ANA_CODE = 99_999_999
SOURCES = ("Hidro", "Telemetria")
TELEMETRY_SOURCE = "datamart"
SERIES_FILES = (*(f"{source}.parquet" for source in SOURCES), "stats.parquet")
STATION_FILES = (*SERIES_FILES, "metadata.json")


def folder_for(code: int) -> Path:
    """
    Locate the hydrological files of a station.

    Args:
        code: Historical ANA station code.

    Returns:
        Station's Hydrology directory within the catalogue root.

    """
    return Path(current_app.config["SHC_STATIONS_DIR"]) / str(code) / "Hydrology"


def metadata(folder: Path) -> dict[str, Any]:
    """
    Read the station record from Hydrology.

    Args:
        folder: Hydrology directory. Call under the catalogue lock.

    Returns:
        Station name and timestamp, or an empty record for an unregistered station.

    """
    path = folder / "metadata.json"
    if path.is_file():
        return dict(json.loads(path.read_text(encoding="utf-8")))
    return {}


def has_series(folder: Path) -> bool:
    """
    Check that all daily data files for a station are available.

    Args:
        folder: Station's Hydrology directory.

    Returns:
        True when both source files and the corresponding statistics exist.

    """
    return all((folder / name).is_file() for name in SERIES_FILES)


def install(folder: Path, staged: Path) -> None:
    """
    Install a complete set of flat files under the catalogue lock.

    Args:
        folder: Destination Hydrology directory.
        staged: Sibling staging directory, on the same filesystem.

    """
    # Replace files individually on Windows-mounted volumes, which can deny moving
    # the directory itself. Keep metadata last so the date reflects the complete set.
    folder.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=staged.parent) as backup:
        previous = Path(backup)
        for name in STATION_FILES:
            target = folder / name
            if target.exists():
                copyfile(target, previous / name)
        installed = []
        try:
            for name in STATION_FILES:
                (staged / name).replace(folder / name)
                installed.append(name)
        except OSError:
            for name in reversed(installed):
                saved = previous / name
                target = folder / name
                if saved.is_file():
                    saved.replace(target)
                else:
                    target.unlink()
            raise


def save(folder: Path, info: dict[str, Any], daily: pd.DataFrame, stats: pd.DataFrame) -> None:
    """
    Prepare the daily source files and their statistics before replacing the current data.

    Args:
        folder: Destination Hydrology directory.
        info: Station metadata including the update timestamp.
        daily: Daily observations with station code, source, variable and value.
        stats: Per-source statistics with the original measurement and metric columns.

    """
    with TemporaryDirectory(dir=folder.parent) as staging:
        staged = Path(staging) / "Hydrology"
        staged.mkdir()
        is_hidro = daily["source"].eq("Hidro")
        for source, records in zip(SOURCES, (daily[is_hidro], daily[~is_hidro]), strict=True):
            records.to_parquet(staged / f"{source}.parquet")
        stats.to_parquet(staged / "stats.parquet")
        (staged / "metadata.json").write_text(
            json.dumps(info, ensure_ascii=False), encoding="utf-8"
        )
        with current_app.extensions["estacoes"]["lock"]:
            install(folder, staged)


def log_event(status: str, percent: int, message: str) -> tuple[str, int, str]:
    """
    Attach the São Paulo time to a progress message.

    Args:
        status: Current job state.
        percent: Progress through the update stages.
        message: Text displayed in the browser log.

    Returns:
        Status, percentage and timestamped message.

    """
    return status, percent, f"[{datetime.now(LOCAL):%H:%M:%S}] {message}"


def refresh(app: Flask, code: int, token: str) -> None:
    """
    Read full daily histories and record progress at each completed stage.

    Args:
        app: SHC instance owning the station job.
        code: Historical ANA station code.
        token: Requesting user's delegated SQL credential.

    """
    with app.app_context():
        state = app.extensions["estacoes"]
        job = state["jobs"][code]

        def report(percent: int, message: str) -> None:
            """Append a progress event for the in-flight update."""
            job.append(log_event("running", percent, message))

        try:
            with closing(UserSqlConnector(token, use_cache=False)) as connector:
                station = Station(code, connector=connector)
                report(
                    3,
                    f"Estação {station.name} ({code}) localizada. Carregando o histórico.",
                )
                station.load_series(progress=report)
                report(80, "Preparando as séries de cada fonte para gravação.")
                frames = [
                    frame.filter(items=["val", "NivelConsistencia"]).assign(
                        code=series_code, source=station.get_source(series_code), kind=kind
                    )
                    for series_code, kinds in station.series.items()
                    for kind, frame in kinds.items()
                    if not frame.empty
                ]
                if not frames or station.stats is None:
                    job.append(log_event("failed", 80, "A consulta não retornou observações."))
                    return
                report(90, "Gravando Hidro.parquet, Telemetria.parquet e stats.parquet.")
                save(
                    folder_for(code),
                    {
                        "name": station.name,
                        "updated": datetime.now(LOCAL).isoformat(),
                        "telemetry_source": TELEMETRY_SOURCE,
                    },
                    pd.concat(frames),
                    station.stats,
                )
        except Exception:
            app.logger.exception("Falha na atualização hidrológica de %s", code)
            job.append(log_event("failed", job[-1][1], "Falha na atualização. Tente novamente."))
        else:
            job.append(log_event("done", 100, "Observações e estatísticas salvas."))


def job_status(code: int) -> dict[str, Any]:
    """
    Return the current refresh stages for the station.

    Args:
        code: Historical ANA station code.

    Returns:
        Job status, completed stages and messages for the progress dialog.

    """
    events = list(current_app.extensions["estacoes"]["jobs"].get(code, []))
    status, percent = events[-1][:2] if events else ("idle", 0)
    return {"status": status, "progress": percent, "messages": [event[2] for event in events]}


@bp.get("")
def index() -> Response:
    """
    Read the statistics and observations from the same revision.

    Returns:
        Station page with the individual source series and daily update status.

    """
    state = current_app.extensions["estacoes"]
    rows = []
    daily = pd.DataFrame()
    observed = None
    with state["lock"]:
        root = folder_for(0).parent.parent
        catalog = {}
        if root.is_dir():
            for entry in root.iterdir():
                if entry.name.isascii() and entry.name.isdecimal():
                    station_code = int(entry.name)
                    record = metadata(folder_for(station_code))
                    if record:
                        catalog[station_code] = record
        code = request.args.get("station", type=int)
        if code not in catalog:
            code = min(catalog, default=None)
        info = catalog[code] if code is not None else {}
        data = job_status(code) if code is not None else {"status": "idle"}
        updated = datetime.fromisoformat(info["updated"]) if info.get("updated") else None
        available = code is not None and has_series(folder_for(code))
        if available and code is not None:
            folder = folder_for(code)
            columns = ["code", "source", "kind", "val"]
            daily = pd.concat(
                [
                    pd.read_parquet(folder / f"{source}.parquet", columns=columns)
                    for source in SOURCES
                ]
            )
            if not daily.empty:
                observed = daily.index.max()
            stats = pd.read_parquet(folder / "stats.parquet")
            rows = list(stats.itertuples(name=None))
    page = render_template(
        "estacoes.html",
        active="estacoes",
        updated=updated,
        available=available,
        observed=observed,
        rows=rows,
        traces=chart_series(daily) if not daily.empty else [],
        status=data["status"],
        catalog=sorted(catalog.items(), key=lambda item: item[1]["name"].casefold()),
        code=code,
        info=info,
        fresh=(
            available
            and updated
            and updated.date() == datetime.now(LOCAL).date()
            and info.get("telemetry_source") == TELEMETRY_SOURCE
        ),
    )

    response = Response(page, mimetype="text/html")
    if available:
        response.vary.add("Accept-Encoding")
        if request.accept_encodings["gzip"] > 0:
            response.set_data(gzip.compress(response.get_data(), compresslevel=3))
            response.headers["Content-Encoding"] = "gzip"
    return response


def chart_series(daily: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Prepare complete daily series, preserving interruptions in each source.

    Args:
        daily: Observations indexed by date with source, code, variable and value.

    Returns:
        One daily trace per measurement and source series code.

    """
    traces = []
    for (kind, source, series_code), group in daily.groupby(["kind", "source", "code"]):
        series = group["val"].sort_index()
        # Insert one missing point per interruption so Plotly preserves gaps.
        gaps = series.index.to_series().diff() > pd.Timedelta(days=1)
        breaks = series.index[gaps] - pd.Timedelta(days=1)
        series = series.reindex(series.index.union(breaks))
        series = series.where(np.isfinite(series))
        traces.append(
            {
                "kind": kind,
                "name": f"{source} · {series_code}",
                "x": pd.DatetimeIndex(series.index).strftime("%Y-%m-%d").tolist(),
                "y": series.astype(object).where(series.notna(), None).tolist(),
            }
        )
    return traces


@bp.post("/cadastrar")
def register() -> tuple[Response, int]:
    """
    Resolve an ANA code in Hidro and add it to the shared catalogue.

    Returns:
        Station page URL or a validation or connectivity error.

    """
    code = request.form.get("code", type=int)
    if code is None or not 0 < code <= MAX_ANA_CODE:
        return jsonify(error="Informe um código ANA válido."), 400
    folder = folder_for(code)
    state = current_app.extensions["estacoes"]
    with state["lock"]:
        if metadata(folder):
            return jsonify(url=url_for("estacoes.index", station=code)), 200
    try:
        with closing(UserSqlConnector(g.login["access_token"])) as connector:
            station = Station(code, connector=connector)
    except ValueError as exc:
        if str(exc) == f"Station {code} not found in Hidro":
            return jsonify(error="Código ANA não encontrado no Hidro."), 404
        current_app.logger.exception("Falha na consulta ao inventário Hidro")
        return jsonify(error="Não foi possível consultar o inventário Hidro."), 502
    except Exception:
        current_app.logger.exception("Falha na consulta ao inventário Hidro")
        return jsonify(error="Não foi possível consultar o inventário Hidro."), 502
    with state["lock"]:
        if not metadata(folder):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "metadata.json").write_text(
                json.dumps({"name": station.name, "updated": None}, ensure_ascii=False),
                encoding="utf-8",
            )
    return jsonify(url=url_for("estacoes.index", station=code)), 201


@bp.post("/<int:code>/excluir")
def delete(code: int) -> tuple[Response, int]:
    """
    Remove the station from this catalogue and discard its local hydrological files.

    Args:
        code: Historical ANA station code.

    Returns:
        Catalogue URL or a conflict while the station is updating.

    """
    state = current_app.extensions["estacoes"]
    with state["lock"]:
        folder = folder_for(code)
        if not metadata(folder):
            abort(404)
        if job_status(code)["status"] == "running":
            return jsonify(error="Aguarde a atualização antes de excluir a estação."), 409
        for name in STATION_FILES:
            (folder / name).unlink(missing_ok=True)
        if not any(folder.iterdir()):
            folder.rmdir()
        state["jobs"].pop(code, None)
    return jsonify(url=url_for("estacoes.index")), 200


@bp.post("/<int:code>/atualizar")
def start(code: int) -> Response:
    """
    Join or start a shared full-history refresh.

    Args:
        code: Historical ANA station code.

    Returns:
        Current progress for the station.

    """
    state = current_app.extensions["estacoes"]
    with state["lock"]:
        info = metadata(folder_for(code))
        if not info:
            abort(404)
        updated = info.get("updated")
        if (
            updated
            and datetime.fromisoformat(updated).date() == datetime.now(LOCAL).date()
            and info.get("telemetry_source") == TELEMETRY_SOURCE
            and has_series(folder_for(code))
        ):
            return jsonify(status="done", progress=100, messages=["Estação atualizada hoje."])
        if job_status(code)["status"] != "running":
            # Flask types the LocalProxy as Flask. The worker needs the actual application.
            app = current_app._get_current_object()  # type: ignore[attr-defined]  # noqa: SLF001
            state["jobs"][code] = [
                log_event("running", 0, "Consultando a estação no inventário Hidro.")
            ]
            Thread(target=refresh, args=(app, code, g.login["access_token"]), daemon=True).start()
    return jsonify(job_status(code))


@bp.get("/<int:code>/status")
def progress(code: int) -> Response:
    """
    Report the selected station's refresh status.

    Args:
        code: Historical ANA station code.

    Returns:
        Shared refresh status and stage messages.

    """
    return jsonify(job_status(code))
