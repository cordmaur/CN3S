"""Station catalog, shared limits and explicit duration-curve workflows for SHC."""

from __future__ import annotations

import hashlib
import io
import json
import math
import secrets
import shutil
import tempfile
from datetime import date, datetime
from html import escape
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from zoneinfo import ZoneInfo

import matplotlib.dates as mdates
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
    send_file,
    session,
)
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from hydro.duration_curve import LEAP_DAY, DurationCurveReporter
from hydro.station import Station
from utils.user_sql_connector import UserSqlConnector

bp = Blueprint("permanencia", __name__, url_prefix="/shc/permanencia")
TTL = 1800
METRICS = ["Inicio", "Fim", "Anos", "Falhas (%)", "Consist (%)", "Anos (Efet.)"]


def results_root() -> Path:
    """
    Resolve the existing scientific-results directory without creating it.

    Returns:
        Writable mounted results directory.

    Raises:
        ValueError: If the configured data mount is unavailable.

    """
    root = Path(current_app.config["SHC_DURATION_CURVES_DIR"])
    if not root.is_dir():
        msg = "A pasta de curvas não está disponível. Verifique o volume de dados da SHC."
        raise ValueError(msg)
    return root


def metadata(code: int) -> tuple[dict[str, Any], str]:
    """
    Read station metadata and its revision for concurrent-edit detection.

    Args:
        code: Historical station code.

    Returns:
        Metadata and SHA-256 revision of its original bytes.

    """
    raw = (results_root() / str(code) / "meta.json").read_bytes()
    data = json.loads(raw)
    if int(data["station_code"]) != code:
        msg = "O código salvo não corresponde ao diretório da estação."
        raise ValueError(msg)
    # Include scientific files: a recalculation may leave scalar metadata unchanged.
    digest = hashlib.sha256(raw)
    for name in ("curve.parquet", "stats.parquet"):
        status = (results_root() / str(code) / name).stat()
        digest.update(str((status.st_mtime_ns, status.st_size)).encode())
    return data, digest.hexdigest()


def station_catalog() -> list[dict[str, Any]]:
    """
    List saved station identities without querying the database.

    Returns:
        Catalog sorted by station name, including unavailable entries.

    """
    cache = current_app.extensions["shc_catalog_cache"]
    cached = cache.get("stations")
    if cached is not None:
        return cached
    rows = []
    for folder in results_root().iterdir():
        if not folder.is_dir() or not folder.name.isdecimal():
            continue
        code = int(folder.name)
        item = {"code": code, "name": str(code), "available": False, "error": ""}
        try:
            # Catalog identities require only the JSON sidecar. Parquets are checked
            # when opening the station, avoiding repeated filesystem metadata calls.
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
            saved_code = int(meta["station_code"])
            item["name"] = meta["station_name"]
            series_type = meta["series_type"]
        except (OSError, KeyError, json.JSONDecodeError):
            item["error"] = (
                "Os arquivos da estação estão incompletos ou os metadados são inválidos."
            )
        except ValueError as exc:
            item["error"] = str(exc)
        else:
            if saved_code != code:
                item["error"] = "O código salvo não corresponde ao diretório da estação."
            elif series_type != "cota":
                item["error"] = "O resultado salvo não é uma curva de cotas."
            else:
                item["available"] = True
        rows.append(item)
    rows.sort(key=lambda item: (str(item["name"]).casefold(), item["code"]))
    cache.set("stations", rows)
    return rows


