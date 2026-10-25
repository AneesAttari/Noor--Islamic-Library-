"""Tests for Round 1 & 2 features.

Round 1: PDF full-text search, reader resume, reader UI (mode/progress),
         RTL support, download counts + popular shelf, first-page previews.
Round 2: bulk upload, PDF metadata probe, category/language manager,
         audit log, featured pinning, backup/CSV export, trash + revisions.
"""
from __future__ import annotations

import io
import os
import re
import sys
import zipfile
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas as pdf_canvas

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from idl import config, create_app, db, security  # noqa: E402

STORAGE_DIR = config.STORAGE_DIR

ADMIN_USER = "featureadmin"
ADMIN_PASS = "another-long-test-password"


def make_pdf_bytes(pages: int = 2, title: str = "Test", body: str = "") -> bytes:
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer)
    for i in range(pages):
        c.drawString(72, 720, f"{title} — page {i + 1}")
        if body:
            c.drawString(72, 680, body)
        c.showPage()
    c.save()
    return buffer.getvalue()


def login(client):
    page = client.get("/admin/login", follow_redirects=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    token = match.group(1)
    resp = client.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS, "csrf_token": token},
    )
    assert resp.status_code == 302
    return client


def csrf(client, path="/admin/books/new"):
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


def create_book(client, title="Feature Book", author="Author X", category="Testing",
                body="", published="1", pages=2, **extra):
    data = {
        "csrf_token": csrf(client),
        "title": title,
        "author": author,
        "category": category,
        "language": "English",
        "description": extra.pop("description", ""),
        "published": published,
        "pdf": (io.BytesIO(make_pdf_bytes(pages, title, body)), "f.pdf"),
    }
    data.update(extra)
    resp = client.post("/admin/books/new", data=data, content_type="multipart/form-data")
    assert resp.status_code == 302, resp.get_data(as_text=True)[:500]
    with client.application.app_context():
        rows, _ = db.list_books(q=title, published_only=False, include_deleted=True)
        return rows[0]


# ==========================================================================
# Round 1
# ==========================================================================

def test_r1_fulltext_search_finds_text_inside_pdf(client, app):
    login(client)
    create_book(client, title="Book About Astronomy", body="ZijAlSultani is a star catalogue term")
    # search term appears ONLY inside the PDF body, not in metadata
    resp = client.get("/catalogue?q=ZijAlSultani")
    assert resp.status_code == 200
    assert "Book About Astronomy" in resp.get_data(as_text=True)
    # a nonsense term finds nothing
    resp = client.get("/catalogue?q=qqqzzznotfound")
    assert "No books found" in resp.get_data(as_text=True)


def test_r1_reader_resume_ui_and_page_param(client):
    login(client)
    book = create_book(client, title="Resumable Book", pages=3)
    html = client.get(f"/books/{book['id']}/read").get_data(as_text=True)
    assert "resume-bar" in html          # resume UI present
    assert "btn-mode-scroll" in html     # continuous mode toggle
    assert "progress-bar" in html        # progress bar
    assert "maktaba" in html or "localStorage" in Path(
        os.path.join(os.path.dirname(__file__), "..", "static", "js", "reader.js")
    ).read_text()  # position memory implemented in reader.js
    # ?p= deep-link loads the reader (page selection is client-side)
    assert client.get(f"/books/{book['id']}/read?p=2").status_code == 200


def test_r1_rtl_detection(client):
    from idl.views_public import textdir

    assert textdir("صحيح البخاري") == "rtl"
    assert textdir("الجامع المسند") == "rtl"
    assert textdir("Sahih al-Bukhari") == "ltr"
    assert textdir("") == "ltr"

    login(client)
    book = create_book(client, title="صحيح مسلم", author="الإمام مسلم")
    html = client.get(f"/books/{book['id']}").get_data(as_text=True)
    assert 'dir="rtl"' in html


def test_r1_counts_and_popular_shelf(client, app):
    login(client)
    book = create_book(client, title="Popular Candidate")
    anon = app.test_client()

    # visitors reading and downloading are counted
    anon.get(f"/books/{book['id']}/read")
    anon.get(f"/books/{book['id']}/read")
    anon.get(f"/books/{book['id']}/pdf?download=1")
    with app.app_context():
        row = db.get_book(book["id"])
        assert row["open_count"] == 2
        assert row["download_count"] == 1

    # admin actions are NOT counted
    client.get(f"/books/{book['id']}/read")
    with app.app_context():
        assert db.get_book(book["id"])["open_count"] == 2

    # home page shows the popular shelf
    home = anon.get("/").get_data(as_text=True)
    assert "Popular this month" in home
    assert "Popular Candidate" in home


