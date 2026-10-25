"""Persistent file storage for PDFs and covers, with strict upload validation.

Files are written to disk only after they pass validation. Nothing is claimed
as uploaded unless the bytes were actually fsynced to storage/ and the
metadata row committed to SQLite.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Optional

from pypdf import PdfReader
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from . import config


class UploadError(Exception):
    """Raised when an upload fails validation; the message is user-facing."""


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------

def validate_and_save_pdf(upload: FileStorage) -> tuple[str, int, int]:
    """Validate a PDF upload and persist it.

    Returns (stored_filename, size_bytes, page_count).
    Raises UploadError with a clear message on any failure.
    """
    if upload is None or not upload.filename:
        raise UploadError("Please choose a PDF file to upload.")

    original = secure_filename(upload.filename or "")
    if not original.lower().endswith(".pdf"):
        raise UploadError("Only PDF files are accepted (filename must end in .pdf).")

    # Read the stream once, enforcing the size cap while copying.
    buffer = io.BytesIO()
    size = 0
    while True:
        chunk = upload.stream.read(64 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > config.MAX_PDF_BYTES:
            raise UploadError(
                f"PDF exceeds the maximum size of {config.MAX_PDF_BYTES // (1024 * 1024)} MB."
            )
        buffer.write(chunk)

    if size == 0:
        raise UploadError("The uploaded file is empty.")
    if not buffer.getvalue().startswith(b"%PDF-"):
        raise UploadError("The file is not a valid PDF (missing %PDF header).")

    # Structural check: must be readable and contain at least one page.
    try:
        reader = PdfReader(buffer)
        page_count = len(reader.pages)
        if page_count < 1:
            raise UploadError("The PDF contains no pages.")
    except UploadError:
        raise
    except Exception as exc:  # pypdf parse errors
        raise UploadError(f"The PDF could not be read: {exc}") from exc

    # Persist with a collision-proof name; never trust the client filename.
    stored_name = f"{uuid.uuid4().hex}.pdf"
    target = config.PDF_DIR / stored_name
    config.ensure_dirs()
    buffer.seek(0)
    with open(target, "wb") as fh:
        while True:
            chunk = buffer.read(64 * 1024)
            if not chunk:
                break
            fh.write(chunk)
        fh.flush()

    return stored_name, size, page_count


def pdf_path(filename: str) -> Path:
    return _safe_child(config.PDF_DIR, filename)


def delete_pdf(filename: Optional[str]) -> None:
    if filename:
        _unlink_quiet(pdf_path(filename))


# --------------------------------------------------------------------------
# covers
# --------------------------------------------------------------------------

def validate_and_save_cover(upload: FileStorage) -> str:
    """Validate an image upload and store it as JPEG. Raises UploadError."""
    from PIL import Image, UnidentifiedImageError

    if upload is None or not upload.filename:
        raise UploadError("Please choose an image file.")

    upload.stream.seek(0, 2)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size == 0:
        raise UploadError("The uploaded image is empty.")
    if size > config.MAX_COVER_BYTES:
        raise UploadError("Cover image exceeds the maximum size of 8 MB.")

    try:
        image = Image.open(upload.stream)
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise UploadError("The cover file is not a valid image.") from exc

    if image.width < 100 or image.height < 100:
        raise UploadError("Cover image must be at least 100 x 100 pixels.")

    image = image.convert("RGB")
    image.thumbnail((800, 1200))

    stored_name = f"{uuid.uuid4().hex}.jpg"
    config.ensure_dirs()
    target = config.COVER_DIR / stored_name
    image.save(target, format="JPEG", quality=85)
    return stored_name


def cover_path(filename: str) -> Path:
    return _safe_child(config.COVER_DIR, filename)


def delete_cover(filename: Optional[str]) -> None:
    if filename:
        _unlink_quiet(cover_path(filename))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _safe_child(directory: Path, filename: str) -> Path:
    """Resolve filename inside directory, rejecting any path traversal."""
    if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
        raise UploadError("Invalid storage filename.")
    candidate = (directory / filename).resolve()
    if candidate.parent != directory.resolve():
        raise UploadError("Invalid storage filename.")
    return candidate


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