def numeric_rows(rows: list[dict[str, Any]], *, corrections: bool = False) -> dict[str, Any]:
    """
    Convert editor rows into limits or dated scientific replacements.

    Args:
        rows: Submitted editor rows.
        corrections: Whether rows specify measurement/date replacements.

    Returns:
        Named limits in cm, or replacements by variable and ISO date.

    Raises:
        ValueError: If rows are incomplete, repeated or non-finite.

    """
    result: dict[str, Any] = {}
    for row in rows:
        try:
            value = float(row["value"])
        except (KeyError, TypeError, ValueError):
            msg = "Informe valores numéricos finitos."
            raise ValueError(msg) from None
        if not math.isfinite(value):
            msg = "Informe valores numéricos finitos."
            raise ValueError(msg) from None
        if corrections:
            variable = row.get("variable")
            day = str(row.get("date", ""))
            try:
                valid_date = date.fromisoformat(day).isoformat() == day
            except ValueError:
                valid_date = False
            if variable not in {"cota", "vazao"} or not valid_date:
                msg = "Informe a variável e uma data válida para cada correção."
                raise ValueError(msg)
            values = result.setdefault(variable, {})
            if day in values:
                msg = "Há mais de uma correção para a mesma variável e data."
                raise ValueError(msg)
            values[day] = value
        else:
            name = str(row.get("name", "")).strip()
            if not name or name in result:
                msg = "Informe nomes não vazios e distintos para os limites."
                raise ValueError(msg)
            result[name] = value
    return result


def stats_rows(station: Station) -> list[dict[str, Any]]:
    """
    Serialize original per-source station statistics for the review table.

    Args:
        station: Station with complete daily observations loaded.

    Returns:
        Rows of historical/telemetric stage and discharge statistics.

    """
    rows = []
    for code, row in station.stats.iterrows():
        values: dict[str, Any] = {"code": int(code), "source": str(row[("Fonte", "")])}
        for kind in ("cota", "vazao"):
            values[kind] = []
            for metric in METRICS:
                value = row[(kind, metric)]
                if pd.isna(value):
                    value = None
                elif hasattr(value, "item"):
                    value = value.item()
                values[kind].append(value)
        rows.append(values)
    return rows


def progress(job_id: str, phase: str) -> None:
    """
    Publish a processing phase without exposing credentials.

    Args:
        job_id: Server-generated operation identifier.
        phase: Human-readable description in Brazilian Portuguese.

    """
    cache = current_app.config["SESSION_CACHELIB"]
    job = cache.get("operation:" + job_id)
    if job:
        job["phase"] = phase
        cache.set("operation:" + job_id, job, timeout=TTL)


def station_image(station: Station, reporter: DurationCurveReporter) -> tuple[bytes, str | None]:
    """
    Draw the notebook's annual chart with local, headless Matplotlib objects.

    Args:
        station: Station with the observations used in this chart.
        reporter: Reporter containing the saved historical references.

    Returns:
        PNG bytes and latest telemetric observation date, if available.

    """
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    telemetry = station.get_series(
        "telemetria", "cota", slice(f"{today.year - 2}-01-01", today.isoformat())
    )
    with current_app.extensions["shc_render_lock"]:
        fig = Figure(figsize=(14, 7))
        ax = fig.subplots()
        reporter.plot_annual_stage_chart(ax, ref_year=today.year, allow_missing_telemetry=True)
        months = (
            "jan",
            "fev",
            "mar",
            "abr",
            "mai",
            "jun",
            "jul",
            "ago",
            "set",
            "out",
            "nov",
            "dez",
        )
        ax.xaxis.set_major_formatter(
            FuncFormatter(lambda x, _: months[mdates.num2date(x).month - 1])
        )
        output = io.BytesIO()
        fig.savefig(output, format="png")
        fig.clear()
    return output.getvalue(), None if telemetry.empty else telemetry.index.max().strftime(
        "%d/%m/%Y"
    )


