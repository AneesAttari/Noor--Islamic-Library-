"""Admin routes: authentication and library management.

Every mutating route runs three checks on the backend:
  1. CSRF token validation,
  2. session authentication against the admins table,
  3. explicit parameterized SQL scoped by book id.
All data changes are recorded in the audit log. Deletes go to Trash first;
files are only removed on permanent deletion.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from functools import wraps

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from . import config, db, security, storage
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


def _audit(action: str, book_id=None, detail: str = "") -> None:
    from .security import current_admin

    admin = current_admin()
    db.audit(
        action,
        admin_username=admin["username"] if admin else "",
        book_id=book_id,
        detail=detail,
        admin_id=admin["id"] if admin else None,
    )


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
            _audit("login")
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
    _audit("logout")
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
        featured_order=db.featured_ordered(),
    )


# --------------------------------------------------------------------------
# book CRUD
# --------------------------------------------------------------------------

@bp.route("/books/new", methods=["GET", "POST"])
@admin_required
@_csrf_protect
def book_new():
    if request.method == "GET":
        return render_template("admin/book_form.html", book=None, mode="new", revisions=[])

    try:
        title = _clean_text("title", 300, required=True)
        author = _clean_text("author", 200, required=True)
        category = _clean_text("category", 100, required=True)
        language = _clean_text("language", 60, required=True) or "English"
        description = _clean_text("description", 5000)
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("admin/book_form.html", book=None, mode="new", revisions=[]), 400

    try:
        pdf_name, pdf_size, page_count = storage.validate_and_save_pdf(request.files.get("pdf"))
    except storage.UploadError as exc:
        flash(f"PDF upload failed: {exc}", "error")
        return render_template("admin/book_form.html", book=None, mode="new", revisions=[]), 400

    cover_name = None
    cover_upload = request.files.get("cover")
    if cover_upload is not None and cover_upload.filename:
        try:
            cover_name = storage.validate_and_save_cover(cover_upload)
        except storage.UploadError as exc:
            storage.delete_pdf(pdf_name)
            flash(f"Cover upload failed: {exc}", "error")
            return render_template("admin/book_form.html", book=None, mode="new", revisions=[]), 400

    preview_name = storage.generate_preview(pdf_name)
    text = storage.extract_pdf_text(pdf_name)

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
            "preview_filename": preview_name,
            "featured": _form_bool("featured"),
            "published": _form_bool("published"),
        }
    )
    db.set_book_text(book_id, text)
    _audit("create", book_id=book_id, detail=f"“{title}” added ({page_count} pages)")
    flash("Book added successfully.", "success")
    return redirect(url_for("admin.book_edit", book_id=book_id))


@bp.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
@admin_required
@_csrf_protect
def book_edit(book_id: int):
    book = db.get_book(book_id, published_only=False, include_deleted=True)
    if book is None:
        abort(404)

    if request.method == "GET":
        return render_template(
            "admin/book_form.html", book=book, mode="edit",
            revisions=db.list_revisions(book_id),
        )

    try:
        title = _clean_text("title", 300, required=True)
        author = _clean_text("author", 200, required=True)
        category = _clean_text("category", 100, required=True)
        language = _clean_text("language", 60, required=True) or "English"
        description = _clean_text("description", 5000)
    except ValueError as exc:
        flash(str(exc), "error")
        return render_template("admin/book_form.html", book=book, mode="edit",
                               revisions=db.list_revisions(book_id)), 400

    pdf_upload = request.files.get("pdf")
    if pdf_upload is not None and pdf_upload.filename:
        try:
            new_name, new_size, new_pages = storage.validate_and_save_pdf(pdf_upload)
        except storage.UploadError as exc:
            flash(f"PDF upload failed: {exc}", "error")
            return render_template("admin/book_form.html", book=book, mode="edit",
                                   revisions=db.list_revisions(book_id)), 400
        # keep the previous file as a recoverable revision instead of deleting it
        db.add_revision(book_id, book["pdf_filename"], book["pdf_size"], book["page_count"])
        db.replace_book_pdf(book_id, new_name, new_size, new_pages)
        storage.delete_preview(book["preview_filename"])
        db.set_book_preview(book_id, storage.generate_preview(new_name))
        db.set_book_text(book_id, storage.extract_pdf_text(new_name))
        _audit("replace_pdf", book_id=book_id,
               detail=f"PDF replaced ({new_pages} pages); previous version kept as revision")

    cover_upload = request.files.get("cover")
    if cover_upload is not None and cover_upload.filename:
        try:
            new_cover = storage.validate_and_save_cover(cover_upload)
        except storage.UploadError as exc:
            flash(f"Cover upload failed: {exc}", "error")
            return render_template("admin/book_form.html", book=book, mode="edit",
                                   revisions=db.list_revisions(book_id)), 400
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
    _audit("edit", book_id=book_id, detail=f"“{title}” updated")
    flash("Book updated successfully.", "success")
    return redirect(url_for("admin.book_edit", book_id=book_id))


@bp.route("/books/<int:book_id>/publish", methods=["POST"])
@admin_required
@_csrf_protect
def book_publish(book_id: int):
    book = db.get_book(book_id, published_only=False, include_deleted=True)
    if book is None:
        abort(404)
    make_published = (request.form.get("value") or "1") == "1"
    db.set_published(book_id, make_published)
    _audit("publish" if make_published else "unpublish", book_id=book_id,
           detail=f"“{book['title']}”")
    flash(
        "Book published." if make_published else "Book unpublished (hidden from visitors).",
        "success",
    )
    return redirect(request.form.get("next") or url_for("admin.dashboard"))


@bp.route("/books/<int:book_id>/pin", methods=["POST"])
@admin_required
@_csrf_protect
def book_pin(book_id: int):
    book = db.get_book(book_id, published_only=False)
    if book is None:
        abort(404)
    action = request.form.get("action") or "top"
    if action == "unpin":
        db.pin_clear(book_id)
        _audit("unpin", book_id=book_id, detail=f"“{book['title']}”")
    elif action in ("up", "down", "top"):
        db.pin_move(book_id, action)
        _audit("pin", book_id=book_id, detail=f"“{book['title']}” moved ({action})")
    return redirect(url_for("admin.dashboard") + "#featured-order")


# --------------------------------------------------------------------------
# trash
# --------------------------------------------------------------------------

@bp.route("/books/<int:book_id>/delete", methods=["POST"])
@admin_required
@_csrf_protect
def book_delete(book_id: int):
    row = db.get_book(book_id, published_only=False)
    if row is None:
        abort(404)
    db.soft_delete_book(book_id)
    _audit("trash", book_id=book_id, detail=f"“{row['title']}” moved to trash")
    flash(
        f"“{row['title']}” moved to trash. Files are kept — restore it or "
        "delete it forever from the Trash page.",
        "success",
    )
    return redirect(url_for("admin.dashboard"))


@bp.route("/trash")
@admin_required
def trash():
    return render_template("admin/trash.html", books=db.list_trash())


@bp.route("/books/<int:book_id>/restore", methods=["POST"])
@admin_required
@_csrf_protect
def book_restore(book_id: int):
    row = db.get_book(book_id, published_only=False, include_deleted=True)
    if row is None or not row["deleted_at"]:
        abort(404)
    db.restore_book(book_id)
    _audit("restore", book_id=book_id, detail=f"“{row['title']}” restored from trash")
    flash(f"“{row['title']}” restored.", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/books/<int:book_id>/purge", methods=["POST"])
@admin_required
@_csrf_protect
def book_purge(book_id: int):
    row = db.get_book(book_id, published_only=False, include_deleted=True)
    if row is None:
        abort(404)
    # collect every stored file first, then delete row + files
    files = [row["pdf_filename"], row["cover_filename"], row["preview_filename"]]
    files += [rev["pdf_filename"] for rev in db.list_revisions(book_id)]
    db.purge_book(book_id)
    for name in files:
        if not name:
            continue
        try:
            storage.delete_pdf(name)
        except storage.UploadError:
            pass
        try:
            storage.delete_cover(name)
        except storage.UploadError:
            pass
        try:
            storage.delete_preview(name)
        except storage.UploadError:
            pass
    _audit("purge", book_id=book_id, detail=f"“{row['title']}” permanently deleted with all files")
    flash(f"“{row['title']}” and its files were permanently deleted.", "success")
    return redirect(url_for("admin.trash"))


@bp.route("/books/<int:book_id>/revisions/<int:revision_id>/restore", methods=["POST"])
@admin_required
@_csrf_protect
def revision_restore(book_id: int, revision_id: int):
    book = db.get_book(book_id, published_only=False, include_deleted=True)
    rev = db.get_revision(revision_id)
    if book is None or rev is None or rev["book_id"] != book_id:
        abort(404)
    # current file becomes a revision, the old one becomes current again
    db.add_revision(book_id, book["pdf_filename"], book["pdf_size"], book["page_count"])
    db.replace_book_pdf(book_id, rev["pdf_filename"], rev["pdf_size"], rev["page_count"])
    db.delete_revision(revision_id)
    storage.delete_preview(book["preview_filename"])
    db.set_book_preview(book_id, storage.generate_preview(rev["pdf_filename"]))
    db.set_book_text(book_id, storage.extract_pdf_text(rev["pdf_filename"]))
    _audit("restore_revision", book_id=book_id,
           detail=f"“{book['title']}” — restored earlier PDF ({rev['page_count']} pages)")
    flash("Earlier PDF restored — the replaced version was kept as a revision.", "success")
    return redirect(url_for("admin.book_edit", book_id=book_id))


# --------------------------------------------------------------------------
# bulk upload
# --------------------------------------------------------------------------

@bp.route("/books/bulk", methods=["GET", "POST"])
@admin_required
@_csrf_protect
def book_bulk():
    if request.method == "GET":
        return render_template("admin/bulk.html", results=None)

    category = _clean_text("category", 100, required=True)
    language = _clean_text("language", 60) or "English"
    published = _form_bool("published")
    parse_names = _form_bool("parse_names")
    uploads = request.files.getlist("pdfs")

    if not uploads or all(not u.filename for u in uploads):
        flash("Choose at least one PDF file.", "error")
        return render_template("admin/bulk.html", results=None), 400

    results = []
    for upload in uploads:
        if not upload.filename:
            continue
        entry = {"filename": upload.filename, "ok": False, "title": "", "detail": ""}
        try:
            pdf_name, pdf_size, page_count = storage.validate_and_save_pdf(upload)
        except storage.UploadError as exc:
            entry["detail"] = str(exc)
            results.append(entry)
            continue

        meta = storage.read_pdf_metadata(pdf_name)
        title, author = meta["title"], meta["author"]
        if parse_names:
            fn_title, fn_author = storage.parse_title_author(upload.filename)
            title = title or fn_title
            author = author or fn_author
        title = title or upload.filename[:-4]
        author = author or "Unknown author"

        preview_name = storage.generate_preview(pdf_name)
        text = storage.extract_pdf_text(pdf_name)
        book_id = db.insert_book(
            {
                "title": title,
                "author": author,
                "description": "",
                "category": category,
                "language": language,
                "pdf_filename": pdf_name,
                "pdf_size": pdf_size,
                "page_count": page_count,
                "cover_filename": None,
                "preview_filename": preview_name,
                "featured": False,
                "published": published,
            }
        )
        db.set_book_text(book_id, text)
        _audit("bulk_create", book_id=book_id,
               detail=f"“{title}” added via bulk upload ({page_count} pages)")
        entry.update(ok=True, title=title, detail=f"{page_count} pages · {pdf_size} bytes · id {book_id}")
        results.append(entry)

    ok_count = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count
    flash(
        f"Bulk upload finished: {ok_count} added"
        + (f", {fail_count} failed (see details below)." if fail_count else "."),
        "success" if ok_count and not fail_count else ("error" if not ok_count else "info"),
    )
    return render_template("admin/bulk.html", results=results)


@bp.route("/api/probe-pdf", methods=["POST"])
@admin_required
@_csrf_protect
def api_probe_pdf():
    """Read embedded metadata from a chosen PDF (nothing is stored)."""
    upload = request.files.get("pdf")
    if upload is None or not upload.filename:
        return jsonify({"ok": False, "error": "No file received."}), 400
    data = upload.stream.read(config.MAX_PDF_BYTES + 1)
    if len(data) > config.MAX_PDF_BYTES:
        return jsonify({"ok": False, "error": "File exceeds 100 MB."}), 400
    result = storage.probe_pdf_bytes(data)
    status = 200 if result["ok"] else 400
    return jsonify(result), status


# --------------------------------------------------------------------------
# categories & languages manager
# --------------------------------------------------------------------------

@bp.route("/terms")
@admin_required
def terms():
    return render_template(
        "admin/terms.html",
        categories=db.category_counts(published_only=False, include_deleted=False),
        languages=db.language_counts(published_only=False, include_deleted=False),
    )


@bp.route("/terms/rename", methods=["POST"])
@admin_required
@_csrf_protect
def term_rename():
    field = request.form.get("field") or ""
    if field not in ("category", "language"):
        abort(400)
    old = (request.form.get("old") or "").strip()
    new = (request.form.get("new") or "").strip()[:100]
    if not old or not new:
        flash("Both the current name and the new name are required.", "error")
        return redirect(url_for("admin.terms"))
    changed = db.rename_term(field, old, new)
    _audit("rename_term", detail=f"{field} “{old}” → “{new}” ({changed} books)")
    flash(f"Renamed {field} “{old}” to “{new}” across {changed} book(s).", "success")
    return redirect(url_for("admin.terms"))


@bp.route("/terms/merge", methods=["POST"])
@admin_required
@_csrf_protect
def term_merge():
    field = request.form.get("field") or ""
    if field not in ("category", "language"):
        abort(400)
    source = (request.form.get("source") or "").strip()
    target = (request.form.get("target") or "").strip()
    if not source or not target or source == target:
        flash("Choose two different names to merge.", "error")
        return redirect(url_for("admin.terms"))
    changed = db.merge_term(field, source, target)
    _audit("merge_term", detail=f"{field} “{source}” merged into “{target}” ({changed} books)")
    flash(f"Merged “{source}” into “{target}” — {changed} book(s) updated.", "success")
    return redirect(url_for("admin.terms"))


@bp.route("/terms/delete", methods=["POST"])
@admin_required
@_csrf_protect
def term_delete():
    field = request.form.get("field") or ""
    if field not in ("category", "language"):
        abort(400)
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)
    if db.term_book_count(field, name) > 0:
        flash(f"“{name}” still has books — merge or rename it instead.", "error")
    else:
        _audit("delete_term", detail=f"empty {field} “{name}” removed")
        flash(f"Empty {field} “{name}” removed from the lists.", "success")
    return redirect(url_for("admin.terms"))


# --------------------------------------------------------------------------
# audit log
# --------------------------------------------------------------------------

@bp.route("/audit")
@admin_required
def audit_log():
    return render_template("admin/audit.html", entries=db.audit_entries(200))


# --------------------------------------------------------------------------
# backup & export
# --------------------------------------------------------------------------

@bp.route("/backup")
@admin_required
def backup():
    """Zip of the database + every stored file, streamed once."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # consistent snapshot of the SQLite database
        import tempfile

        src = sqlite3.connect(config.DB_PATH)
        with tempfile.NamedTemporaryFile(suffix=".db") as tmpf:
            dst = sqlite3.connect(tmpf.name)
            src.backup(dst)
            dst.close()
            src.close()
            zf.write(tmpf.name, "data/library.db")

        for folder, arc in (
            (config.PDF_DIR, "storage/pdfs"),
            (config.COVER_DIR, "storage/covers"),
            (storage.preview_dir(), "storage/previews"),
        ):
            if folder.is_dir():
                for f in sorted(folder.iterdir()):
                    if f.is_file():
                        zf.write(f, f"{arc}/{f.name}")

        stats = db.stats()
        manifest = (
            f"Maktaba backup — {stamp} UTC\n"
            f"books: {stats['total']} (published {stats['published']}, drafts {stats['drafts']}, "
            f"trash {stats['trashed']})\n"
            f"Restore: copy data/library.db and storage/ back into the app directory.\n"
        )
        zf.writestr("README.txt", manifest)

    buf.seek(0)
    _audit("backup", detail=f"backup archive created ({stamp})")
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=maktaba-backup-{stamp}.zip",
        },
    )


@bp.route("/export.csv")
@admin_required
def export_csv():
    rows = db.all_books_for_export()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "title", "author", "category", "language", "pages",
                     "size_bytes", "published", "featured", "reads", "downloads", "added"])
    for r in rows:
        writer.writerow([
            r["id"], r["title"], r["author"], r["category"], r["language"],
            r["page_count"], r["pdf_size"], r["published"], r["featured"],
            r["open_count"], r["download_count"], r["created_at"],
        ])
    _audit("export_csv", detail=f"catalogue exported ({len(rows)} books)")
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=maktaba-catalogue.csv"},
    )
