"""Public (visitor) routes: home, catalogue, search, book detail, PDF reader."""
from __future__ import annotations

import re
from datetime import datetime

from flask import (
    Blueprint,
    Response,
    abort,
    render_template,
    request,
    send_file,
)

from . import config, db, storage
from .covers import render_cover_svg
from .security import current_admin, ensure_csrf_token

bp = Blueprint("public", __name__)

_ARABIC_RE = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
)


def _is_admin() -> bool:
    return current_admin() is not None


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

@bp.route("/")
def index():
    featured = db.featured_ordered()[:6]
    recent, _ = db.list_books(sort="newest", published_only=True, limit=8)
    popular = db.popular_books(days=30, limit=6)
    categories = db.category_counts()
    stats = db.stats()
    stats["languages"] = len(db.language_counts())
    return render_template(
        "index.html",
        featured=featured,
        recent=recent,
        popular=popular,
        categories=categories,
        stats=stats,
    )


@bp.route("/catalogue")
def catalogue():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    language = request.args.get("language", "").strip()
    sort = request.args.get("sort", "newest")
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    per_page = 12
    books, total = db.list_books(
        q=q,
        category=category,
        language=language,
        sort=sort if sort in db.VALID_SORTS else "newest",
        page=page,
        per_page=per_page,
        published_only=not _is_admin(),
    )
    total_pages = db.page_count(total, per_page)
    if page > total_pages and total_pages > 1:
        return abort(404)

    return render_template(
        "catalogue.html",
        books=books,
        total=total,
        page=page,
        total_pages=total_pages,
        q=q,
        category=category,
        language=language,
        sort=sort,
        categories=db.category_counts(),
        languages=db.language_counts(),
    )


@bp.route("/categories")
def categories():
    return render_template(
        "categories.html",
        categories=db.category_counts(),
        languages=db.language_counts(),
    )


@bp.route("/books/<int:book_id>")
def book_detail(book_id: int):
    book = db.get_book(book_id, published_only=not _is_admin())
    if book is None:
        abort(404)
    related = db.related_books(book)
    return render_template("book_detail.html", book=book, related=related)


@bp.route("/books/<int:book_id>/read")
def read(book_id: int):
    book = db.get_book(book_id, published_only=not _is_admin())
    if book is None:
        abort(404)
    if not _is_admin():
        db.record_event(book_id, "read")
    return render_template("reader.html", book=book)


# --------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------

@bp.route("/books/<int:book_id>/pdf")
def book_pdf(book_id: int):
    book = db.get_book(book_id, published_only=not _is_admin())
    if book is None:
        abort(404)
    try:
        path = storage.pdf_path(book["pdf_filename"])
    except storage.UploadError:
        abort(404)
    if not path.is_file():
        abort(404)

    download = request.args.get("download") == "1"
    if download and not _is_admin():
        db.record_event(book_id, "download")
    safe_name = _download_name(book)
    resp = send_file(
        path,
        mimetype="application/pdf",
        as_attachment=download,
        download_name=safe_name,
        conditional=True,
        max_age=0,
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@bp.route("/books/<int:book_id>/cover")
def book_cover(book_id: int):
    book = db.get_book(book_id, published_only=not _is_admin())
    if book is None:
        abort(404)

    if book["cover_filename"]:
        try:
            path = storage.cover_path(book["cover_filename"])
        except storage.UploadError:
            path = None
        if path is not None and path.is_file():
            resp = send_file(path, mimetype="image/jpeg", conditional=True, max_age=3600)
            resp.headers["X-Content-Type-Options"] = "nosniff"
            return resp

    svg = render_cover_svg(book["title"], book["author"], book["category"])
    return Response(
        svg,
        mimetype="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


@bp.route("/books/<int:book_id>/preview")
def book_preview(book_id: int):
    """First-page thumbnail rendered from the actual PDF."""
    book = db.get_book(book_id, published_only=not _is_admin())
    if book is None or not book["preview_filename"]:
        abort(404)
    try:
        path = storage.preview_path(book["preview_filename"])
    except storage.UploadError:
        abort(404)
    if not path.is_file():
        abort(404)
    resp = send_file(path, mimetype="image/jpeg", conditional=True, max_age=3600)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@bp.route("/healthz")
def healthz():
    return {"status": "ok", "books": db.stats()["total"]}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _download_name(book) -> str:
    stem = "".join(c if c.isalnum() or c in " -_" else "_" for c in book["title"])[:80].strip()
    stem = "-".join(stem.split()) or f"book-{book['id']}"
    return f"{stem}.pdf"


@bp.app_template_filter("humandate")
def humandate(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%d %B %Y").lstrip("0")
    except (ValueError, TypeError):
        return value


@bp.app_template_filter("humansize")
def humansize(num) -> str:
    try:
        size = float(num)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


@bp.app_template_filter("textdir")
def textdir(value: str) -> str:
    """'rtl' when the text contains Arabic-script characters, else 'ltr'."""
    return "rtl" if value and _ARABIC_RE.search(value) else "ltr"


@bp.app_context_processor
def inject_globals():
    return {
        "app_name": config.APP_NAME,
        "app_tagline": config.APP_TAGLINE,
        "nav_categories": [row["category"] for row in db.category_counts()[:6]],
        "csrf_token": ensure_csrf_token,
    }