def station_plotly(station: Station, reporter: DurationCurveReporter) -> dict[str, Any]:
    """
    Build interactive traces from the same references as the annual notebook chart.

    Args:
        station: Station containing the recently loaded telemetry.
        reporter: Saved historical curve and named limits in centimetres.

    Returns:
        JSON-compatible Plotly traces and layout, with missing values as null.

    """
    year = datetime.now(ZoneInfo("America/Sao_Paulo")).year
    result = reporter.results
    stats = result.df.copy()
    months = stats.index.get_level_values("mes")
    days = stats.index.get_level_values("dia")
    # Align by calendar day, excluding leap day exactly as in Matplotlib.
    keep = ~((months == LEAP_DAY[0]) & (days == LEAP_DAY[1]))
    stats = stats.loc[keep]
    dates = [
        f"{year}-{month:02d}-{day:02d}" for month, day in zip(months[keep], days[keep], strict=True)
    ]
    traces = []

    def trace(name: str, x: list[str], values: Any, color: str, **options: Any) -> None:
        """
        Append one line, preserving missing observations as gaps.

        Args:
            name: Legend label, escaped for Plotly's text rendering.
            x: Calendar dates aligned to the reference year.
            values: Stage values in centimetres.
            color: CSS line colour.
            **options: Plotly trace options, including bands and hover details.

        """
        traces.append(
            {
                "type": "scatter",
                "mode": "lines",
                "name": escape(name),
                "x": x,
                "y": [float(value) if pd.notna(value) else None for value in values],
                "line": {"color": color, "width": 1.5},
                "connectgaps": False,
                "hovertemplate": "%{x|%d/%m}: %{y:.2f} cm<extra>%{fullData.name}</extra>",
                **options,
            }
        )

    trace("Mínima histórica", dates, stats["min"], "darkgray")
    trace("Máxima histórica", dates, stats["max"], "gray")
    trace("Permanência 90%", dates, stats["q10"], "lightblue", showlegend=False)
    trace(
        "Permanência 90-10%",
        dates,
        stats["q90"],
        "lightblue",
        fill="tonexty",
        fillcolor="rgba(173,216,230,0.2)",
    )
    trace(
        "MLT",
        dates,
        stats["MLT"],
        "lightblue",
        line={"color": "lightblue", "dash": "dash", "width": 1.5},
    )
    telemetry = station.get_series(
        "telemetria", "cota", slice(f"{year - 2}-01-01", f"{year}-12-31")
    )
    telemetry = telemetry.loc[
        ~((telemetry.index.month == LEAP_DAY[0]) & (telemetry.index.day == LEAP_DAY[1]))
    ]
    for observation_year, color in zip(
        range(year - 2, year + 1), ("#1f77b4", "#ff7f0e", "black"), strict=True
    ):
        annual = telemetry.loc[telemetry.index.year == observation_year]
        if annual.empty:
            continue
        trace(
            str(observation_year),
            [day.replace(year=year).date().isoformat() for day in annual.index],
            annual["val"],
            color,
            customdata=annual.index.strftime("%d/%m/%Y").tolist(),
            hovertemplate="%{customdata}: %{y:.2f} cm<extra>%{fullData.name}</extra>",
        )
    for index, (name, value) in enumerate(result.thresholds.items()):
        color = ("darkgoldenrod", "darkred", "red")[index % 3]
        trace(
            name,
            dates,
            [value] * len(dates),
            color,
            line={"color": color, "dash": "dash", "width": 1},
        )
    return {
        "data": traces,
        "layout": {
            "hovermode": "x unified",
            "dragmode": "zoom",
            "height": 560,
            "margin": {"l": 65, "r": 25, "t": 25, "b": 110},
            "xaxis": {"type": "date", "dtick": "M1", "tickformat": "%b", "hoverformat": "%d/%m"},
            "yaxis": {"title": {"text": "Cota (cm)"}, "fixedrange": False},
            "legend": {"orientation": "h", "y": -0.18, "traceorder": "normal"},
            "paper_bgcolor": "white",
            "plot_bgcolor": "white",
        },
    }


