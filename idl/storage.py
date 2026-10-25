"""Persistent file storage for PDFs, covers, and first-page previews.

Files are written to disk only after passing validation. Nothing is claimed
as uploaded unless the bytes were actually written to storage/ and the
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


PREVIEW_DIR_NAME = "previews"
MAX_EXTRACT_CHARS = 1_000_000


def preview_dir() -> Path:
    d = config.STORAGE_DIR / PREVIEW_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


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

    try:
        reader = PdfReader(buffer)
        page_count = len(reader.pages)
        if page_count < 1:
            raise UploadError("The PDF contains no pages.")
    except UploadError:
        raise
    except Exception as exc:
        raise UploadError(f"The PDF could not be read: {exc}") from exc

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


JUNK_TITLES = {"", "untitled", "untitled document", "document", "microsoft word - document", "no title"}
JUNK_AUTHORS = JUNK_TITLES | {"anonymous", "reportlab", "unknown", "user"}


def _clean_meta_title(value: str) -> str:
    v = (value or "").strip()
    return "" if v.lower() in JUNK_TITLES else v


def read_pdf_metadata(filename: str) -> dict:
    """Return embedded title/author/page_count from a stored PDF (best effort)."""
    result = {"title": "", "author": "", "page_count": 0}
    try:
        reader = PdfReader(str(pdf_path(filename)))
        result["page_count"] = len(reader.pages)
        meta = reader.metadata
        if meta:
            title = _clean_meta_title(meta.title if hasattr(meta, "title") else "")
            author = (meta.author or "").strip() if hasattr(meta, "author") else ""
            if title and len(title) < 300:
                result["title"] = title
            if author and len(author) < 200 and author.lower() not in JUNK_AUTHORS:
                result["author"] = author
    except Exception:
        pass
    return result


def probe_pdf_bytes(data: bytes) -> dict:
    """Read metadata from in-memory PDF bytes without persisting anything."""
    result = {"ok": False, "title": "", "author": "", "page_count": 0, "error": ""}
    if not data.startswith(b"%PDF-"):
        result["error"] = "The file is not a valid PDF (missing %PDF header)."
        return result
    try:
        reader = PdfReader(io.BytesIO(data))
        result["page_count"] = len(reader.pages)
        meta = reader.metadata
        if meta:
            result["title"] = _clean_meta_title(meta.title if hasattr(meta, "title") else "")[:300]
            author = (meta.author or "").strip() if hasattr(meta, "author") else ""
            result["author"] = ("" if author.lower() in JUNK_AUTHORS else author)[:200]
        result["ok"] = True
    except Exception as exc:
        result["error"] = f"The PDF could not be read: {exc}"
    return result


def extract_pdf_text(filename: str) -> str:
    """Extract the visible text of a stored PDF for the search index.

    Truncated to MAX_EXTRACT_CHARS so the index stays bounded. Failures
    return '' rather than breaking the upload flow.
    """
    try:
        reader = PdfReader(str(pdf_path(filename)))
        parts: list[str] = []
        total = 0
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            parts.append(text)
            total += len(text)
            if total >= MAX_EXTRACT_CHARS:
                break
        return "\n".join(parts)[:MAX_EXTRACT_CHARS]
    except Exception:
        return ""


def generate_preview(filename: str) -> Optional[str]:
    """Render page 1 of a stored PDF to JPEG. Returns stored filename or None.

    A missing preview never blocks an upload — the UI degrades gracefully.
    """
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(pdf_path(filename)))
        try:
            if len(pdf) < 1:
                return None
            page = pdf[0]
            bitmap = page.render(scale=2.0)
            pil = bitmap.to_pil()
            pil = pil.convert("RGB")
            pil.thumbnail((900, 1300))
            stored_name = f"{uuid.uuid4().hex}.jpg"
            pil.save(preview_dir() / stored_name, format="JPEG", quality=82)
            return stored_name
        finally:
            pdf.close()
    except Exception:
        return None


def preview_path(filename: str) -> Path:
    return _safe_child(preview_dir(), filename)


def delete_preview(filename: Optional[str]) -> None:
    if filename:
        _unlink_quiet(preview_path(filename))


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
    image.save(config.COVER_DIR / stored_name, format="JPEG", quality=85)
    return stored_name


def cover_path(filename: str) -> Path:
    return _safe_child(config.COVER_DIR, filename)


def delete_cover(filename: Optional[str]) -> None:
    if filename:
        _unlink_quiet(cover_path(filename))


def parse_title_author(filename: str) -> tuple[str, str]:
    """Guess (title, author) from a filename like 'Author - Title.pdf'."""
    stem = Path(filename).stem.replace("_", " ").strip()
    for sep in (" - ", " – ", " — ", " -- "):
        if sep in stem:
            left, right = stem.split(sep, 1)
            author, title = left.strip(), right.strip()
            if title and author:
                return title[:300], author[:200]
    return stem[:300], ""


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _safe_child(directory: Path, filename: str) -> Path:
    if not filename or "/" in filename or "\\" in filename or filename.startswith("."):
        raise UploadError("Invalid storage filename.")
    directory.mkdir(parents=True, exist_ok=True)
    candidate = (directory / filename).resolve()
    if candidate.parent != directory.resolve():
        raise UploadError("Invalid storage filename.")
    return candidate


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
