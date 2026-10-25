"""Security primitives: password hashing, CSRF, login throttling.

Credentials are never stored in plaintext and never leave the server. The
admin password is kept only as an argon2 hash inside the SQLite database.
"""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from functools import wraps
from typing import Callable, Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import abort, redirect, request, session, url_for

from . import config, db

_hasher = PasswordHasher()


# --------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


# --------------------------------------------------------------------------
# CSRF
# --------------------------------------------------------------------------

def ensure_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf(submitted: Optional[str]) -> bool:
    expected = session.get("csrf_token")
    if not expected or not submitted:
        return False
    return hmac.compare_digest(expected, submitted)


def csrf_protect() -> None:
    """Abort a state-changing request when the CSRF token is missing/invalid."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not validate_csrf(request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")):
            abort(403, description="Invalid or missing CSRF token.")


# --------------------------------------------------------------------------
# login throttling
# --------------------------------------------------------------------------

_lock = threading.Lock()
_attempts: dict[str, list[float]] = {}


def _prune(bucket: list[float], now: float) -> list[float]:
    cutoff = now - config.LOGIN_RATE_WINDOW
    return [t for t in bucket if t > cutoff]


def login_blocked(key: str) -> bool:
    now = time.time()
    with _lock:
        bucket = _prune(_attempts.get(key, []), now)
        _attempts[key] = bucket
        return len(bucket) >= config.LOGIN_RATE_LIMIT


def record_login_failure(key: str) -> None:
    now = time.time()
    with _lock:
        bucket = _prune(_attempts.get(key, []), now)
        bucket.append(now)
        _attempts[key] = bucket


def clear_login_failures(key: str) -> None:
    with _lock:
        _attempts.pop(key, None)


# --------------------------------------------------------------------------
# session / decorators
# --------------------------------------------------------------------------

def current_admin():
    """Return the admin row for the current session, or None."""
    admin_id = session.get("admin_id")
    if not admin_id:
        return None
    return db.get_admin_by_id(admin_id)


def login_admin(admin_id: int) -> None:
    session.clear()
    session["admin_id"] = admin_id
    session.permanent = True
    ensure_csrf_token()


def logout_admin() -> None:
    session.clear()


def admin_required(view: Callable) -> Callable:
    """Backend enforcement for every mutating admin route.

    Interface-level hiding is not enough: each protected view re-checks the
    session against the database before touching any data.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        admin = current_admin()
        if admin is None:
            if request.method == "POST":
                abort(403, description="Administrator authentication required.")
            return redirect(url_for("admin.login", next=request.full_path if request.query_string else request.path))
        return view(*args, **kwargs)

    return wrapped