def load_chart(
    code: int, token: str, owner: str, job_id: str, *, refresh: bool = False
) -> dict[str, Any]:
    """
    Reopen historical references and refresh only the years displayed.

    Args:
        code: Saved station code.
        token: Current visitor's delegated SQL token.
        owner: Login identifier owning the generated image.
        job_id: Current operation identifier.
        refresh: Bypass SQL cache for an explicit observation refresh.

    Returns:
        Public chart metadata; image bytes remain in the server cache.

    """
    progress(job_id, "Consultando observações recentes…")
    conn = UserSqlConnector(
        token,
        cache=current_app.extensions["shc_sql_cache"],
        use_cache=not refresh,
    )
    try:
        lock = current_app.extensions["shc_station_locks"].setdefault(code, Lock())
        with lock:
            data, revision = metadata(code)
            station = Station(code, sanitization=data.get("sanitization") or None, connector=conn)
            reporter = DurationCurveReporter.from_saved(results_root() / str(code), station)
        today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        station.load_series(
            source="telemetria",
            series_type="cota",
            start=f"{today.year - 2}-01-01",
            end=today.isoformat(),
        )
        progress(job_id, "Gerando gráfico anual…")
        png, latest = station_image(station, reporter)
        interactive = station_plotly(station, reporter)
    finally:
        conn.close()
    current_app.config["SESSION_CACHELIB"].set(
        "chart:" + job_id,
        {"owner": owner, "png": png, "code": code, "plotly": interactive},
        timeout=TTL,
    )
    # Detect a shared edit made while SQL was loading; never label an old image as new.
    with lock:
        _, now_revision = metadata(code)
    return {
        "code": code,
        "name": data["station_name"],
        "thresholds": data.get("thresholds", {}),
        "description": data["description"],
        "source": data["source"],
        "method": data["method"],
        "requested_method": data.get("requested_method"),
        "revision": revision,
        "latest": latest,
        "chart_id": job_id,
        "warning": "A estação foi alterada por outra pessoa. Atualize a estação."
        if revision != now_revision
        else "",
    }


def analyze(
    code: int, token: str, owner: str, job_id: str, *, editing: bool = False
) -> dict[str, Any]:
    """
    Load original daily records once for statistics and subsequent calculation.

    Args:
        code: Station requested by the visitor.
        token: Visitor's SQL token.
        owner: Owner of the analysis data.
        job_id: Operation/analysis identifier.
        editing: Load saved settings and revision for an existing station.

    Returns:
        Public statistics and an opaque identifier for the cached daily records.

    """
    settings = {}
    revision = None
    if editing:
        lock = current_app.extensions["shc_station_locks"].setdefault(code, Lock())
        with lock:
            settings, revision = metadata(code)
    progress(job_id, "Carregando séries e preparando estatísticas…")
    conn = UserSqlConnector(token, cache=current_app.extensions["shc_sql_cache"])
    try:
        station = Station(code, connector=conn)
        station.load_series()
        current_app.config["SESSION_CACHELIB"].set(
            "analysis:" + job_id,
            {
                "owner": owner,
                "code": code,
                "series": station.series,
                "telemetric_info": station.telemetric_info,
                "stats": station.stats,
                "revision": revision,
                "editing": editing,
            },
            timeout=TTL,
        )
        return {
            "code": code,
            "name": station.name,
            "stats": stats_rows(station),
            "analysis_id": job_id,
            "existing": (results_root() / str(code)).exists(),
            "editing": editing,
            "settings": settings,
        }
    finally:
        conn.close()


def publish_results(
    code: int, reporter: DurationCurveReporter, *, editing: bool, revision: str | None
) -> None:
    """
    Publish complete scientific files while protecting concurrent edits.

    Args:
        code: Station whose files are being published.
        reporter: Reporter containing the newly calculated curve.
        editing: Whether the station already exists and should be replaced.
        revision: Station revision from the original analysis, if editing.

    """
    folder = results_root() / str(code)
    lock = current_app.extensions["shc_station_locks"].setdefault(code, Lock())
    with lock:
        if editing and metadata(code)[1] != revision:
            msg = "A estação foi alterada por outra pessoa. Reabra a edição antes de salvar."
            raise ValueError(msg)
        if editing or not folder.exists():
            # Calculate completely before replacing shared scientific results.
            with tempfile.TemporaryDirectory(prefix=".shc-", dir=results_root()) as staging:
                reporter.save_results(staging)
                prepared = Path(staging) / str(code)
                if editing:
                    names = ("curve.parquet", "stats.parquet", "meta.json")
                    backup = Path(staging) / "previous"
                    backup.mkdir()
                    for name in names:
                        shutil.copy2(folder / name, backup / name)
                        (prepared / name).chmod((folder / name).stat().st_mode & 0o777)
                    try:
                        for name in names:
                            (prepared / name).replace(folder / name)
                    except OSError:
                        # Keep the previous complete curve if a filesystem write fails.
                        for name in names:
                            (backup / name).replace(folder / name)
                        raise
                else:
                    prepared.rename(folder)
            current_app.extensions["shc_catalog_cache"].delete("stations")


