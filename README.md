# Maktaba — Islamic Digital Library

A public digital library of Islamic books in PDF. Anyone can browse, search,
and read published books in the browser — no account required. A single
authorized administrator manages the catalogue through a secure dashboard.

Built with **Flask + SQLite + local file storage**: real persistence, no
external services, trivial to back up (two directories).

---

## Features

**Public (no login)**
- Home page with search, featured books, popular-this-month, recently added,
  and categories
- Catalogue with filters (category, language), sorting (incl. popularity),
  and pagination
- Full-text search across title, author, category, description **and the
  extracted text inside every PDF** (SQLite FTS5 index)
- Book detail pages with cover, first-page preview ("look inside"), metadata,
  and read/download counts
- Dedicated PDF reader (PDF.js, served locally) with page navigation,
  page-jump input, zoom in/out, fit-width, keyboard shortcuts (← → pages,
  +/− zoom), **single-page and continuous-scroll modes**, a progress bar,
  and **“continue where you left off”** (position remembered per book in
  `localStorage` — no account needed)
- RTL rendering for Arabic-script titles and authors (bundled Noto Naskh
  Arabic font — works offline)
- **Light / Dark / Warm colour themes** — visitor's choice remembered on
  their device; applies site-wide including the reader
- **About & Contact pages** with a real message inbox for administrators
  (per-IP throttled, no email service required)
- **Share previews** (Open Graph / Twitter cards — book pages show the cover)
- **Installable as an app** (PWA manifest + icons + minimal offline shell)
- **How to cite** (Chicago-style citation) and print-optimised book pages
- Download as PDF
- Clear loading, empty, and error states throughout

**Administration** (`/admin`)
- Login with throttling (10 failures / 15 min per account+IP → 429)
- Dashboard with statistics, the full book list, read/download counts, and
  unread contact-message count
- **Contact message inbox** (mark read / delete)
- Add a book: PDF upload (validated), optional cover upload, metadata
  **auto-filled from the PDF's embedded title/author**
- **Bulk upload**: many PDFs at once, titles/authors parsed from PDF metadata
  or filenames (`Author - Title.pdf`), with an honest per-file results report
- Edit a book: update metadata, replace the PDF or cover, remove the cover
- **PDF version safety**: replaced PDFs are kept as restorable revisions
- Publish / unpublish (unpublished books are invisible to visitors at the
  **backend** level — detail, reader, and PDF endpoints all return 404)
- **Featured ordering**: pin, reorder (↑ ↓ / top), and unpin the home shelf
- **Trash**: delete is a soft-delete; restore later or "delete forever"
  (which removes the row and every stored file)
- **Categories & languages manager**: rename or merge across the catalogue
- **Audit log**: every change recorded with admin, action, book, and time
- **Backup & export**: one-click zip (SQLite snapshot + all PDFs/covers/
  previews) and CSV catalogue export

## Security model

| Concern | How it is handled |
|---|---|
| Credentials | Admin password stored only as an **argon2** hash in SQLite. Set via `IDL_ADMIN_PASSWORD` or interactive prompt — never in code. |
| Secrets | Session signing key from `IDL_SECRET_KEY` (or a private file `data/secret_key`, chmod 600). Never sent to the client. |
| Authorization | Every mutating route re-checks the session against the `admins` table server-side. Public queries filter `published = 1` in SQL. |
| CSRF | Per-session token required on every POST; compared with `hmac.compare_digest`. |
| Uploads | PDFs verified by magic bytes (`%PDF-`) **and** parsed with pypdf; size cap 100 MB; stored under random UUID names (client filenames never trusted); path-traversal protected. Covers verified with Pillow, re-encoded to JPEG. |
| Deletion | Soft-delete to Trash first; files are only removed on an explicit "delete forever". Replaced PDFs are kept as restorable revisions. |
| Privacy | Popularity counting stores only book id + kind + timestamp — no user identifiers. Reader positions stay in the visitor's own `localStorage`. |
| Login abuse | Sliding-window rate limiting returns HTTP 429. |
| Transport | Session cookie is `HttpOnly`, `SameSite=Lax`; set `IDL_SECURE_COOKIES=1` behind HTTPS. |
| Headers | CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` on every response. |
| SQL | 100% parameterized queries. |

Visitors can read **published** books without logging in; only the admin can
modify the library. Enforcement is in the routes and SQL, not in the UI.

## Requirements

- Python 3.10+ (tested on 3.13)
- See `requirements.txt` (Flask, waitress, argon2-cffi, pypdf, Pillow, reportlab)

## Setup (manual steps)

```bash
# 1. Install dependencies (ideally in a virtualenv)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure secrets (recommended for deployment)
export IDL_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
export IDL_SECURE_COOKIES=1        # when serving over HTTPS

