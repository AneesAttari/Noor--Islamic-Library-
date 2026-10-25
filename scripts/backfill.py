"""Backfill search text and first-page previews for existing books.

Run after upgrading an existing database (or after importing books):
    python3 scripts/backfill.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from idl import create_app, db, storage  # noqa: E402


def main() -> int:
    app = create_app()
    with app.app_context():
        db.ensure_schema()
        books, _ = db.list_books(published_only=False, per_page=1000, include_deleted=True)
        for book in books:
            changed = False

            row = db.get_db().execute(
                "SELECT text FROM book_text WHERE book_id = ?", (book["id"],)
            ).fetchone()
            if not row or not row["text"].strip():
                text = storage.extract_pdf_text(book["pdf_filename"])
                db.set_book_text(book["id"], text)
                print(f"#{book['id']} indexed text ({len(text)} chars)")
                changed = True

            if not book["preview_filename"]:
                preview = storage.generate_preview(book["pdf_filename"])
                if preview:
                    db.set_book_preview(book["id"], preview)
                    print(f"#{book['id']} generated preview {preview}")
                    changed = True

            if changed:
                db.fts_sync(book["id"])
                db.get_db().commit()
        print("backfill complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