def insert(
    code: int, token: str, owner: str, job_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """
    Insert or recalculate a station from its reviewed original daily observations.

    Args:
        code: Station code tied to the analysis.
        token: Current visitor's SQL token.
        owner: Owner of the original analysis.
        job_id: Current operation identifier.
        payload: Analysis ID, editing flag, method, corrections and limits.

    Returns:
        Newly generated or existing chart metadata.

    """
    folder = results_root() / str(code)
    editing = payload.get("editing") is True
    if folder.exists() and not editing:
        return load_chart(code, token, owner, job_id)
    cache = current_app.config["SESSION_CACHELIB"]
    analysis = cache.get("analysis:" + str(payload.get("analysis_id", "")))
    if not analysis or analysis["owner"] != owner or analysis["code"] != code:
        msg = "A análise expirou ou não corresponde à estação. Consulte as estatísticas novamente."
        raise ValueError(msg)
    if analysis.get("editing", False) != editing:
        msg = "Consulte as estatísticas novamente para esta operação."
        raise ValueError(msg)
    method = payload.get("method", "from_discharge")
    if method not in {"from_discharge", "direct"}:
        msg = "Escolha um método de cálculo válido."
        raise ValueError(msg)
    corrections = numeric_rows(payload.get("corrections", []), corrections=True)
    thresholds = numeric_rows(payload.get("thresholds", []))
    conn = UserSqlConnector(token, cache=current_app.extensions["shc_sql_cache"])
    try:
        station = Station(code, sanitization=corrections or None, connector=conn)
        # Reuse parsed daily records, never an SQL engine or another user's connector.
        station.series = analysis["series"]
        station.stats = analysis["stats"]
        station.telemetric_info = analysis["telemetric_info"]
        reporter = DurationCurveReporter(station, thresholds=thresholds)
        # Use the same source as the reporter when checking the correction dates.
        source = reporter._select_best_source("cota")  # noqa: SLF001
        for kind, replacements in corrections.items():
            series = station.get_series(source, kind)
            for day in replacements:
                if pd.Timestamp(day) not in series.index:
                    msg = (
                        f"A correção de {kind} em {day} não corresponde a uma "
                        "observação da série selecionada."
                    )
                    raise ValueError(msg)
        progress(job_id, "Calculando curva histórica…")
        reporter.create_duration_curve(series_type="cota", source=source, method=method)
        progress(job_id, "Salvando resultados…")
        publish_results(code, reporter, editing=editing, revision=analysis["revision"])
    finally:
        conn.close()
    cache.delete("analysis:" + str(payload.get("analysis_id", "")))
    try:
        return load_chart(code, token, owner, job_id)
    except Exception:
        current_app.logger.exception("Station saved but chart refresh failed for %s", code)
        return {
            "saved_only": True,
            "code": code,
            "warning": (
                "Estação salva. Não foi possível atualizar o gráfico. "
                "Selecione a estação novamente para gerar o gráfico."
            ),
        }


def save_limits(
    code: int, token: str, owner: str, job_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """
    Update shared limits atomically and then refresh the displayed chart.

    Args:
        code: Station to update.
        token: Current visitor's SQL token.
        owner: Owner of the regenerated image.
        job_id: Current operation identifier.
        payload: New limits and revision originally presented to the visitor.

    Returns:
        Refreshed chart, or a distinct saved-but-not-rendered outcome.

    """
    thresholds = numeric_rows(payload.get("thresholds", []))
    lock = current_app.extensions["shc_station_locks"].setdefault(code, Lock())
    progress(job_id, "Salvando limites compartilhados…")
    with lock:
        data, revision = metadata(code)
        if payload.get("revision") != revision:
            msg = "Os limites foram alterados por outra pessoa. Atualize a estação antes de salvar."
            raise ValueError(msg)
        data["thresholds"] = thresholds
        folder = results_root() / str(code)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=folder, delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
            # Preserve shared-data permissions when replacing a restrictive temp file.
            temporary.chmod((folder / "meta.json").stat().st_mode & 0o777)
            temporary.replace(folder / "meta.json")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    try:
        return load_chart(code, token, owner, job_id)
    except Exception:
        current_app.logger.exception("Limits saved but chart refresh failed for %s", code)
        return {
            "saved_only": True,
            "code": code,
            "warning": (
                "Limites salvos. Não foi possível atualizar o gráfico. "
                "Selecione a estação novamente para gerar o gráfico."
            ),
        }


def run_operation(
    app: Flask, job_id: str, owner: str, token: str, kind: str, code: int, payload: dict[str, Any]
) -> None:
    """
    Execute one station operation outside the HTTP request context.

    Args:
        app: Application owning the operation cache and locks.
        job_id: Random operation identifier.
        owner: Initiating login identifier.
        token: Delegated SQL token, never returned in the operation response.
        kind: Analyze, insert/recalculate, refresh or limits.
        code: Historical station code.
        payload: Submitted scientific settings.

    """
    with app.app_context():
        cache = app.config["SESSION_CACHELIB"]
        try:
            if kind == "analyze":
                result = analyze(code, token, owner, job_id, editing=payload.get("editing") is True)
            elif kind == "insert":
                result = insert(code, token, owner, job_id, payload)
            elif kind == "limits":
                result = save_limits(code, token, owner, job_id, payload)
            else:
                result = load_chart(
                    code,
                    token,
                    owner,
                    job_id,
                    refresh=payload.get("refresh") is True,
                )
            job = {"owner": owner, "status": "done", "result": result}
        except Exception as exc:
            app.logger.exception("SHC operation %s failed for %s", kind, code)
            message = (
                "Não foi possível concluir a operação. "
                "Verifique suas permissões e os registros do servidor."
            )
            if isinstance(exc, ValueError):
                message = str(exc)
                if message.startswith(("No data", "No usable")):
                    message = "A estação não possui observações utilizáveis para esse cálculo."
                elif "not found in Hidro" in message:
                    message = (
                        "Estação não encontrada no inventário Hidro. Verifique o código informado."
                    )
                elif message.startswith("Rating-curve conversion failed"):
                    message = (
                        "A conversão pela curva-chave falhou e não há cotas para o método direto."
                    )
            if isinstance(exc, (FileNotFoundError, json.JSONDecodeError)):
                message = "Os arquivos da estação estão incompletos ou os metadados são inválidos."
            job = {"owner": owner, "status": "failed", "error": message}
        job["run_id"] = app.extensions["shc_run_id"]
        cache.set("operation:" + job_id, job, timeout=TTL)


def start_operation(kind: str, code: int | None = None) -> tuple[Response, int]:
    """
    Start one operation per browser session and return promptly.

    Args:
        kind: Requested station operation.
        code: Route station code, or None to read the submitted code.

    Returns:
        Accepted operation ID or an input/concurrency error.

    """
    payload = request.get_json(silent=True) or {}
    try:
        code = code if code is not None else int(payload.get("code", 0))
        if code <= 0:
            return jsonify(error="Informe um código de estação válido."), 400
        results_root()
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc) or "Informe um código de estação válido."), 400
    cache = current_app.config["SESSION_CACHELIB"]
    owner = session["login_id"]
    active = session.get("active_operation")
    previous = cache.get("operation:" + active) if active else None
    if (
        previous
        and previous["status"] == "running"
        and previous.get("run_id") == current_app.extensions["shc_run_id"]
    ):
        return jsonify(error="Aguarde a operação atual terminar."), 409
    job_id = secrets.token_urlsafe(24)
    cache.set(
        "operation:" + job_id,
        {
            "owner": owner,
            "status": "running",
            "phase": "Preparando consulta…",
            "run_id": current_app.extensions["shc_run_id"],
        },
        timeout=TTL,
    )
    session["active_operation"] = job_id
    Thread(
        target=run_operation,
        args=(
            # Flask documents this API for passing the real application to a thread.
            current_app._get_current_object(),  # noqa: SLF001
            job_id,
            owner,
            g.login["access_token"],
            kind,
            code,
            payload,
        ),
        daemon=True,
    ).start()
    return jsonify(operation_id=job_id), 202


