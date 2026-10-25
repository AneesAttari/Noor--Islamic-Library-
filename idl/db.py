"""SQLite persistence layer: schema, migrations, and queries.

Everything is parameterized. Public queries exclude unpublished and deleted
books at the SQL level. Full-text search is backed by an FTS5 index over
title/author/category/description **and the extracted text of each PDF**.
"""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from flask import g

from . import config

BASE_SCHEMA = """
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
    preview_filename TEXT,
    featured      INTEGER NOT NULL DEFAULT 0,
    pinned_order  INTEGER,
    published     INTEGER NOT NULL DEFAULT 0,
    open_count    INTEGER NOT NULL DEFAULT 0,
    download_count INTEGER NOT NULL DEFAULT 0,
    deleted_at    TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS book_text (
    book_id  INTEGER PRIMARY KEY,
    text     TEXT NOT NULL DEFAULT ''
);

CREATE VIRTUAL TABLE IF NOT EXISTS book_fts USING fts5(
    title, author, category, description, content_text, book_id UNINDEXED
);

CREATE TABLE IF NOT EXISTS book_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id    INTEGER NOT NULL,
    kind       TEXT    NOT NULL CHECK (kind IN ('read','download')),
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_events_book ON book_events(book_id);
CREATE INDEX IF NOT EXISTS idx_events_time ON book_events(created_at DESC);

CREATE TABLE IF NOT EXISTS book_revisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id      INTEGER NOT NULL,
    pdf_filename TEXT    NOT NULL,
    pdf_size     INTEGER NOT NULL,
    page_count   INTEGER NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_revisions_book ON book_revisions(book_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id   INTEGER,
    admin_username TEXT NOT NULL DEFAULT '',
    action     TEXT    NOT NULL,
    book_id    INTEGER,
    detail     TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_log(created_at DESC);

CREATE TABLE IF NOT EXISTS contact_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL DEFAULT '',
    email      TEXT    NOT NULL DEFAULT '',
    subject    TEXT    NOT NULL DEFAULT '',
    message    TEXT    NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'new' CHECK (status IN ('new','read')),
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_messages_status ON contact_messages(status);

CREATE INDEX IF NOT EXISTS idx_books_published ON books(published);
CREATE INDEX IF NOT EXISTS idx_books_category  ON books(category);
CREATE INDEX IF NOT EXISTS idx_books_language  ON books(language);
CREATE INDEX IF NOT EXISTS idx_books_created   ON books(created_at DESC);
"""

# Columns added after the first release; applied automatically to old DBs.
BOOK_COLUMNS = {
    "preview_filename": "TEXT",
    "pinned_order": "INTEGER",
    "open_count": "INTEGER NOT NULL DEFAULT 0",
    "download_count": "INTEGER NOT NULL DEFAULT 0",
    "deleted_at": "TEXT",
}

