"""Microsoft device-code authentication for SHC visitors."""

from __future__ import annotations

import secrets
import time
from datetime import datetime
from threading import Thread
from typing import Any

from azure.identity import DeviceCodeCredential
from flask import (
    Blueprint,
    Flask,
    Response,
    current_app,
    jsonify,
    redirect,
    render_template,
    session,
    url_for,
)

SQL_SCOPE = "https://database.windows.net/.default"
LOGIN_TIMEOUT = 600
bp = Blueprint("login", __name__, url_prefix="/shc")


def authenticate_user(app: Flask, login_id: str) -> None:
    """
    Wait for one visitor's device login without blocking a browser request.

    Args:
        app: Application owning the server-side cache.
        login_id: Random identifier tied to one visitor's server-side session.

    """
    cache = app.config["SESSION_CACHELIB"]
    key = "device-login:" + login_id

    def show_code(uri: str, code: str, expires_on: datetime) -> None:
        """
        Publish Microsoft's instructions only to the initiating session.

        Args:
            uri: Microsoft verification address returned by Azure Identity.
            code: User code to enter on Microsoft's page.
            expires_on: UTC expiry returned by Microsoft.

        """
        if cache.get(key) is not None:
            cache.set(
                key,
                {
                    "status": "pending",
                    "verification_uri": uri,
                    "user_code": code,
                    "expires_on": expires_on.timestamp(),
                },
                timeout=LOGIN_TIMEOUT,
            )

    try:
        # Matches the notebook's Azure development client, but has no shared disk cache.
        with DeviceCodeCredential(prompt_callback=show_code, timeout=LOGIN_TIMEOUT) as credential:
            record = credential.authenticate(scopes=[SQL_SCOPE])
            token = credential.get_token(SQL_SCOPE)
        # A signed-out or expired session must not be resurrected by a late completion.
        if cache.get(key) is not None:
            cache.set(
                key,
                {
                    "status": "signed_in",
                    "username": record.username,
                    "access_token": token.token,
                    "expires_on": token.expires_on,
                },
                timeout=max(1, min(3600, int(token.expires_on - time.time()))),
            )
    except Exception:
        app.logger.exception("Device-code sign-in failed")
        if cache.get(key) is not None:
            cache.set(key, {"status": "failed"}, timeout=LOGIN_TIMEOUT)


def current_login() -> dict[str, Any]:
    """
    Read only the current visitor's server-side authentication state.

    Returns:
        Login state; expired or missing sessions are treated as signed out.

    """
    login_id = session.get("login_id")
    state = (
        current_app.config["SESSION_CACHELIB"].get("device-login:" + login_id) if login_id else None
    )
    if not state or state.get("expires_on", time.time() + 1) <= time.time():
        return {"status": "signed_out"}
    return state


@bp.get("/login")
def index() -> str | Response:
    """
    Show device-code instructions or send authenticated visitors home.

    Returns:
        Login HTML or a redirect to the SHC homepage.

    """
    state = current_login()
    if state["status"] == "signed_in":
        return redirect(url_for("home"))
    return render_template("login.html", login=state)


@bp.post("/login")
def start() -> Response:
    """
    Start a separate device login for the current visitor.

    Returns:
        Redirect to the login instructions.

    """
    if current_login()["status"] in {"starting", "pending", "signed_in"}:
        return redirect(url_for("login.index"))
    session.clear()
    session["login_id"] = secrets.token_urlsafe(32)
    session["csrf_token"] = secrets.token_urlsafe(32)
    current_app.session_interface.regenerate(session)
    current_app.config["SESSION_CACHELIB"].set(
        "device-login:" + session["login_id"],
        {"status": "starting"},
        timeout=LOGIN_TIMEOUT,
    )
    Thread(
        target=authenticate_user,
        args=(current_app._get_current_object(), session["login_id"]),
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
    state = current_login()
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
        current_app.config["SESSION_CACHELIB"].delete("device-login:" + login_id)
    session.clear()
    return redirect(url_for("login.index"))
