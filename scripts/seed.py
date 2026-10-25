"""Seed the library with the generated sample booklets.

The PDFs are pushed through the exact same validation + storage pipeline used
by the admin upload form (storage.validate_and_save_pdf), so every seeded
entry is backed by a real file in storage/pdfs/ and a real database row.

Usage: python scripts/seed.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.datastructures import FileStorage  # noqa: E402

from idl import create_app, db, storage  # noqa: E402

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_pdfs"

BOOKS = [
    {
        "title": "The Etiquette of Seeking Knowledge",
        "author": "Maktaba Sample Editions",
        "category": "Islamic Education",
        "language": "English",
        "description": (
            "A short booklet on the manners of students of learning: sincerity of intention, "
            "respect for teachers and fellow students, consistency in study, and sharing "
            "knowledge with care. Sample edition produced for this library."
        ),
        "pdf": "etiquette-seeking-knowledge.pdf",
        "cover": None,
        "featured": True,
        "published": True,
    },
    {
        "title": "A Glossary of Islamic Terms",
        "author": "Maktaba Sample Editions",
        "category": "Reference",
        "language": "English",
        "description": (
            "Plain-language definitions of common Islamic terms — acts of worship, Qur'anic "
            "terms, hadith and legal vocabulary, and community words — written for new "
            "readers. Sample edition produced for this library."
        ),
        "pdf": "glossary-islamic-terms.pdf",
        "cover": "cover-glossary.jpg",
        "featured": True,
        "published": True,
    },
    {
        "title": "Introduction to the Sciences of Hadith",
        "author": "Maktaba Sample Editions",
        "category": "Hadith Studies",
        "language": "English",
        "description": (
            "How reports about the Prophet were collected and verified: the isnad and matn, "
            "the classification of reports as sahih, hasan, or da'if, and the great "
            "collections. Sample edition produced for this library."
        ),
        "pdf": "sciences-of-hadith.pdf",
        "cover": None,
        "featured": True,
        "published": True,
    },
    {
        "title": "The Qur'an: A Short Introduction",
        "author": "Maktaba Sample Editions",
        "category": "Qur'an Studies",
        "language": "English",
        "description": (
            "Orientation for first-time readers: how the 114 surahs are arranged, Makki and "
            "Madani periods, recitation and memorisation, and practical reading "
            "recommendations. Sample edition produced for this library."
        ),
        "pdf": "quran-short-introduction.pdf",
        "cover": None,
        "featured": True,
        "published": True,
    },
    {
        "title": "Understanding the Five Daily Prayers",
        "author": "Maktaba Sample Editions",
        "category": "Worship",
        "language": "English",
        "description": (
            "Names, times, and structure of the five obligatory prayers — rak'ah counts, "
            "ablution, direction of prayer, and congregational prayer. Sample edition "
            "produced for this library."
        ),
        "pdf": "five-daily-prayers.pdf",
        "cover": None,
        "featured": False,
        "published": True,
    },
]


def main() -> int:
    if not SAMPLE_DIR.exists():
        print("Sample PDFs not found. Run scripts/make_samples.py first.", file=sys.stderr)
        return 1

    app = create_app()
    with app.app_context():
        db.ensure_schema()

        existing_titles = {
            row["title"]
            for row in db.list_books(published_only=False, per_page=1000)[0]
        }

        for spec in BOOKS:
            if spec["title"] in existing_titles:
                print(f"skipped (already present): {spec['title']}")
                continue

            pdf_path = SAMPLE_DIR / spec["pdf"]
            if not pdf_path.exists():
                print(f"missing sample file: {pdf_path}", file=sys.stderr)
                return 1

            with open(pdf_path, "rb") as fh:
                pdf_name, pdf_size, page_count = storage.validate_and_save_pdf(
                    FileStorage(stream=fh, filename=spec["pdf"], content_type="application/pdf")
                )

            cover_name = None
            if spec["cover"]:
                cover_path = SAMPLE_DIR / spec["cover"]
                with open(cover_path, "rb") as fh:
                    cover_name = storage.validate_and_save_cover(
                        FileStorage(stream=fh, filename=spec["cover"], content_type="image/jpeg")
                    )

            preview_name = storage.generate_preview(pdf_name)
            text = storage.extract_pdf_text(pdf_name)

            book_id = db.insert_book(
                {
                    "title": spec["title"],
                    "author": spec["author"],
                    "description": spec["description"],
                    "category": spec["category"],
                    "language": spec["language"],
                    "pdf_filename": pdf_name,
                    "pdf_size": pdf_size,
                    "page_count": page_count,
                    "cover_filename": cover_name,
                    "preview_filename": preview_name,
                    "featured": spec["featured"],
                    "published": spec["published"],
                }
            )
            db.set_book_text(book_id, text)
            print(
                f"seeded book #{book_id}: {spec['title']} "
                f"({page_count} pages, {pdf_size} bytes -> storage/pdfs/{pdf_name})"
            )

        print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