VALID_SORTS = {
    "newest": "created_at DESC, id DESC",
    "oldest": "created_at ASC, id ASC",
    "title": "title COLLATE NOCASE ASC",
    "author": "author COLLATE NOCASE ASC",
    "popular": "open_count + download_count DESC, created_at DESC",
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
        conn.executescript(BASE_SCHEMA)
        # migrate old databases: add any missing book columns
        existing = {r[1] for r in conn.execute("PRAGMA table_info(books)")}
        for name, decl in BOOK_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE books ADD COLUMN {name} {decl}")
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _like(term: str) -> str:
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
# full-text search sync
# --------------------------------------------------------------------------

def fts_sync(book_id: int) -> None:
    """Reindex one book in the FTS table from its row + extracted text."""
    book = get_book(book_id, published_only=False, include_deleted=True)
    if book is None:
        get_db().execute("DELETE FROM book_fts WHERE book_id = ?", (book_id,))
        return
    text_row = get_db().execute(
        "SELECT text FROM book_text WHERE book_id = ?", (book_id,)
    ).fetchone()
    content = text_row["text"] if text_row else ""
    get_db().execute("DELETE FROM book_fts WHERE book_id = ?", (book_id,))
    get_db().execute(
        "INSERT INTO book_fts (title, author, category, description, content_text, book_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (book["title"], book["author"], book["category"], book["description"], content, book_id),
    )


def set_book_text(book_id: int, text: str) -> None:
    get_db().execute(
        "INSERT INTO book_text (book_id, text) VALUES (?, ?) "
        "ON CONFLICT(book_id) DO UPDATE SET text = excluded.text",
        (book_id, text),
    )
    fts_sync(book_id)
    get_db().commit()


def _fts_match_query(q: str) -> str:
    """Turn free text into a safe FTS5 query: every token as a prefix term."""
    tokens = []
    for raw in q.split():
        term = raw.replace('"', '""')
        tokens.append(f'"{term}"*')
    return " ".join(tokens)


# --------------------------------------------------------------------------
# books
# --------------------------------------------------------------------------

def _book_filters(
    q: str = "",
    category: str = "",
    language: str = "",
    featured: Optional[int] = None,
    published_only: bool = True,
    include_deleted: bool = False,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if published_only:
        clauses.append("published = 1")
    if not include_deleted:
        clauses.append("deleted_at IS NULL")
    if featured is not None:
        clauses.append("featured = ?")
        params.append(featured)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if language:
        clauses.append("language = ?")
        params.append(language)
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
    include_deleted: bool = False,
) -> tuple[list[sqlite3.Row], int]:
    """Return (rows, total_matching). `q` searches metadata and PDF contents."""
    order = VALID_SORTS.get(sort, VALID_SORTS["newest"])
    clauses, params = _book_filters(q, category, language, featured, published_only, include_deleted)

    if q:
        match = _fts_match_query(q)
        if match:
            inner_from = (
                "FROM books b JOIN book_fts ON book_fts.book_id = b.id "
                f"WHERE book_fts MATCH ? {'AND ' + ' AND '.join(clauses) if clauses else ''}"
            )
            inner_params = [match] + params
            total = get_db().execute(
                f"SELECT COUNT(*) AS n {inner_from}", inner_params
            ).fetchone()["n"]
            order_sql = "rank" if sort == "newest" else order
            if limit is not None:
                rows = get_db().execute(
                    f"SELECT b.* {inner_from} ORDER BY {order_sql} LIMIT ?",
                    inner_params + [limit],
                ).fetchall()
                return rows, total
            page = max(1, page)
            rows = get_db().execute(
                f"SELECT b.* {inner_from} ORDER BY {order_sql} LIMIT ? OFFSET ?",
                inner_params + [per_page, (page - 1) * per_page],
            ).fetchall()
            return rows, total

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    total = get_db().execute(f"SELECT COUNT(*) AS n FROM books {where}", params).fetchone()["n"]
    if limit is not None:
        rows = get_db().execute(
            f"SELECT * FROM books {where} ORDER BY {order} LIMIT ?", params + [limit]
        ).fetchall()
        return rows, total
    page = max(1, page)
    rows = get_db().execute(
        f"SELECT * FROM books {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page],
    ).fetchall()
    return rows, total


def get_book(book_id: int, published_only: bool = True, include_deleted: bool = False) -> Optional[sqlite3.Row]:
    query = "SELECT * FROM books WHERE id = ?"
    params: list[Any] = [book_id]
    if published_only:
        query += " AND published = 1"
    if not include_deleted:
        query += " AND deleted_at IS NULL"
    return get_db().execute(query, params).fetchone()


def related_books(book: sqlite3.Row, limit: int = 4) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM books WHERE published = 1 AND deleted_at IS NULL "
        "AND category = ? AND id != ? ORDER BY created_at DESC LIMIT ?",
        (book["category"], book["id"], limit),
    ).fetchall()


