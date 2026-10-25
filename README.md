# Maktaba — Islamic Digital Library

A public digital library of Islamic books in PDF. Anyone can browse, search,
and read published books in the browser — no account required. A single
authorized administrator manages the catalogue through a secure dashboard.

Built with **Flask + SQLite + local file storage**: real persistence, no
external services, trivial to back up (two directories).

---

## Features

**Public (no login)**
- Home page with search, featured books, recently added, and categories
- Catalogue with filters (category, language), sorting, and pagination
- Full-text search across title, author, category, and description
- Book detail pages with cover, metadata, and description
- Dedicated PDF reader (PDF.js, served locally) with page navigation,
  page-jump input, zoom in/out, fit-width, and keyboard shortcuts
  (← → for pages, +/− for zoom)
- Download as PDF
- Clear loading, empty, and error states throughout

**Administration** (`/admin`)
- Login with throttling (10 failures / 15 min per account+IP → 429)
- Dashboard with statistics and the full book list
- Add a book: PDF upload (validated), optional cover upload, metadata
- Edit a book: update metadata, replace the PDF or cover, remove the cover
- Publish / unpublish (unpublished books are invisible to visitors at the
  **backend** level — detail, reader, and PDF endpoints all return 404)
- Delete a book (removes the database row **and** the stored PDF/cover files)

## Security model

| Concern | How it is handled |
|---|---|
| Credentials | Admin password stored only as an **argon2** hash in SQLite. Set via `IDL_ADMIN_PASSWORD` or interactive prompt — never in code. |
| Secrets | Session signing key from `IDL_SECRET_KEY` (or a private file `data/secret_key`, chmod 600). Never sent to the client. |
| Authorization | Every mutating route re-checks the session against the `admins` table server-side. Public queries filter `published = 1` in SQL. |
| CSRF | Per-session token required on every POST; compared with `hmac.compare_digest`. |
| Uploads | PDFs verified by magic bytes (`%PDF-`) **and** parsed with pypdf; size cap 100 MB; stored under random UUID names (client filenames never trusted); path-traversal protected. Covers verified with Pillow, re-encoded to JPEG. |
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

23 end-to-end tests cover: public browsing/search/detail/reader, PDF
streaming and Range requests, unpublished-book protection, login (wrong
password, wrong CSRF, rate limiting, logout), real multipart uploads with
disk persistence, invalid upload rejection, edit/PDF-replacement, delete with
file cleanup, missing-CSRF rejection, and secret-leak checks.

All flows were also smoke-tested against the running server with curl.

## Project layout

```
app code        idl/            (config, db, security, storage, covers, views)
templates       templates/      (public pages, reader, admin, errors)
static          static/         (css, js, vendored pdf.js, favicon)
persistent data data/           (library.db, secret_key)   ← back up
persistent files storage/       (pdfs/, covers/)           ← back up
scripts         scripts/        (create_admin, make_samples, seed)
tests           tests/          (pytest end-to-end suite)
```

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
