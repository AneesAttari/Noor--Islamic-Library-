"""Application configuration and filesystem layout.

All runtime state lives under the project directory (or paths overridden by
environment variables) so backups are a simple directory copy:

  data/          -> SQLite database + server secret key
  storage/       -> uploaded PDF files and cover images
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("IDL_DATA_DIR", BASE_DIR / "data")).resolve()
STORAGE_DIR = Path(os.environ.get("IDL_STORAGE_DIR", BASE_DIR / "storage")).resolve()
PDF_DIR = STORAGE_DIR / "pdfs"
COVER_DIR = STORAGE_DIR / "covers"
DB_PATH = Path(os.environ.get("IDL_DB_PATH", DATA_DIR / "library.db")).resolve()
SECRET_KEY_FILE = DATA_DIR / "secret_key"

APP_NAME = "Maktaba"
APP_TAGLINE = "Islamic Digital Library"

# Upload limits
MAX_PDF_BYTES = 100 * 1024 * 1024        # 100 MB
MAX_COVER_BYTES = 8 * 1024 * 1024        # 8 MB
MAX_REQUEST_BYTES = MAX_PDF_BYTES + 1 * 1024 * 1024

# Session / cookie
SESSION_LIFETIME_SECONDS = 12 * 60 * 60  # 12 hours for admin sessions
SECURE_COOKIES = os.environ.get("IDL_SECURE_COOKIES", "").lower() in ("1", "true", "yes")

# Login throttling: max failed attempts per key inside the window
LOGIN_RATE_LIMIT = 10
LOGIN_RATE_WINDOW = 15 * 60  # seconds


def ensure_dirs() -> None:
    """Create data/storage directories if they do not exist yet."""
    for path in (DATA_DIR, STORAGE_DIR, PDF_DIR, COVER_DIR):
        path.mkdir(parents=True, exist_ok=True)


def load_secret_key() -> str:
    """Return the Flask session secret key.

    Resolution order:
      1. IDL_SECRET_KEY environment variable (recommended for deployment).
      2. A randomly generated key persisted to data/secret_key (dev convenience).

    The key is never exposed to client-side code; it only signs session cookies.
    """
    env_key = os.environ.get("IDL_SECRET_KEY", "").strip()
    if env_key:
        return env_key
    ensure_dirs()
    if SECRET_KEY_FILE.exists():
        return SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(key, encoding="utf-8")
    try:
        os.chmod(SECRET_KEY_FILE, 0o600)
    except OSError:
        pass
    return key