def insert_book(data: dict[str, Any]) -> int:
    now = utcnow()
    cur = get_db().execute(
        """
        INSERT INTO books (title, author, description, category, language,
                           pdf_filename, pdf_size, page_count, cover_filename,
                           preview_filename, featured, published, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["title"], data["author"], data.get("description", ""),
            data["category"], data.get("language", "English"),
            data["pdf_filename"], data["pdf_size"], data.get("page_count", 0),
            data.get("cover_filename"), data.get("preview_filename"),
            1 if data.get("featured") else 0,
            1 if data.get("published") else 0,
            now, now,
        ),
    )
    get_db().commit()
    book_id = int(cur.lastrowid)
    fts_sync(book_id)
    get_db().commit()
    return book_id


def update_book(book_id: int, data: dict[str, Any]) -> None:
    now = utcnow()
    get_db().execute(
        """
        UPDATE books SET title = ?, author = ?, description = ?, category = ?,
                         language = ?, featured = ?, published = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            data["title"], data["author"], data.get("description", ""),
            data["category"], data.get("language", "English"),
            1 if data.get("featured") else 0,
            1 if data.get("published") else 0,
            now, book_id,
        ),
    )
    fts_sync(book_id)
    get_db().commit()


def replace_book_pdf(book_id: int, pdf_filename: str, pdf_size: int, page_count: int) -> None:
    get_db().execute(
        "UPDATE books SET pdf_filename = ?, pdf_size = ?, page_count = ?, "
        "updated_at = ? WHERE id = ?",
        (pdf_filename, pdf_size, page_count, utcnow(), book_id),
    )
    get_db().commit()


def add_revision(book_id: int, pdf_filename: str, pdf_size: int, page_count: int) -> int:
    cur = get_db().execute(
        "INSERT INTO book_revisions (book_id, pdf_filename, pdf_size, page_count) VALUES (?, ?, ?, ?)",
        (book_id, pdf_filename, pdf_size, page_count),
    )
    get_db().commit()
    return int(cur.lastrowid)


def list_revisions(book_id: int) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM book_revisions WHERE book_id = ? ORDER BY created_at DESC", (book_id,)
    ).fetchall()


def get_revision(revision_id: int) -> Optional[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM book_revisions WHERE id = ?", (revision_id,)
    ).fetchone()


def delete_revision(revision_id: int) -> None:
    get_db().execute("DELETE FROM book_revisions WHERE id = ?", (revision_id,))
    get_db().commit()


def set_book_cover(book_id: int, cover_filename: Optional[str]) -> None:
    get_db().execute(
        "UPDATE books SET cover_filename = ?, updated_at = ? WHERE id = ?",
        (cover_filename, utcnow(), book_id),
    )
    get_db().commit()


def set_book_preview(book_id: int, preview_filename: Optional[str]) -> None:
    get_db().execute(
        "UPDATE books SET preview_filename = ?, updated_at = ? WHERE id = ?",
        (preview_filename, utcnow(), book_id),
    )
    get_db().commit()


def set_published(book_id: int, published: bool) -> None:
    get_db().execute(
        "UPDATE books SET published = ?, updated_at = ? WHERE id = ?",
        (1 if published else 0, utcnow(), book_id),
    )
    get_db().commit()


def soft_delete_book(book_id: int) -> None:
    get_db().execute(
        "UPDATE books SET deleted_at = ?, updated_at = ? WHERE id = ?",
        (utcnow(), utcnow(), book_id),
    )
    get_db().commit()


def restore_book(book_id: int) -> None:
    get_db().execute(
        "UPDATE books SET deleted_at = NULL, updated_at = ? WHERE id = ?", (utcnow(), book_id)
    )
    get_db().commit()


def list_trash() -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM books WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
    ).fetchall()


