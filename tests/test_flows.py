"""End-to-end flow tests for the Islamic Digital Library.

These tests exercise the real application: real SQLite rows, real files on
disk, real session cookies. Run with:  python -m pytest tests/ -v

They cover:
  * public browsing / search / detail / reader
  * PDF streaming incl. unpublished protection
  * admin login, throttling, CSRF
  * add / edit / publish / delete with real file storage
  * rejection of invalid uploads
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas as pdf_canvas

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Point the app at a throwaway data directory before importing it.
import os

from idl import config, create_app, db, security  # noqa: E402

TEST_ROOT = Path(__file__).resolve().parent / "_tmp_data"
STORAGE_DIR = config.STORAGE_DIR

ADMIN_USER = "testadmin"
ADMIN_PASS = "correct-horse-battery-staple"


def make_pdf_bytes(pages: int = 2, title: str = "Test Book") -> bytes:
    buffer = io.BytesIO()
    c = pdf_canvas.Canvas(buffer)
    for i in range(pages):
        c.drawString(72, 720, f"{title} — page {i + 1}")
        c.showPage()
    c.save()
    return buffer.getvalue()


def make_image_bytes(size=(400, 600)) -> bytes:
    from PIL import Image

    img = Image.new("RGB", size, (30, 90, 70))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def app():
    if TEST_ROOT.exists():
        import shutil

        shutil.rmtree(TEST_ROOT)
    application = create_app()
    application.config["TESTING"] = True
    with application.app_context():
        db.ensure_schema()
        db.create_admin(ADMIN_USER, security.hash_password(ADMIN_PASS))
    return application


@pytest.fixture(scope="session")
def seeded_book_id(app):
    """Create one published book through the real storage pipeline."""
    with app.app_context():
        from werkzeug.datastructures import FileStorage

        from idl import storage

        name, size, pages = storage.validate_and_save_pdf(
            FileStorage(stream=io.BytesIO(make_pdf_bytes(3, "Seeded")), filename="seed.pdf")
        )
        return db.insert_book(
            {
                "title": "Seeded Book on Prayer",
                "author": "Test Author",
                "description": "A seeded book used by the test suite.",
                "category": "Worship",
                "language": "English",
                "pdf_filename": name,
                "pdf_size": size,
                "page_count": pages,
                "cover_filename": None,
                "featured": True,
                "published": True,
            }
        )


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username=ADMIN_USER, password=ADMIN_PASS, csrf=None):
    if csrf is None:
        page = client.get("/admin/login", follow_redirects=True)
        match = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
        csrf = match.group(1)
    return client.post(
        "/admin/login",
        data={"username": username, "password": password, "csrf_token": csrf},
    )


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF token missing from form"
    return match.group(1)


# ==========================================================================
# public browsing
# ==========================================================================

def test_home_page_lists_books(client, seeded_book_id):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Seeded Book on Prayer" in html
    assert "Search library" in html or "Search" in html


def test_catalogue_lists_and_searches(client, seeded_book_id):
    resp = client.get("/catalogue")
    assert resp.status_code == 200
    assert "Seeded Book on Prayer" in resp.get_data(as_text=True)

    # search by title
    resp = client.get("/catalogue?q=Prayer")
    assert "Seeded Book on Prayer" in resp.get_data(as_text=True)

    # search by author
    resp = client.get("/catalogue?q=Test+Author")
    assert "Seeded Book on Prayer" in resp.get_data(as_text=True)

    # search by category
    resp = client.get("/catalogue?q=Worship")
    assert "Seeded Book on Prayer" in resp.get_data(as_text=True)

    # empty result state
    resp = client.get("/catalogue?q=zzzznotfoundzzzz")
    assert resp.status_code == 200
    assert "No books found" in resp.get_data(as_text=True)


def test_search_by_category_filter(client, seeded_book_id):
    resp = client.get("/catalogue?category=Worship")
    assert "Seeded Book on Prayer" in resp.get_data(as_text=True)
    resp = client.get("/catalogue?category=Nonexistent")
    assert "No books found" in resp.get_data(as_text=True)


def test_book_detail_page(client, seeded_book_id):
    resp = client.get(f"/books/{seeded_book_id}")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Seeded Book on Prayer" in html
    assert "Test Author" in html
    assert "Read online" in html
    assert "Download PDF" in html


def test_reader_page(client, seeded_book_id):
    resp = client.get(f"/books/{seeded_book_id}/read")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "pdf.min.js" in html
    assert "reader.js" in html
    assert f"/books/{seeded_book_id}/pdf" in html


def test_pdf_streaming(client, seeded_book_id):
    resp = client.get(f"/books/{seeded_book_id}/pdf")
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")
    assert resp.headers["Content-Type"].startswith("application/pdf")

    # range request support (used by the reader for large files)
    resp = client.get(f"/books/{seeded_book_id}/pdf", headers={"Range": "bytes=0-99"})
    assert resp.status_code == 206
    assert len(resp.data) == 100


def test_cover_endpoint_generates_svg(client, seeded_book_id):
    resp = client.get(f"/books/{seeded_book_id}/cover")
    assert resp.status_code == 200
    assert b"<svg" in resp.data


def test_missing_book_404(client):
    resp = client.get("/books/99999")
    assert resp.status_code == 404


# ==========================================================================
# unpublished protection
# ==========================================================================

def test_unpublished_invisible_to_public(client, app):
    with app.app_context():
        from werkzeug.datastructures import FileStorage

        from idl import storage

        name, size, pages = storage.validate_and_save_pdf(
            FileStorage(stream=io.BytesIO(make_pdf_bytes(1, "Hidden")), filename="hidden.pdf")
        )
        book_id = db.insert_book(
            {
                "title": "Hidden Unpublished Book",
                "author": "Nobody",
                "description": "",
                "category": "Test",
                "language": "English",
                "pdf_filename": name,
                "pdf_size": size,
                "page_count": pages,
                "cover_filename": None,
                "featured": False,
                "published": False,
            }
        )

    # not in catalogue
    assert "Hidden Unpublished Book" not in client.get("/catalogue").get_data(as_text=True)
    # detail page 404 for visitors
    assert client.get(f"/books/{book_id}").status_code == 404
    # PDF not downloadable for visitors
    assert client.get(f"/books/{book_id}/pdf").status_code == 404
    # reader page blocked for visitors
    assert client.get(f"/books/{book_id}/read").status_code == 404

    # ...but an authenticated admin can see it
    login(client)
    assert client.get(f"/books/{book_id}").status_code == 200
    resp = client.get(f"/books/{book_id}/pdf")
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF-")


# ==========================================================================
# admin auth
# ==========================================================================

def test_admin_requires_login(client):
    resp = client.get("/admin/")
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["Location"]

    resp = client.post("/admin/books/1/delete", data={"csrf_token": "x"})
    assert resp.status_code == 403


def test_login_wrong_password(client):
    resp = login(client, password="wrong-password")
    assert resp.status_code == 401
    assert "Invalid username or password" in resp.get_data(as_text=True)
    # session must not grant access
    assert client.get("/admin/").status_code == 302


def test_login_wrong_csrf(client):
    resp = login(client, csrf="forged-token")
    assert resp.status_code == 403


def test_login_success_and_logout(client):
    resp = login(client)
    assert resp.status_code == 302
    assert "/admin/" in resp.headers["Location"]

    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert "Library dashboard" in resp.get_data(as_text=True)

    # logout requires CSRF
    html = client.get("/admin/").get_data(as_text=True)
    token = csrf_from(html)
    resp = client.post("/admin/logout", data={"csrf_token": token})
    assert resp.status_code == 302
    assert client.get("/admin/").status_code == 302


def test_login_rate_limiting(client):
    from idl import security as sec

    key = "127.0.0.1|ratelimit-user"
    sec.clear_login_failures(key)
    for _ in range(sec.config.LOGIN_RATE_LIMIT):
        login(client, username="ratelimit-user", password="nope")
    resp = login(client, username="ratelimit-user", password="nope")
    assert resp.status_code == 429
    sec.clear_login_failures(key)


# ==========================================================================
# admin CRUD with real storage
# ==========================================================================

def _admin_csrf(client) -> str:
    return csrf_from(client.get("/admin/books/new").get_data(as_text=True))


def test_add_book_upload_and_visibility(client, app):
    login(client)
    token = _admin_csrf(client)

    pdf_bytes = make_pdf_bytes(4, "Uploaded")
    resp = client.post(
        "/admin/books/new",
        data={
            "csrf_token": token,
            "title": "Uploaded Book of Adab",
            "author": "Test Author",
            "category": "Islamic Education",
            "language": "English",
            "description": "Uploaded by the test suite through the real form.",
            "published": "1",
            "featured": "1",
            "pdf": (io.BytesIO(pdf_bytes), "adab.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302

    with app.app_context():
        rows, _ = db.list_books(q="Uploaded Book of Adab", published_only=False)
        assert len(rows) == 1
        book = rows[0]
        book_id = book["id"]
        # real file exists and is a real PDF
        pdf_file = STORAGE_DIR / "pdfs" / book["pdf_filename"]
        assert pdf_file.is_file()
        assert pdf_file.read_bytes().startswith(b"%PDF-")
        assert book["page_count"] == 4
        assert book["published"] == 1

    # visible to visitors now
    assert "Uploaded Book of Adab" in client.get("/catalogue").get_data(as_text=True)
    resp = client.get(f"/books/{book_id}/pdf")
    assert resp.status_code == 200 and resp.data.startswith(b"%PDF-")


def test_add_book_with_cover(client, app):
    login(client)
    token = _admin_csrf(client)
    resp = client.post(
        "/admin/books/new",
        data={
            "csrf_token": token,
            "title": "Book With Cover",
            "author": "Cover Author",
            "category": "Reference",
            "language": "English",
            "description": "",
            "published": "1",
            "pdf": (io.BytesIO(make_pdf_bytes(1)), "c.pdf"),
            "cover": (io.BytesIO(make_image_bytes()), "cover.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302

    with app.app_context():
        rows, _ = db.list_books(q="Book With Cover", published_only=False)
        book = rows[0]
        cover_file = STORAGE_DIR / "covers" / book["cover_filename"]
        assert cover_file.is_file()

    resp = client.get(f"/books/{book['id']}/cover")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("image/jpeg")


def test_invalid_upload_rejected(client, app):
    login(client)
    token = _admin_csrf(client)

    # a text file pretending to be a PDF
    resp = client.post(
        "/admin/books/new",
        data={
            "csrf_token": token,
            "title": "Bad Book",
            "author": "A",
            "category": "Test",
            "language": "English",
            "published": "1",
            "pdf": (io.BytesIO(b"this is not a pdf at all"), "fake.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "PDF upload failed" in resp.get_data(as_text=True)

    with app.app_context():
        rows, _ = db.list_books(q="Bad Book", published_only=False)
        assert rows == []

    # wrong extension
    resp = client.post(
        "/admin/books/new",
        data={
            "csrf_token": token,
            "title": "Bad Book 2",
            "author": "A",
            "category": "Test",
            "language": "English",
            "published": "1",
            "pdf": (io.BytesIO(make_pdf_bytes(1)), "malware.exe"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400

    # missing PDF on create
    resp = client.post(
        "/admin/books/new",
        data={
            "csrf_token": token,
            "title": "Bad Book 3",
            "author": "A",
            "category": "Test",
            "language": "English",
            "published": "1",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_edit_and_unpublish(client, app, seeded_book_id):
    login(client)
    resp = client.get(f"/admin/books/{seeded_book_id}/edit")
    token = csrf_from(resp.get_data(as_text=True))

    resp = client.post(
        f"/admin/books/{seeded_book_id}/edit",
        data={
            "csrf_token": token,
            "title": "Seeded Book on Prayer (Revised)",
            "author": "Test Author",
            "category": "Worship",
            "language": "English",
            "description": "Edited description.",
            "published": "1",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302

    resp = client.get(f"/books/{seeded_book_id}")
    assert "Seeded Book on Prayer (Revised)" in resp.get_data(as_text=True)
    assert "Edited description." in resp.get_data(as_text=True)

    # unpublish via the publish toggle
    html = client.get("/admin/").get_data(as_text=True)
    token = csrf_from(html)
    resp = client.post(
        f"/admin/books/{seeded_book_id}/publish",
        data={"csrf_token": token, "value": "0"},
    )
    assert resp.status_code == 302

    # gone for visitors, still there for admin
    anon = app.test_client()
    assert anon.get(f"/books/{seeded_book_id}").status_code == 404
    assert anon.get(f"/books/{seeded_book_id}/pdf").status_code == 404
    assert client.get(f"/books/{seeded_book_id}").status_code == 200

    # re-publish for later tests
    html = client.get("/admin/").get_data(as_text=True)
    token = csrf_from(html)
    client.post(
        f"/admin/books/{seeded_book_id}/publish",
        data={"csrf_token": token, "value": "1"},
    )


def test_replace_pdf_on_edit(client, app):
    login(client)
    token = _admin_csrf(client)
    resp = client.post(
        "/admin/books/new",
        data={
            "csrf_token": token,
            "title": "Replaceable PDF",
            "author": "A",
            "category": "Test",
            "language": "English",
            "published": "1",
            "pdf": (io.BytesIO(make_pdf_bytes(2, "Original")), "orig.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302
    with app.app_context():
        rows, _ = db.list_books(q="Replaceable PDF", published_only=False)
        book = rows[0]
        book_id = book["id"]
        old_file = book["pdf_filename"]

    html = client.get(f"/admin/books/{book_id}/edit").get_data(as_text=True)
    token = csrf_from(html)
    resp = client.post(
        f"/admin/books/{book_id}/edit",
        data={
            "csrf_token": token,
            "title": "Replaceable PDF",
            "author": "A",
            "category": "Test",
            "language": "English",
            "description": "",
            "published": "1",
            "pdf": (io.BytesIO(make_pdf_bytes(5, "Second")), "new.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302

    with app.app_context():
        rows, _ = db.list_books(q="Replaceable PDF", published_only=False)
        book = rows[0]
        assert book["page_count"] == 5
        assert book["pdf_filename"] != old_file
        # the old file is kept on disk as a recoverable revision
        assert (STORAGE_DIR / "pdfs" / old_file).exists()
        assert (STORAGE_DIR / "pdfs" / book["pdf_filename"]).exists()
        revs = db.list_revisions(book_id)
        assert len(revs) == 1 and revs[0]["pdf_filename"] == old_file


def test_delete_book_goes_to_trash_then_purge_removes_files(client, app):
    login(client)
    token = _admin_csrf(client)
    resp = client.post(
        "/admin/books/new",
        data={
            "csrf_token": token,
            "title": "Doomed Book",
            "author": "A",
            "category": "Test",
            "language": "English",
            "published": "1",
            "pdf": (io.BytesIO(make_pdf_bytes(1)), "d.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 302
    with app.app_context():
        rows, _ = db.list_books(q="Doomed Book", published_only=False)
        book = rows[0]
        book_id = book["id"]
        pdf_file = STORAGE_DIR / "pdfs" / book["pdf_filename"]
        assert pdf_file.exists()

    html = client.get("/admin/").get_data(as_text=True)
    token = csrf_from(html)
    resp = client.post(f"/admin/books/{book_id}/delete", data={"csrf_token": token})
    assert resp.status_code == 302

    # soft delete: hidden from everyone, but files and row remain in trash
    assert client.get(f"/books/{book_id}").status_code == 404
    assert pdf_file.exists()
    with app.app_context():
        row = db.get_book(book_id, published_only=False, include_deleted=True)
        assert row is not None and row["deleted_at"] is not None

    # trash page lists it; restore brings it back
    trash_html = client.get("/admin/trash").get_data(as_text=True)
    assert "Doomed Book" in trash_html
    resp = client.post(f"/admin/books/{book_id}/restore", data={"csrf_token": token})
    assert resp.status_code == 302
    assert client.get(f"/books/{book_id}").status_code == 200

    # trash again, then purge forever: files and row are gone
    client.post(f"/admin/books/{book_id}/delete", data={"csrf_token": token})
    resp = client.post(f"/admin/books/{book_id}/purge", data={"csrf_token": token})
    assert resp.status_code == 302
    assert not pdf_file.exists()
    assert client.get(f"/books/{book_id}").status_code == 404
    with app.app_context():
        assert db.get_book(book_id, published_only=False, include_deleted=True) is None


def test_mutations_reject_missing_csrf(client, app, seeded_book_id):
    login(client)
    resp = client.post(
        f"/admin/books/{seeded_book_id}/publish",
        data={"value": "0"},
    )
    assert resp.status_code == 403
    with app.app_context():
        assert db.get_book(seeded_book_id, published_only=False)["published"] == 1


def test_admin_password_not_in_client_code(client):
    """No secrets leak into served HTML/JS/CSS."""
    for path in ("/", "/admin/login", "/catalogue", "/static/js/main.js", "/static/js/reader.js"):
        body = client.get(path).get_data(as_text=True)
        assert ADMIN_PASS not in body
        assert "password_hash" not in body
        assert "argon2" not in body.lower()


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
