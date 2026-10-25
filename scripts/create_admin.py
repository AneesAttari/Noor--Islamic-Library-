"""Create or reset the library administrator account.

The password is never stored in plaintext: only an argon2 hash is written to
the database. Credentials are supplied via environment variables or an
interactive prompt — never committed to source code.

Usage:
    python scripts/create_admin.py
    IDL_ADMIN_USERNAME=admin IDL_ADMIN_PASSWORD='...' python scripts/create_admin.py
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from idl import config, create_app, db, security  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        db.ensure_schema()

        username = (os.environ.get("IDL_ADMIN_USERNAME") or "").strip()
        password = os.environ.get("IDL_ADMIN_PASSWORD") or ""

        if not username:
            username = input("Admin username: ").strip()
        if not password:
            password = getpass.getpass("Admin password (min 10 chars): ")

        if not username:
            print("Error: username must not be empty.", file=sys.stderr)
            return 1
        if len(password) < 10:
            print("Error: password must be at least 10 characters.", file=sys.stderr)
            return 1

        existing = db.get_admin_by_username(username)
        if existing:
            db.update_admin_password(existing["id"], security.hash_password(password))
            print(f"Updated password for existing admin '{username}'.")
        else:
            db.create_admin(username, security.hash_password(password))
            print(f"Created admin '{username}'.")
        print("You can now sign in at /admin/login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
