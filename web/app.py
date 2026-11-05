"""SHC application configuration and shared page navigation."""

from __future__ import annotations

import os
import secrets
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from cachelib import FileSystemCache, SimpleCache
from flask import Flask, Response, g, jsonify, redirect, render_template, request, session, url_for
from flask_session import Session

# Keep scientific plotting headless in development as well as in the image.
os.environ.setdefault("MPLBACKEND", "Agg")

from web import login, permanencia


def create_app(config: dict[str, Any] | None = None) -> Flask:
    """
    Build the SHC application with shared authentication and module routes.

    Args:
        config: Optional configuration overrides for local verification.

    Returns:
        Configured Flask application.

    """
    app = Flask(__name__, static_url_path="/shc/static")
    app.config.update(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
        SESSION_TYPE="cachelib",
        SESSION_CACHELIB=FileSystemCache(
            # Restricted cache-file permissions protect tokens; preserve the configured path.
            cache_dir=os.environ.get("SHC_SESSION_DIR", "/tmp/shc-sessions"),  # noqa: S108
            mode=0o600,
        ),
        SESSION_COOKIE_NAME="shc_session",
        SESSION_COOKIE_PATH="/shc",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=os.environ.get("SHC_COOKIE_SECURE", "false").lower() == "true",
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
        SHC_DURATION_CURVES_DIR=Path(
            os.environ.get(
                "SHC_DURATION_CURVES_DIR",
                "/data/CN3S/duration_curves",
            )
        ),
    )
    app.config.update(config or {})
    Session(app)
    app.extensions["shc_sql_cache"] = SimpleCache(threshold=512, default_timeout=0)
    app.extensions["shc_catalog_cache"] = SimpleCache(threshold=1, default_timeout=0)
    app.extensions["shc_station_locks"] = {}
    app.extensions["shc_render_lock"] = Lock()
    app.extensions["shc_run_id"] = secrets.token_urlsafe(16)
    app.register_blueprint(login.bp)
    app.register_blueprint(permanencia.bp)

    @app.before_request
    def check_session() -> Response | tuple[Response | str, int] | None:
        """
        Protect SHC modules and validate all state-changing forms.

        Returns:
            Login redirect or error when access is invalid; otherwise None.

        """
        if request.endpoint == "static":
            response = None
            filename = (request.view_args or {}).get("filename", "")
            if (
                filename == "vendor/plotly-basic-3.1.0.min.js"
                and request.accept_encodings["gzip"] > 0
            ):
                # Precompressed Plotly reduces transfers through IIS and the VPN.
                response = app.send_static_file(filename + ".gz")
                response.mimetype = "text/javascript"
                response.headers["Content-Encoding"] = "gzip"
            return response
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        g.login = login.current_login()
        public = {"login.index", "login.start", "login.status", "login.logout", "static", "entry"}
        if request.endpoint and request.endpoint not in public and g.login["status"] != "signed_in":
            if request.path.startswith("/shc/permanencia/"):
                return jsonify(
                    error="Sua sessão expirou. Entre novamente.", login_required=True
                ), 401
            return redirect(url_for("login.index"))
        if request.method == "POST":
            token = request.headers.get("X-CSRF-Token", request.form.get("csrf_token", ""))
            if not secrets.compare_digest(token, session["csrf_token"]):
                message = "Solicitação inválida. Recarregue a página e tente novamente."
                if request.is_json:
                    return jsonify(error=message), 400
                return render_template("error.html", message=message), 400
        return None

    @app.context_processor
    def shared_context() -> dict[str, Any]:
        """
        Supply identity and form protection to the shared templates.

        Returns:
            Public user identity and the current anti-forgery token.

        """
        return {"user": g.login.get("username"), "csrf_token": session["csrf_token"]}

    @app.after_request
    def response_headers(response: Response) -> Response:
        """
        Prevent caching of private station and login results.

        Args:
            response: Outgoing HTTP response.

        Returns:
            Response with private data excluded from HTTP caches.

        """
        filename = (request.view_args or {}).get("filename", "")
        if request.endpoint == "static" and filename == "vendor/plotly-basic-3.1.0.min.js":
            response.vary.add("Accept-Encoding")
        if request.endpoint == "static" and filename.startswith("vendor/"):
            # Versioned public libraries can be reused across page loads, unlike user data.
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/shc")
    @app.get("/shc/")
    def entry() -> Response:
        """
        Route visitors to sign-in or the authenticated homepage.

        Returns:
            Redirect appropriate to the visitor's current session.

        """
        return redirect(url_for("home" if g.login["status"] == "signed_in" else "login.index"))

    @app.get("/shc/home")
    def home() -> str:
        """
        Display the SHC module menu.

        Returns:
            Authenticated homepage in Brazilian Portuguese.

        """
        return render_template("shc_home.html", active="home")

    return app


app = create_app()
