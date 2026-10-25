"""Flask application factory for the Islamic Digital Library."""
from __future__ import annotations

from flask import Flask, render_template, request

from . import config, db


def create_app() -> Flask:
    config.ensure_dirs()

    app = Flask(
        __name__,
        instance_relative_config=False,
        static_folder=str(config.BASE_DIR / "static"),
        template_folder=str(config.BASE_DIR / "templates"),
    )

    app.config.update(
        SECRET_KEY=config.load_secret_key(),
        MAX_CONTENT_LENGTH=config.MAX_REQUEST_BYTES,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.SECURE_COOKIES,
        PERMANENT_SESSION_LIFETIME=config.SESSION_LIFETIME_SECONDS,
        TEMPLATES_AUTO_RELOAD=False,
    )

    db.init_app(app)

    from . import views_admin, views_public

    app.register_blueprint(views_public.bp)
    app.register_blueprint(views_admin.bp)

    # ---- security headers -------------------------------------------------
    @app.after_request
    def set_security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; worker-src 'self' blob:; child-src 'self' blob:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'self'",
        )
        return resp

    # ---- error pages ------------------------------------------------------
    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html", message=getattr(e, "description", "")), 403

    @app.errorhandler(413)
    def too_large(_e):
        return render_template("errors/413.html"), 413

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("errors/500.html"), 500

    return app