@bp.get("")
def index() -> str:
    """
    Display the station workspace without eagerly loading SQL observations.

    Returns:
        Curves page containing local catalog entries.

    """
    try:
        return render_template(
            "permanencia.html", active="permanencia", stations=station_catalog(), catalog_error=""
        )
    except ValueError as exc:
        return render_template(
            "permanencia.html", active="permanencia", stations=[], catalog_error=str(exc)
        )


@bp.post("/estacoes/analisar")
def analyze_route() -> tuple[Response, int]:
    """
    Start the original-series statistics query.

    Returns:
        Accepted analysis operation or an error response.

    """
    return start_operation("analyze")


@bp.post("/estacoes")
def insert_route() -> tuple[Response, int]:
    """
    Start a reviewed station calculation.

    Returns:
        Accepted insertion operation or an error response.

    """
    return start_operation("insert")


@bp.post("/estacoes/<int:code>/atualizar")
def refresh_route(code: int) -> tuple[Response, int]:
    """
    Refresh an existing station's observations and image.

    Args:
        code: Historical station code.

    Returns:
        Accepted refresh operation or an error response.

    """
    return start_operation("refresh", code)


@bp.post("/estacoes/<int:code>/limites")
def limits_route(code: int) -> tuple[Response, int]:
    """
    Save shared thresholds with stale-edit detection.

    Args:
        code: Historical station code.

    Returns:
        Accepted save operation or an error response.

    """
    return start_operation("limits", code)