def purge_book(book_id: int) -> Optional[sqlite3.Row]:
    row = get_book(book_id, published_only=False, include_deleted=True)
    if row is not None:
        conn = get_db()
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.execute("DELETE FROM book_text WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM book_fts WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM book_revisions WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM book_events WHERE book_id = ?", (book_id,))
        conn.commit()
    return row


# --------------------------------------------------------------------------
# events (popularity)
# --------------------------------------------------------------------------

def record_event(book_id: int, kind: str) -> None:
    conn = get_db()
    conn.execute("INSERT INTO book_events (book_id, kind) VALUES (?, ?)", (book_id, kind))
    if kind == "read":
        conn.execute("UPDATE books SET open_count = open_count + 1 WHERE id = ?", (book_id,))
    elif kind == "download":
        conn.execute("UPDATE books SET download_count = download_count + 1 WHERE id = ?", (book_id,))
    conn.commit()


def popular_books(days: int = 30, limit: int = 6) -> list[sqlite3.Row]:
    return get_db().execute(
        """
        SELECT b.*, COUNT(e.id) AS hits
        FROM books b JOIN book_events e ON e.book_id = b.id
        WHERE b.published = 1 AND b.deleted_at IS NULL
          AND e.created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)
        GROUP BY b.id
        ORDER BY hits DESC, b.open_count + b.download_count DESC
        LIMIT ?
        """,
        (f"-{int(days)} days", limit),
    ).fetchall()


# --------------------------------------------------------------------------
# pinning (featured order)
# --------------------------------------------------------------------------

def featured_ordered() -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM books WHERE featured = 1 AND deleted_at IS NULL "
        "ORDER BY (pinned_order IS NULL), pinned_order ASC, created_at DESC"
    ).fetchall()


def _renumber_featured() -> None:
    conn = get_db()
    for i, row in enumerate(featured_ordered(), start=1):
        conn.execute("UPDATE books SET pinned_order = ? WHERE id = ?", (i, row["id"]))
    conn.commit()


def pin_move(book_id: int, direction: str) -> None:
    """Move a featured book up/down/top within the pinned order."""
    items = featured_ordered()
    ids = [r["id"] for r in items]
    if book_id not in ids:
        return
    pos = ids.index(book_id)
    if direction == "top":
        ids.insert(0, ids.pop(pos))
    elif direction == "up" and pos > 0:
        ids[pos - 1], ids[pos] = ids[pos], ids[pos - 1]
    elif direction == "down" and pos < len(ids) - 1:
        ids[pos + 1], ids[pos] = ids[pos], ids[pos + 1]
    conn = get_db()
    for i, bid in enumerate(ids, start=1):
        conn.execute("UPDATE books SET pinned_order = ? WHERE id = ?", (i, bid))
    conn.commit()


def pin_clear(book_id: int) -> None:
    conn = get_db()
    conn.execute("UPDATE books SET pinned_order = NULL WHERE id = ?", (book_id,))
    conn.commit()
    # compact the remaining PINNED books only (the cleared one stays unpinned)
    rows = conn.execute(
        "SELECT id FROM books WHERE featured = 1 AND deleted_at IS NULL "
        "AND pinned_order IS NOT NULL ORDER BY pinned_order ASC, created_at DESC"
    ).fetchall()
    for i, row in enumerate(rows, start=1):
        conn.execute("UPDATE books SET pinned_order = ? WHERE id = ?", (i, row["id"]))
    conn.commit()


# --------------------------------------------------------------------------
# audit log
# --------------------------------------------------------------------------

def audit(action: str, admin_username: str = "", book_id: Optional[int] = None,
          detail: str = "", admin_id: Optional[int] = None) -> None:
    get_db().execute(
        "INSERT INTO audit_log (admin_id, admin_username, action, book_id, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (admin_id, admin_username, action, book_id, detail),
    )
    get_db().commit()


def audit_entries(limit: int = 200) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()


# --------------------------------------------------------------------------
# facets & stats
# --------------------------------------------------------------------------

