"""Tests for Round 3: About/Contact pages + message inbox, share previews,
PWA manifest, citation & print, accessibility meta, themes, RTL font."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from idl import create_app, db, security  # noqa: E402  (conftest sets paths)

ADMIN_USER = "testadmin"
ADMIN_PASS = "correct-horse-battery-staple"


def login(client):
    page = client.get("/admin/login", follow_redirects=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    resp = client.post(
        "/admin/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS, "csrf_token": match.group(1)},
    )
    assert resp.status_code == 302
    return client


def csrf_from(html):
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match
    return match.group(1)


def test_about_page(client):
    resp = client.get("/about")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Our mission" in html
    assert "Suggest a book" in html
    assert "free public library" in html.lower()


def test_contact_page_and_submission(client, app):
    # GET shows the form
    resp = client.get("/contact")
    assert resp.status_code == 200
    assert "Write to the library" in resp.get_data(as_text=True)

    # empty message rejected
    resp = client.post(
        "/contact",
        data={"csrf_token": csrf_from(resp.get_data(as_text=True)), "message": ""},
    )
    assert resp.status_code == 400

    # valid message is stored (real persistence)
    html = client.get("/contact").get_data(as_text=True)
    resp = client.post(
        "/contact",
        data={
            "csrf_token": csrf_from(html),
            "name": "Test Visitor",
            "email": "visitor@example.com",
            "subject": "Book suggestion",
            "message": "Please add Kitab al-Tawhid to the catalogue.",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Thank you" in resp.get_data(as_text=True)
    with app.app_context():
        messages = db.list_messages()
        assert any(
            m["message"].startswith("Please add Kitab") and m["email"] == "visitor@example.com"
            for m in messages
        )


def test_contact_rate_limit(client):
    from idl import security as sec

    key = f"contact|{client.get('/contact').request.environ.get('REMOTE_ADDR', '127.0.0.1')}"
    sec.clear_login_failures(key)
    # exceed the 5/hour window
    for _ in range(5):
        html = client.get("/contact").get_data(as_text=True)
        client.post(
            "/contact",
            data={"csrf_token": csrf_from(html), "message": "spam message number"},
        )
    html = client.get("/contact").get_data(as_text=True)
    resp = client.post(
        "/contact",
        data={"csrf_token": csrf_from(html), "message": "one message too many"},
    )
    assert resp.status_code == 429
    sec.clear_login_failures(key)


def test_admin_message_inbox(client, app):
    login(client)
    # send a visitor message first (anonymous client)
    anon = app.test_client()
    html = anon.get("/contact").get_data(as_text=True)
    anon.post(
        "/contact",
        data={
            "csrf_token": csrf_from(html),
            "name": "Inbox Tester",
            "subject": "Broken file",
            "message": "The PDF on page 2 does not open.",
        },
    )

    html = client.get("/admin/messages").get_data(as_text=True)
    assert "Inbox Tester" in html
    assert "does not open" in html
    assert "New" in html

    with app.app_context():
        msg_id = db.list_messages()[0]["id"]
    token = csrf_from(html)
    resp = client.post(f"/admin/messages/{msg_id}/read", data={"csrf_token": token})
    assert resp.status_code == 302
    assert "Read" in client.get("/admin/messages").get_data(as_text=True)

    token = csrf_from(client.get("/admin/messages").get_data(as_text=True))
    resp = client.post(f"/admin/messages/{msg_id}/delete", data={"csrf_token": token})
    assert resp.status_code == 302
    with app.app_context():
        assert db.get_message(msg_id) is None


def test_share_previews_and_pwa_meta(client):
    html = client.get("/").get_data(as_text=True)
    assert 'property="og:title"' in html
    assert 'property="og:image"' in html
    assert "share-card.png" in html
    assert 'name="twitter:card"' in html
    assert 'rel="manifest"' in html
    assert 'name="theme-color"' in html

    resp = client.get("/static/manifest.json")
    assert resp.status_code == 200
    import json

    manifest = json.loads(resp.get_data(as_text=True))
    assert manifest["name"].startswith("Maktaba")
    assert any(icon["sizes"] == "512x512" for icon in manifest["icons"])

    for icon in ("icon-180.png", "icon-192.png", "icon-512.png", "share-card.png"):
        assert client.get(f"/static/img/{icon}").status_code == 200


def test_book_share_meta_uses_cover(client, app):
    from idl import db as _db

    with app.app_context():
        books, _ = _db.list_books(limit=1)
        book_id = books[0]["id"]
    html = client.get(f"/books/{book_id}").get_data(as_text=True)
    assert 'property="og:type" content="book"' in html
    assert f"/books/{book_id}/cover" in html


def test_citation_block_and_print_button(client, app):
    with app.app_context():
        books, _ = db.list_books(limit=1)
        book = books[0]
        book_id = book["id"]
    html = client.get(f"/books/{book_id}").get_data(as_text=True)
    assert "How to cite this book" in html
    assert "Chicago style" in html
    assert "Maktaba — Islamic Digital Library" in html  # citation string
    assert 'id="print-btn"' in html


def test_accessibility_meta(client):
    html = client.get("/").get_data(as_text=True)
    assert '<html lang="en">' in html
    assert 'class="skip-link"' in html
    assert 'aria-live="polite"' in html
    assert 'aria-label="Main"' in html
    assert '<main id="main">' in html


def test_themes_css_and_font_bundled(client):
    css = client.get("/static/css/style.css").get_data(as_text=True)
    assert '[data-theme="dark"]' in css
    assert '[data-theme="warm"]' in css
    assert "@media print" in css
    assert "NotoNaskhArabic.ttf" in css

    theme_js = client.get("/static/js/theme.js").get_data(as_text=True)
    assert "maktaba:theme" in theme_js

    assert client.get("/static/fonts/NotoNaskhArabic.ttf").status_code == 200
    assert client.get("/static/js/sw.js").status_code == 200


def test_about_and_contact_in_nav_footer(client):
    html = client.get("/").get_data(as_text=True)
    assert html.count('href="/about"') >= 2   # nav + footer
    assert html.count('href="/contact"') >= 1