# 3. Create the administrator account (required before first login)
export IDL_ADMIN_USERNAME=admin
export IDL_ADMIN_PASSWORD='choose-a-strong-password'
python3 scripts/create_admin.py

# 4. (Optional) load the sample booklets so the catalogue is not empty
python3 scripts/make_samples.py
python3 scripts/seed.py

# 5. Run
python3 run.py                      # http://0.0.0.0:8000
# or: gunicorn -w 4 -b 0.0.0.0:8000 run:app
```

Then open `http://localhost:8000`, and sign in at `/admin/login`.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `IDL_SECRET_KEY` | Flask session signing key | generated into `data/secret_key` |
| `IDL_ADMIN_USERNAME` / `IDL_ADMIN_PASSWORD` | used only by `scripts/create_admin.py` | — |
| `IDL_HOST` / `IDL_PORT` | bind address for `run.py` | `0.0.0.0` / `8000` |
| `IDL_SECURE_COOKIES` | set `1` behind HTTPS | `0` |
| `IDL_DATA_DIR` / `IDL_STORAGE_DIR` / `IDL_DB_PATH` | storage locations | `./data`, `./storage` |

### Backup

Stop the app (or not, SQLite WAL is crash-safe), then copy two directories:

```bash
cp -r data storage /path/to/backup/
```

Restore by copying them back.

### Deployment notes

- Any WSGI server works (`waitress` (bundled default), `gunicorn`, `uvicorn --ws wsgi`).
- Serve behind HTTPS (e.g. Caddy or nginx) and set `IDL_SECURE_COOKIES=1`.
- The app is a single stateless process group + two local directories; it
  scales vertically without special handling. For multiple machines, put
  `storage/` on a shared volume and `data/` on one writer (SQLite) or migrate
  to Postgres later.
- PDF files are served with HTTP Range support so the reader stays fast on
  large books.

## Tests

```bash
python3 -m pytest tests/ -v
```

47 end-to-end tests cover: public browsing/search/detail/reader, PDF
streaming and Range requests, unpublished-book protection, login (wrong
password, wrong CSRF, rate limiting, logout), real multipart uploads with
disk persistence, invalid upload rejection, edit/PDF-replacement with
revision recovery, trash → restore → permanent delete with file cleanup,
missing-CSRF rejection, secret-leak checks — plus the feature rounds:
PDF full-text search, reader resume UI, RTL detection, read/download
counting and the popular shelf, first-page previews, bulk upload, PDF
metadata probing, category rename/merge, the audit log, featured pinning,
backup zips, CSV export, the contact form with rate limiting and admin
inbox, share previews, PWA manifest, citation/print support, themes, and
the bundled Arabic font.

All flows were also smoke-tested against the running server with curl.

## Project layout

```
app code        idl/            (config, db, security, storage, covers, views)
templates       templates/      (public pages, reader, admin, errors)
static          static/         (css, js, vendored pdf.js, favicon)
persistent data data/           (library.db, secret_key)   ← back up
persistent files storage/       (pdfs/, covers/, previews/)  ← back up
scripts         scripts/        (create_admin, make_samples, seed, backfill)
tests           tests/          (pytest end-to-end suite)
```

Upgrades of an existing install: run `python3 scripts/backfill.py` once to
index PDF texts and generate first-page previews for older books.

## Sample content

`scripts/make_samples.py` generates five short **original sample booklets**
(as clearly labelled in their descriptions) plus one cover image; `seed.py`
pushes them through the same validation and storage pipeline as the admin
upload form. They exist so the library can be exercised end to end — replace
them with real books through the admin dashboard whenever you like.

## Troubleshooting

- **"No admin account" on login** — run `python3 scripts/create_admin.py`.
- **413 on upload** — the PDF exceeds 100 MB (`MAX_PDF_BYTES` in `idl/config.py`).
- **Reader shows "This book could not be opened"** — check that the PDF file
  exists in `storage/pdfs/` (it may have been removed manually); re-upload it
  from the admin edit form.
- **Forgot the admin password** — re-run `scripts/create_admin.py` with the
  same username to reset it.