def test_r1_first_page_preview(client, app):
    login(client)
    book = create_book(client, title="Previewed Book")
    with app.app_context():
        row = db.get_book(book["id"])
        assert row["preview_filename"], "preview was not generated at upload"
        preview_file = STORAGE_DIR / "previews" / row["preview_filename"]
        assert preview_file.is_file()

    resp = client.get(f"/books/{book['id']}/preview")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("image/jpeg")

    # detail page shows the preview
    html = client.get(f"/books/{book['id']}").get_data(as_text=True)
    assert f"/books/{book['id']}/preview" in html


# ==========================================================================
# Round 2
# ==========================================================================

def test_r2_bulk_upload(client, app):
    login(client)
    token = csrf(client, "/admin/books/bulk")
    resp = client.post(
        "/admin/books/bulk",
        data={
            "csrf_token": token,
            "category": "Bulk Category",
            "language": "English",
            "published": "1",
            "parse_names": "1",
            "pdfs": [
                (io.BytesIO(make_pdf_bytes(1, "Alpha")), "Alice Author - Alpha Book.pdf"),
                (io.BytesIO(make_pdf_bytes(1, "Beta")), "Beta Book.pdf"),
                (io.BytesIO(b"not a pdf"), "broken.pdf"),
            ],
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Alpha Book" in html          # parsed from 'Author - Title' filename
    assert "Beta Book" in html           # filename fallback
    assert "not a valid PDF" in html     # honest failure report
    with app.app_context():
        rows, total = db.list_books(category="Bulk Category", published_only=False)
        assert total == 2
        titles = {r["title"] for r in rows}
        assert "Alpha Book" in titles and "Beta Book" in titles


def test_r2_pdf_metadata_probe(client):
    login(client)
    token = csrf(client)
    resp = client.post(
        "/admin/api/probe-pdf",
        data={"csrf_token": token, "pdf": (io.BytesIO(make_pdf_bytes(3, "Probe Title")), "p.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["page_count"] == 3

    resp = client.post(
        "/admin/api/probe-pdf",
        data={"csrf_token": token, "pdf": (io.BytesIO(b"junk"), "p.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_r2_terms_manager_rename_and_merge(client, app):
    login(client)
    create_book(client, title="Cat Book 1", category="Old Category")
    create_book(client, title="Cat Book 2", category="Old Category")

    token = csrf(client, "/admin/terms")
    # rename
    resp = client.post(
        "/admin/terms/rename",
        data={"csrf_token": token, "field": "category", "old": "Old Category", "new": "Renamed Category"},
    )
    assert resp.status_code == 302
    with app.app_context():
        assert db.term_book_count("category", "Renamed Category") == 2

    # merge into another
    create_book(client, title="Cat Book 3", category="Other Category")
    token = csrf(client, "/admin/terms")
    resp = client.post(
        "/admin/terms/merge",
        data={"csrf_token": token, "field": "category", "source": "Renamed Category", "target": "Other Category"},
    )
    assert resp.status_code == 302
    with app.app_context():
        assert db.term_book_count("category", "Other Category") == 3
        assert db.term_book_count("category", "Renamed Category") == 0

    # empty names can be removed; names with books cannot
    resp = client.post(
        "/admin/terms/delete",
        data={"csrf_token": token, "field": "category", "name": "Other Category"},
        follow_redirects=True,
    )
    assert "still has books" in resp.get_data(as_text=True)

    # renamed search still works (fts synced)
    resp = client.get("/catalogue?q=Cat+Book")
    assert resp.status_code == 200


def test_r2_audit_log_records_actions(client, app):
    login(client)
    book = create_book(client, title="Audited Book")
    token = csrf(client, "/admin/")
    client.post(f"/admin/books/{book['id']}/publish", data={"csrf_token": token, "value": "0"})
    client.post(f"/admin/books/{book['id']}/delete", data={"csrf_token": token})

    html = client.get("/admin/audit").get_data(as_text=True)
    assert "Audited Book" in html
    assert "create" in html
    assert "unpublish" in html
    assert "trash" in html
    assert ADMIN_USER in html


def test_r2_featured_pinning(client, app):
    login(client)
    a = create_book(client, title="Pin Book A", featured="1")
    b = create_book(client, title="Pin Book B", featured="1")

    # newest featured first by default (B before A on home)
    with app.app_context():
        order = [r["title"] for r in db.featured_ordered()]
    assert order.index("Pin Book B") < order.index("Pin Book A")

    token = csrf(client, "/admin/")
    client.post(f"/admin/books/{a['id']}/pin", data={"csrf_token": token, "action": "top"})
    with app.app_context():
        order = [r["title"] for r in db.featured_ordered()]
    assert order[0] == "Pin Book A"

    token = csrf(client, "/admin/")
    client.post(f"/admin/books/{a['id']}/pin", data={"csrf_token": token, "action": "unpin"})
    with app.app_context():
        row = db.get_book(a["id"])
        assert row["pinned_order"] is None


def test_r2_backup_zip_and_csv(client, app):
    login(client)
    create_book(client, title="Backup Book")

    resp = client.get("/admin/backup")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("application/zip")
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    names = zf.namelist()
    assert "data/library.db" in names
    assert "README.txt" in names
    assert any(n.startswith("storage/pdfs/") for n in names)

    resp = client.get("/admin/export.csv")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    body = resp.get_data(as_text=True)
    assert "Backup Book" in body
    assert "title,author,category" in body


def test_r2_pdf_replacement_keeps_revision(client, app):
    login(client)
    book = create_book(client, title="Revision Book", pages=2)
    old_pdf = book["pdf_filename"]

    token = csrf(client, f"/admin/books/{book['id']}/edit")
    resp = client.post(
        f"/admin/books/{book['id']}/edit",
        data={
            "csrf_token": token,
            "title": "Revision Book",
            "author": "Author X",
            "category": "Testing",
            "language": "English",
            "description": "",
            "published": "1",
            "pdf": (io.BytesIO(make_pdf_bytes(5, "Revision Book v2")), "v2.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302

    with app.app_context():
        row = db.get_book(book["id"])
        assert row["page_count"] == 5
        revs = db.list_revisions(book["id"])
        assert len(revs) == 1 and revs[0]["pdf_filename"] == old_pdf
        # the old file is STILL on disk (recoverable)
        assert (STORAGE_DIR / "pdfs" / old_pdf).exists()

    # edit page shows the revision
    html = client.get(f"/admin/books/{book['id']}/edit").get_data(as_text=True)
    assert "Previous PDF versions" in html

    # restore the old version: swap back to 2 pages
    with app.app_context():
        rev_id = db.list_revisions(book["id"])[0]["id"]
    token = csrf(client, f"/admin/books/{book['id']}/edit")
    resp = client.post(
        f"/admin/books/{book['id']}/revisions/{rev_id}/restore",
        data={"csrf_token": token},
    )
    assert resp.status_code == 302
    with app.app_context():
        row = db.get_book(book["id"])
        assert row["page_count"] == 2
        assert row["pdf_filename"] == old_pdf


def test_r2_bulk_probe_requires_auth_and_csrf(app):
    anon = app.test_client()
    assert anon.get("/admin/books/bulk").status_code == 302
    assert anon.get("/admin/backup").status_code == 302
    assert anon.get("/admin/audit").status_code == 302
    assert anon.get("/admin/trash").status_code == 302
    assert anon.post("/admin/books/1/pin", data={"csrf_token": "x"}).status_code == 403
    assert anon.post("/admin/api/probe-pdf", data={"csrf_token": "x"}).status_code == 403


def test_search_still_finds_metadata(client, app):
    """Metadata search must keep working alongside PDF full-text search."""
    login(client)
    create_book(client, title="UniqueTitleWord", author="UniqueAuthorWord", category="UniqueCatWord")
    for term in ("UniqueTitleWord", "UniqueAuthorWord", "UniqueCatWord"):
        resp = client.get(f"/catalogue?q={term}")
        assert "UniqueTitleWord" in resp.get_data(as_text=True), f"metadata search failed for {term}"
