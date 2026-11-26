"""Microsoft device-code authentication for SHC visitors."""

from __future__ import annotations

import secrets
import time
from threading import Thread
from typing import TYPE_CHECKING, Any

from flask import (
    Blueprint,
    Flask,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from msal import PublicClientApplication, SerializableTokenCache
from werkzeug.exceptions import ServiceUnavailable

if TYPE_CHECKING:
    from werkzeug.wrappers import Response

SQL_SCOPE = "https://database.windows.net/.default"
CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"  # Microsoft Azure CLI public client
AUTHORITY = "https://login.microsoftonline.com/organizations"
LOGIN_TIMEOUT = 600
bp = Blueprint("login", __name__, url_prefix="/shc")


def require_login() -> Response | tuple[Response, int]:
    """
    Remember the requested CN3S page and route an unauthenticated request.

    Returns:
        Login redirect for page navigation or a JSON error for API clients.

    """
    if request.endpoint == "cn3s.index":
        session["return_to"] = url_for(
            "cn3s.index",
            step=(request.view_args or {}).get("step", "estacao"),
            station=request.args.get("station", ""),
        )
        return redirect(url_for("login.index"))
    if request.path.startswith(("/shc/permanencia/", "/shc/cn3s/")):
        return jsonify(error="Sua sessão expirou. Entre novamente.", login_required=True), 401
    return redirect(url_for("login.index"))


def authenticate_user(app: Flask, login_id: str) -> None:
    """
    Wait for one visitor's device login without blocking a browser request.

    Args:
        app: Application owning the server-side cache.
        login_id: Random identifier tied to one visitor's server-side session.

    """
    cache = app.config["SESSION_CACHELIB"]
    key = "device-login:" + login_id

    try:
        tokens = SerializableTokenCache()
        client = PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=tokens)
        flow = client.initiate_device_flow(scopes=[SQL_SCOPE])
        with app.extensions["shc_login_lock"]:
            if cache.get(key) is None:
                return
            cache.set(
                key,
                {
                    "status": "pending",
                    "verification_uri": flow["verification_uri"],
                    "user_code": flow["user_code"],
                    "expires_on": flow["expires_at"],
                },
                timeout=LOGIN_TIMEOUT,
            )
        result = client.acquire_token_by_device_flow(flow)
        account = client.get_accounts()[0]
        state = {
            "status": "signed_in",
            "username": account["username"],
            "access_token": result["access_token"],
            "expires_on": time.time() + int(result["expires_in"]),
            "token_cache": tokens.serialize(),
            "account_id": account["home_account_id"],
        }
    except Exception:
        app.logger.warning("Device-code sign-in did not complete.")
        state = {"status": "failed"}
    with app.extensions["shc_login_lock"]:
        if cache.get(key) is not None:
            cache.set(
                key,
                state,
                timeout=int(app.permanent_session_lifetime.total_seconds())
                if state["status"] == "signed_in"
                else LOGIN_TIMEOUT,
            )


def current_login() -> dict[str, Any]:
    """
    Read the visitor's delegated token, refreshing from their private MSAL cache.

    Returns:
        Server-side login state, with idle expiry extended for authenticated requests.

    """
    login_id = session.get("login_id")
    key = "device-login:" + (login_id or "")
    cache = current_app.config["SESSION_CACHELIB"]
    with current_app.extensions["shc_login_lock"]:
        state: dict[str, Any] | None = cache.get(key)
        if not state:
            return {"status": "signed_out"}
        if state["status"] != "signed_in":
            if state.get("expires_on", time.time() + 1) <= time.time():
                return {"status": "signed_out"}
            return state
        if state["expires_on"] <= time.time() + 60:
            if "token_cache" not in state:
                cache.delete(key)
                return {"status": "signed_out"}
            tokens = SerializableTokenCache()
            tokens.deserialize(state["token_cache"])
            unavailable = "Microsoft temporariamente indisponível."
            try:
                client = PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=tokens)
                account = next(
                    (
                        a
                        for a in client.get_accounts()
                        if a["home_account_id"] == state["account_id"]
                    ),
                    None,
                )
                result = (
                    client.acquire_token_silent_with_error([SQL_SCOPE], account, force_refresh=True)
                    if account
                    else None
                )
            except Exception as exc:
                raise ServiceUnavailable(unavailable) from exc
            if result and result.get("error") in {"temporarily_unavailable", "server_error"}:
                raise ServiceUnavailable(unavailable)
            if not result or "access_token" not in result:
                cache.delete(key)
                return {"status": "signed_out"}
            state.update(
                access_token=result["access_token"],
                expires_on=time.time() + int(result["expires_in"]),
                token_cache=tokens.serialize(),
            )
        cache.set(key, state, timeout=int(current_app.permanent_session_lifetime.total_seconds()))
        return state


@bp.get("/login")
def index() -> str | Response:
    """
    Show device-code instructions or send authenticated visitors home.

    Returns:
        Login HTML or a redirect to the SHC homepage.

    """
    state = g.login
    if state["status"] == "signed_in":
        return redirect(session.pop("return_to", url_for("home")))
    return render_template("login.html", login=state)


@bp.post("/login")
def start() -> Response:
    """
    Start a separate device login for the current visitor.

    Returns:
        Redirect to the login instructions.

    """
    if g.login["status"] in {"starting", "pending", "signed_in"}:
        return redirect(url_for("login.index"))
    destination = session.get("return_to", url_for("home"))
    session.clear()
    session["return_to"] = destination
    session.permanent = True
    session["login_id"] = secrets.token_urlsafe(32)
    session["csrf_token"] = secrets.token_urlsafe(32)
    current_app.session_interface.regenerate(session)  # type: ignore[attr-defined]  # Flask-Session extension
    current_app.config["SESSION_CACHELIB"].set(
        "device-login:" + session["login_id"],
        {"status": "starting"},
        timeout=LOGIN_TIMEOUT,
    )
    Thread(
        target=authenticate_user,
        args=(current_app._get_current_object(), session["login_id"]),  # type: ignore[attr-defined]  # noqa: SLF001 - unwrap thread-local proxy for worker
        daemon=True,
    ).start()
    return redirect(url_for("login.index"))


@bp.get("/login/status")
def status() -> Response:
    """
    Return public login progress without returning access tokens.

    Returns:
        Status JSON belonging only to the current browser session.

    """
    state = g.login
    return jsonify(
        {
            key: value
            for key, value in state.items()
            if key in {"status", "username", "verification_uri", "user_code", "expires_on"}
        }
    )


@bp.post("/logout")
def logout() -> Response:
    """
    Discard only this visitor's device login and SQL token.

    Returns:
        Redirect to the login page.

    """
    login_id = session.get("login_id")
    if login_id:
        with current_app.extensions["shc_login_lock"]:
            current_app.config["SESSION_CACHELIB"].delete("device-login:" + login_id)
    session.clear()
    return redirect(url_for("login.index"))