def category_counts(published_only: bool = True, include_deleted: bool = False) -> list[sqlite3.Row]:
    clauses = []
    if published_only:
        clauses.append("published = 1")
    if not include_deleted:
        clauses.append("deleted_at IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return get_db().execute(
        f"SELECT category, COUNT(*) AS n FROM books {where} "
        "GROUP BY category ORDER BY n DESC, category COLLATE NOCASE ASC"
    ).fetchall()


def language_counts(published_only: bool = True, include_deleted: bool = False) -> list[sqlite3.Row]:
    clauses = []
    if published_only:
        clauses.append("published = 1")
    if not include_deleted:
        clauses.append("deleted_at IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return get_db().execute(
        f"SELECT language, COUNT(*) AS n FROM books {where} "
        "GROUP BY language ORDER BY n DESC, language COLLATE NOCASE ASC"
    ).fetchall()


def rename_term(field: str, old: str, new: str) -> int:
    """Rename a category/language across all books. Returns rows changed."""
    assert field in ("category", "language")
    cur = get_db().execute(
        f"UPDATE books SET {field} = ?, updated_at = ? WHERE {field} = ?",
        (new, utcnow(), old),
    )
    for row in get_db().execute("SELECT id FROM books WHERE category = ? OR language = ?", (new, new)).fetchall():
        fts_sync(row["id"])
    get_db().commit()
    return cur.rowcount


def merge_term(field: str, source: str, target: str) -> int:
    return rename_term(field, source, target)


def term_book_count(field: str, value: str) -> int:
    assert field in ("category", "language")
    return get_db().execute(
        f"SELECT COUNT(*) AS n FROM books WHERE {field} = ?", (value,)
    ).fetchone()["n"]


def stats() -> dict[str, int]:
    row = get_db().execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN published = 1 AND deleted_at IS NULL THEN 1 ELSE 0 END), 0) AS published,
            COALESCE(SUM(CASE WHEN published = 0 AND deleted_at IS NULL THEN 1 ELSE 0 END), 0) AS drafts,
            COALESCE(SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS trashed,
            COALESCE(SUM(CASE WHEN deleted_at IS NULL THEN pdf_size ELSE 0 END), 0) AS bytes,
            COUNT(DISTINCT CASE WHEN deleted_at IS NULL THEN category END) AS categories
        FROM books
        """
    ).fetchone()
    return {
        "total": row["total"],
        "published": row["published"],
        "drafts": row["drafts"],
        "trashed": row["trashed"],
        "bytes": row["bytes"],
        "categories": row["categories"],
    }


def page_count(total_items: int, per_page: int) -> int:
    return max(1, math.ceil(total_items / per_page)) if total_items else 1


# --------------------------------------------------------------------------
# contact messages
# --------------------------------------------------------------------------

def add_message(name: str, email: str, subject: str, message: str) -> int:
    cur = get_db().execute(
        "INSERT INTO contact_messages (name, email, subject, message) VALUES (?, ?, ?, ?)",
        (name, email, subject, message),
    )
    get_db().commit()
    return int(cur.lastrowid)


def list_messages() -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM contact_messages ORDER BY created_at DESC LIMIT 200"
    ).fetchall()


def get_message(message_id: int) -> Optional[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM contact_messages WHERE id = ?", (message_id,)
    ).fetchone()


def set_message_status(message_id: int, status: str) -> None:
    get_db().execute(
        "UPDATE contact_messages SET status = ? WHERE id = ?", (status, message_id)
    )
    get_db().commit()


def delete_message(message_id: int) -> None:
    get_db().execute("DELETE FROM contact_messages WHERE id = ?", (message_id,))
    get_db().commit()


def unread_message_count() -> int:
    return get_db().execute(
        "SELECT COUNT(*) AS n FROM contact_messages WHERE status = 'new'"
    ).fetchone()["n"]


def all_books_for_export() -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM books WHERE deleted_at IS NULL ORDER BY id"
    ).fetchall()