@bp.get("/operacoes/<job_id>")
def operation_status(job_id: str) -> Response:
    """
    Return progress only to the session that started an operation.

    Args:
        job_id: Operation identifier.

    Returns:
        Public status/result JSON without credentials or cached daily records.

    """
    job = current_app.config["SESSION_CACHELIB"].get("operation:" + job_id)
    if not job or job["owner"] != session.get("login_id"):
        return jsonify(error="Operação indisponível ou expirada."), 404
    if job["status"] == "running" and job.get("run_id") != current_app.extensions["shc_run_id"]:
        job.update(
            status="failed", error="O servidor foi reiniciado durante a operação. Tente novamente."
        )
        current_app.config["SESSION_CACHELIB"].set("operation:" + job_id, job, timeout=TTL)
    return jsonify({key: value for key, value in job.items() if key not in {"owner", "run_id"}})


@bp.get("/graficos/<chart_id>.png")
def chart(chart_id: str) -> Response:
    """
    Serve a private chart without exposing scientific directories.

    Args:
        chart_id: Completed operation/image identifier.

    Returns:
        PNG image, optionally downloaded with a station-specific filename.

    """
    item = current_app.config["SESSION_CACHELIB"].get("chart:" + chart_id)
    if not item or item["owner"] != session.get("login_id"):
        abort(404)
    return send_file(
        io.BytesIO(item["png"]),
        mimetype="image/png",
        as_attachment=request.args.get("download") == "1",
        download_name=f"SHC_cotas_{item['code']}.png",
        max_age=0,
    )


@bp.get("/graficos/<chart_id>.json")
def interactive_chart(chart_id: str) -> Response:
    """
    Serve interactive chart data only to its authenticated owner.

    Args:
        chart_id: Completed chart identifier.

    Returns:
        Plotly traces and layout, without credentials or original daily records.

    """
    item = current_app.config["SESSION_CACHELIB"].get("chart:" + chart_id)
    if not item or item["owner"] != session.get("login_id"):
        abort(404)
    return jsonify(item["plotly"])
