"""SQLite persistence layer: schema, connections, and book queries.

Every query is parameterized. Public queries can be restricted to published
books at the SQL level so unpublished material cannot leak through the API.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from flask import g

from . import config

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS books (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT    NOT NULL,
    author        TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    category      TEXT    NOT NULL,
    language      TEXT    NOT NULL DEFAULT 'English',
    pdf_filename  TEXT    NOT NULL,
    pdf_size      INTEGER NOT NULL,
    page_count    INTEGER NOT NULL DEFAULT 0,
    cover_filename TEXT,
    featured      INTEGER NOT NULL DEFAULT 0,
    published     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_books_published ON books(published);
CREATE INDEX IF NOT EXISTS idx_books_category  ON books(category);
CREATE INDEX IF NOT EXISTS idx_books_language  ON books(language);
CREATE INDEX IF NOT EXISTS idx_books_created   ON books(created_at DESC);
"""

VALID_SORTS = {
    "newest": "created_at DESC, id DESC",
    "oldest": "created_at ASC, id ASC",
    "title": "title COLLATE NOCASE ASC",
    "author": "author COLLATE NOCASE ASC",
}


# --------------------------------------------------------------------------
# connection handling
# --------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(config.DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc: Optional[BaseException] = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    ensure_schema()


def ensure_schema() -> None:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _like(term: str) -> str:
    """Build a LIKE pattern, escaping user wildcards."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# --------------------------------------------------------------------------
# admins
# --------------------------------------------------------------------------

def get_admin_by_username(username: str) -> Optional[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM admins WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()


def get_admin_by_id(admin_id: int) -> Optional[sqlite3.Row]:
    return get_db().execute("SELECT * FROM admins WHERE id = ?", (admin_id,)).fetchone()


def count_admins() -> int:
    return get_db().execute("SELECT COUNT(*) AS n FROM admins").fetchone()["n"]


def create_admin(username: str, password_hash: str) -> int:
    cur = get_db().execute(
        "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
        (username, password_hash),
    )
    get_db().commit()
    return int(cur.lastrowid)


def update_admin_password(admin_id: int, password_hash: str) -> None:
    get_db().execute(
        "UPDATE admins SET password_hash = ? WHERE id = ?", (password_hash, admin_id)
    )
    get_db().commit()


# --------------------------------------------------------------------------
# books
# --------------------------------------------------------------------------

def _book_filters(
    q: str = "",
    category: str = "",
    language: str = "",
    featured: Optional[int] = None,
    published_only: bool = True,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if published_only:
        clauses.append("published = 1")
    if featured is not None:
        clauses.append("featured = ?")
        params.append(featured)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if language:
        clauses.append("language = ?")
        params.append(language)
    if q:
        clauses.append(
            "(title LIKE ? ESCAPE '\\' OR author LIKE ? ESCAPE '\\' "
            "OR category LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')"
        )
        pattern = _like(q)
        params.extend([pattern, pattern, pattern, pattern])
    return clauses, params


def list_books(
    q: str = "",
    category: str = "",
    language: str = "",
    sort: str = "newest",
    page: int = 1,
    per_page: int = 12,
    featured: Optional[int] = None,
    published_only: bool = True,
    limit: Optional[int] = None,
) -> tuple[list[sqlite3.Row], int]:
    """Return (rows, total_matching)."""
    order = VALID_SORTS.get(sort, VALID_SORTS["newest"])
    clauses, params = _book_filters(q, category, language, featured, published_only)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    total = get_db().execute(
        f"SELECT COUNT(*) AS n FROM books {where}", params
    ).fetchone()["n"]

    if limit is not None:
        rows = get_db().execute(
            f"SELECT * FROM books {where} ORDER BY {order} LIMIT ?",
            params + [limit],
        ).fetchall()
        return rows, total

    page = max(1, page)
    offset = (page - 1) * per_page
    rows = get_db().execute(
        f"SELECT * FROM books {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ).fetchall()
    return rows, total


def get_book(book_id: int, published_only: bool = True) -> Optional[sqlite3.Row]:
    if published_only:
        return get_db().execute(
            "SELECT * FROM books WHERE id = ? AND published = 1", (book_id,)
        ).fetchone()
    return get_db().execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()


def related_books(book: sqlite3.Row, limit: int = 4) -> list[sqlite3.Row]:
    rows = get_db().execute(
        "SELECT * FROM books WHERE published = 1 AND category = ? AND id != ? "
        "ORDER BY created_at DESC LIMIT ?",
        (book["category"], book["id"], limit),
    ).fetchall()
    return rows


def insert_book(data: dict[str, Any]) -> int:
    now = utcnow()
    cur = get_db().execute(
        """
        INSERT INTO books (title, author, description, category, language,
                           pdf_filename, pdf_size, page_count, cover_filename,
                           featured, published, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["title"],
            data["author"],
            data.get("description", ""),
            data["category"],
            data.get("language", "English"),
            data["pdf_filename"],
            data["pdf_size"],
            data.get("page_count", 0),
            data.get("cover_filename"),
            1 if data.get("featured") else 0,
            1 if data.get("published") else 0,
            now,
            now,
        ),
    )
    get_db().commit()
    return int(cur.lastrowid)


