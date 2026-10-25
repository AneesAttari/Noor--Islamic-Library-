"""Admin routes: authentication and library management.

Every mutating route runs three checks on the backend:
  1. CSRF token validation,
  2. session authentication against the admins table,
  3. explicit parameterized SQL scoped by book id.
"""
from __future__ import annotations

from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from . import db, security, storage
from .security import admin_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _csrf_protect(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        security.csrf_protect()
        return view(*args, **kwargs)

    return wrapped


def _form_bool(name: str) -> bool:
    return request.form.get(name) in ("1", "on", "true", "yes")


def _clean_text(name: str, max_len: int, required: bool = False) -> str:
    value = (request.form.get(name) or "").strip()
    if required and not value:
        raise ValueError(f"{name.capitalize()} is required.")
    return value[:max_len]


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if security.current_admin() is not None:
        return redirect(url_for("admin.dashboard"))

    if request.method == "POST":
        security.csrf_protect()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        key = f"{request.remote_addr}|{username.lower()}"

        if security.login_blocked(key):
            flash("Too many failed attempts. Please wait 15 minutes and try again.", "error")
            return render_template("admin/login.html", username=username), 429

        admin = db.get_admin_by_username(username) if username else None
        if (
            admin is not None
            and password
            and security.verify_password(admin["password_hash"], password)
        ):
            if security.password_needs_rehash(admin["password_hash"]):
                db.update_admin_password(admin["id"], security.hash_password(password))
            security.clear_login_failures(key)
            security.login_admin(admin["id"])
            target = request.args.get("next") or url_for("admin.dashboard")
            if not target.startswith("/"):
                target = url_for("admin.dashboard")
            return redirect(target)

        security.record_login_failure(key)
        flash("Invalid username or password.", "error")
        return render_template("admin/login.html", username=username), 401

    return render_template("admin/login.html", username="")


@bp.route("/logout", methods=["POST"])
@_csrf_protect
def logout():
    security.logout_admin()
    flash("You have been signed out.", "success")
    return redirect(url_for("public.index"))


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------

@bp.route("/")
@admin_required
def dashboard():
    books, _ = db.list_books(sort="newest", published_only=False, page=1, per_page=100)
    return render_template(
        "admin/dashboard.html",
        books=books,
        stats=db.stats(),
    )


# --------------------------------------------------------------------------
# book CRUD
# --------------------------------------------------------------------------

@bp.route("/books/new", methods=["GET", "POST"])
@admin_required
@_csrf_protect
def book_new():
    if request.method == "GET":
        return render_template("admin/book_form.html", book=None, mode="new")

    try:
        title = _clean_text("title", 300, required=True)
        author = _clean_text("author", 200, required=True)
        category = _clean_text("category", 100, required=True)
        language = _clean_text("language", 60, required=True) or "English"
        description = _clean_text("description", 5000)
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("admin/book_form.html", book=None, mode="new"), 400

    try:
        pdf_name, pdf_size, page_count = storage.validate_and_save_pdf(request.files.get("pdf"))
    except storage.UploadError as exc:
        flash(f"PDF upload failed: {exc}", "error")
        return render_template("admin/book_form.html", book=None, mode="new"), 400

    cover_name = None
    cover_upload = request.files.get("cover")
    if cover_upload is not None and cover_upload.filename:
        try:
            cover_name = storage.validate_and_save_cover(cover_upload)
        except storage.UploadError as exc:
            storage.delete_pdf(pdf_name)
            flash(f"Cover upload failed: {exc}", "error")
            return render_template("admin/book_form.html", book=None, mode="new"), 400

    book_id = db.insert_book(
        {
            "title": title,
            "author": author,
            "description": description,
            "category": category,
            "language": language,
            "pdf_filename": pdf_name,
            "pdf_size": pdf_size,
            "page_count": page_count,
            "cover_filename": cover_name,
            "featured": _form_bool("featured"),
            "published": _form_bool("published"),
        }
    )
    flash("Book added successfully.", "success")
    return redirect(url_for("admin.book_edit", book_id=book_id))


@bp.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
@admin_required
@_csrf_protect
def book_edit(book_id: int):
    book = db.get_book(book_id, published_only=False)
    if book is None:
        abort(404)

    if request.method == "GET":
        return render_template("admin/book_form.html", book=book, mode="edit")

    try:
        title = _clean_text("title", 300, required=True)
        author = _clean_text("author", 200, required=True)
        category = _clean_text("category", 100, required=True)
        language = _clean_text("language", 60, required=True) or "English"
        description = _clean_text("description", 5000)
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("admin/book_form.html", book=book, mode="edit"), 400

    # Optional PDF replacement — only touches storage after validation.
    pdf_upload = request.files.get("pdf")
    if pdf_upload is not None and pdf_upload.filename:
        try:
            new_name, new_size, new_pages = storage.validate_and_save_pdf(pdf_upload)
        except storage.UploadError as exc:
            flash(f"PDF upload failed: {exc}", "error")
            return render_template("admin/book_form.html", book=book, mode="edit"), 400
        old = book["pdf_filename"]
        db.replace_book_pdf(book_id, new_name, new_size, new_pages)
        storage.delete_pdf(old)

    cover_upload = request.files.get("cover")
    if cover_upload is not None and cover_upload.filename:
        try:
            new_cover = storage.validate_and_save_cover(cover_upload)
        except storage.UploadError as exc:
            flash(f"Cover upload failed: {exc}", "error")
            return render_template("admin/book_form.html", book=book, mode="edit"), 400
        old_cover = book["cover_filename"]
        db.set_book_cover(book_id, new_cover)
        storage.delete_cover(old_cover)
    elif _form_bool("remove_cover") and book["cover_filename"]:
        storage.delete_cover(book["cover_filename"])
        db.set_book_cover(book_id, None)

    db.update_book(
        book_id,
        {
            "title": title,
            "author": author,
            "description": description,
            "category": category,
            "language": language,
            "featured": _form_bool("featured"),
            "published": _form_bool("published"),
        },
    )
    flash("Book updated successfully.", "success")
    return redirect(url_for("admin.book_edit", book_id=book_id))


@bp.route("/books/<int:book_id>/publish", methods=["POST"])
@admin_required
@_csrf_protect
def book_publish(book_id: int):
    book = db.get_book(book_id, published_only=False)
    if book is None:
        abort(404)
    make_published = (request.form.get("value") or "1") == "1"
    db.set_published(book_id, make_published)
    flash(
        "Book published." if make_published else "Book unpublished (hidden from visitors).",
        "success",
    )
    return redirect(request.form.get("next") or url_for("admin.dashboard"))


@bp.route("/books/<int:book_id>/delete", methods=["POST"])
@admin_required
@_csrf_protect
def book_delete(book_id: int):
    row = db.delete_book(book_id)
    if row is None:
        abort(404)
    storage.delete_pdf(row["pdf_filename"])
    storage.delete_cover(row["cover_filename"])
    flash(f"“{row['title']}” was deleted, including its stored files.", "success")
    return redirect(url_for("admin.dashboard"))