def update_book(book_id: int, data: dict[str, Any]) -> None:
    """Update mutable fields; pdf/cover filenames handled separately."""
    now = utcnow()
    get_db().execute(
        """
        UPDATE books SET title = ?, author = ?, description = ?, category = ?,
                         language = ?, featured = ?, published = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            data["title"],
            data["author"],
            data.get("description", ""),
            data["category"],
            data.get("language", "English"),
            1 if data.get("featured") else 0,
            1 if data.get("published") else 0,
            now,
            book_id,
        ),
    )
    get_db().commit()


def replace_book_pdf(book_id: int, pdf_filename: str, pdf_size: int, page_count: int) -> None:
    get_db().execute(
        "UPDATE books SET pdf_filename = ?, pdf_size = ?, page_count = ?, "
        "updated_at = ? WHERE id = ?",
        (pdf_filename, pdf_size, page_count, utcnow(), book_id),
    )
    get_db().commit()


def set_book_cover(book_id: int, cover_filename: Optional[str]) -> None:
    get_db().execute(
        "UPDATE books SET cover_filename = ?, updated_at = ? WHERE id = ?",
        (cover_filename, utcnow(), book_id),
    )
    get_db().commit()


def set_published(book_id: int, published: bool) -> None:
    get_db().execute(
        "UPDATE books SET published = ?, updated_at = ? WHERE id = ?",
        (1 if published else 0, utcnow(), book_id),
    )
    get_db().commit()


def delete_book(book_id: int) -> Optional[sqlite3.Row]:
    row = get_book(book_id, published_only=False)
    if row is not None:
        get_db().execute("DELETE FROM books WHERE id = ?", (book_id,))
        get_db().commit()
    return row


# --------------------------------------------------------------------------
# facets & stats
# --------------------------------------------------------------------------

def category_counts(published_only: bool = True) -> list[sqlite3.Row]:
    where = "WHERE published = 1" if published_only else ""
    return get_db().execute(
        f"SELECT category, COUNT(*) AS n FROM books {where} "
        "GROUP BY category ORDER BY n DESC, category COLLATE NOCASE ASC"
    ).fetchall()


def language_counts(published_only: bool = True) -> list[sqlite3.Row]:
    where = "WHERE published = 1" if published_only else ""
    return get_db().execute(
        f"SELECT language, COUNT(*) AS n FROM books {where} "
        "GROUP BY language ORDER BY n DESC, language COLLATE NOCASE ASC"
    ).fetchall()


def stats() -> dict[str, int]:
    row = get_db().execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN published = 1 THEN 1 ELSE 0 END), 0) AS published,
            COALESCE(SUM(CASE WHEN published = 0 THEN 1 ELSE 0 END), 0) AS drafts,
            COALESCE(SUM(pdf_size), 0) AS bytes,
            COUNT(DISTINCT category) AS categories
        FROM books
        """
    ).fetchone()
    return {
        "total": row["total"],
        "published": row["published"],
        "drafts": row["drafts"],
        "bytes": row["bytes"],
        "categories": row["categories"],
    }


def page_count(total_items: int, per_page: int) -> int:
    return max(1, math.ceil(total_items / per_page)) if total_items else 1
