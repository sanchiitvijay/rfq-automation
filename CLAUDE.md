# CLAUDE.md: Ferguson RFQ Agent

Context for working in this repo. Read this first; `README.md` is the user-facing guide, `spec.md` is the
spec it was built from (with an "Implementation notes" log of every round of changes).

## What this is
The Day-4 Ferguson RFQ challenge (https://ferguson-day4-agentic-fest.vercel.app/), extended into a product:
- **Part A, base flow** (`rfq/`): a request email (.eml or pasted text) → product IDs → lookup → fills
  `templates/rfq_template.xlsx` → `out/<email>/RFQ.xlsx` + `reply.eml`.
- **Part B, agentic arm, option 2 "RFQ Quality Agent"** (`rfq/quality/`): unit standardisation, grey
  (missing) and orange (suspicious) flags, an AI contradiction check and a Summary sheet. It **flags and never
  overwrites**. The competitor finder (option 1) is NOT built: competitor codes are reported `Not found` with a reason.
- **Around it:** FastAPI + SQLite + Redis/arq workers (`backend/`), a React app (`frontend/`), a Gmail Chrome
  extension (`extension/`), human-in-the-loop editing, Excel upload, and sending to the point of contact (POC).

The user (sourcing team at Ferguson) cares most about: **never guessing values**, every value sourced with a link,
Ferguson branding, robustness and edge cases, and things verified for real (not just written).

## Hard rules (do not break)
1. **Blank means unknown; never guess.** Every filled cell has a row on the Sources sheet (source_type,
   confidence, source text, link). The LLM never writes cell values. It may only flag cells that already hold a value.
2. **CLI contract for `mailbot.py`** (do not modify `mailbot.py`):
   `python rfq/build.py <eml> --out out [--offline] [--no-llm] [--no-pdf] [--no-images]` writes
   `out/<eml stem>/RFQ.xlsx` and `reply.eml`.
3. **Email 1 offline must equal `reference/email-1 reference output.xlsx`** on the RFQ sheet, cell by cell. The
   Sources sheet equals the reference in its first 6 columns, after excluding our extra rows (`Description`
   sources and `Supplier: …` rows) and our 7th `link` column. Checked by `tests/test_rfq_output.py`.
4. **Keep every requested ID** in request order. Duplicates are kept once with a Note. Not-found rows stay with
   `Lookup Status = Not found` and blank specs.
5. **Template columns stay as they are**, including both `Image` and `Picture` (the template's "How to fill"
   defines them). Image = embedded picture (+ `=IMAGE()` formula underneath), Picture = the URL as a hyperlink.
   Image always follows Picture: edits to Image are refused, uploads read Picture only.
6. **Respect ferguson.com:** max `FERGUSON_RATE_PER_MINUTE` (default **12**) page loads per minute across all
   workers (spec-sheet PDFs on api.ferguson.com share the budget). No captcha solving or fingerprint spoofing;
   fall back to the catalog instead.
7. **Secrets only in `.env`** (git-ignored). Never print their values: check lengths/shape only. httpx INFO logging
   is silenced in the worker because it logs full URLs (SerpApi key in the query).
8. **Sending email is only ever a human click** after confirmation, to a validated address, and idempotent.
9. **Frontend design:** Ferguson brand tokens only (`frontend/src/theme/tokens.css`). No gradients, no purple, no
   glassmorphism, no "✨ AI" styling. Flat, dense enterprise UI. Inputs must use ink text (never inherit white
   from the navy header).

## Layout
```
rfq/                      core flow (plain Python, used by CLI, worker and later Azure)
  config.py               paths, RFQ/SPEC/SUPPLIER columns, RunOptions (env-driven), .env loader
  models.py               dataclasses: RequestItem, Cell(value, source_type, confidence, source, url), Row
                          (cells + supplier), Sheet, Flag, QualityReport, ParsedEmail; JSON round-trip
  parse_email.py          .eml / pasted text → body (plain or HTML→text), sheet attachments, warnings
  extract_ids.py          deterministic ID extraction (6–7 digit IDs, dashed/alnum competitor codes,
                          masks phones/dates/PO numbers/URLs), qty, brand, dedupe, xlsx/csv attachments
  lookup/cache.py         Cache protocol: RedisCache / MemoryCache (fallback); slot(), rate() sliding window
  lookup/serpapi.py       SerpApi Google search `site:ferguson.com "<id>"`; exact product-URL match only
  lookup/live.py          ferguson.com product page via Chrome CDP :9333 (JSON-LD + spec table + HTML fallback)
  lookup/catalog.py       data/product_catalog.json + product_catalog_sources.csv → sourced Cells + links
  lookup/specsheet.py     spec PDFs: fill BLANK Thickness/ASTM only when the PDF states exactly one value
  lookup/resolve.py       orchestration (order below), live-vs-catalog merge + Notes, supplier merge
  excel/writer.py         render(sheet, path, report, email_info, meta, embed_images); Sources links;
                          Supplier sheet; hidden _rfq_meta; RFQ is first + active sheet; render_summary_bytes
  excel/reader.py         workbook → Sheet (quality agent CLI, base version for uploads)
  excel/importer.py       preview of an uploaded edited file: load_table() for .xlsx/.xlsm/.xls/.csv,
                          then three-way compare + validation (same rules for every format)
  excel/images.py         thumbnail prefetch to out/image_cache (Ferguson CDN only), primary_picture()
  excel/palette.py        the ONE colour palette for .xlsx and .xls (matches the web app)
  excel/exports.py        download formats: xlsx (master), xls (converted via xlwt), csv (+ Review notes)
  quality/                units.py, checks.py (code), llm_checks.py (OpenAI), summary.py, agent.py
  validation.py           rules for human edits (units, Yes/No, URLs incl. a|b lists, no formulas)
  eta.py                  Progress: phases, % and time left (EMA per work kind, rate-limit floor)
  pipeline.py             run(): parse → extract → resolve → quality → pictures → render → reply
backend/app/
  main.py                 FastAPI app, CORS, 503 handlers, /api/health, POST /api/mail/test
  db.py                   async engine: SQLite (WAL, busy_timeout, foreign_keys) or any SQLAlchemy URL
  models.py               Job (sheet/report JSON + version), JobItem, JobEvent, JobEdit, JobSend; UTCDateTime
  api/jobs.py             create (JSON/raw eml/upload), list+search, facets, suggest, detail, retry, delete,
                          rfq.xlsx, summary.xlsx, reply.eml
  api/sheet.py            GET/PATCH sheet (versioned edits), sheet/import (preview), recheck, review
  api/send.py             POST send (validated, idempotent, atomic status claim)
  api/stream.py           SSE: /api/jobs/{id}/events and /api/events (Redis pub/sub)
  services/               jobs.py (serialise), sheet.py (HITL apply/recheck/regenerate), mail.py (SMTP),
                          search.py (DB search, facets with labels, suggestions)
  worker.py               arq: run_rfq_job, send_rfq_email, cron recover_stuck_jobs
  run_worker.py           supervisor: restarts arq when Redis drops (ALWAYS run the worker through this)
frontend/src/             api/ (client, hooks, events SSE+poll fallback, types), components/ui (primitives,
                          SearchBox, Pagination), components/layout (AppShell), features/jobs | review | send,
                          theme/ (tokens), assets/ (real ferguson-light.svg logo + symbol)
extension/                MV3: gmail.js (raw MIME via "Show original", DOM fallback), background.js, popup, options
scripts/                  dev.sh (API+worker+web), chrome.sh (debug Chrome :9333), migrate_pg_to_sqlite.py
docs/                     architecture.md (8 Mermaid diagrams), api.md, rfq-workbook.md, operations.md
presentation/             Group 3 deck (HTML from the Agentic Fest template + PDF + slide images + architecture.mmd)
tests/                    core tests + tests/backend (temp SQLite, fake queue, fake SMTP); fixtures/live/*.html.gz
```

## Lookup order (live mode)
cache → **SerpApi** (if `SERPAPI_API_KEY` set and not exhausted) → **ferguson.com page** (only if SerpApi is
unusable/timed out/found nothing, or the product is NOT in the catalog, per `SCRAPE_AFTER_SERPAPI=missing|always|never`)
→ **backup catalog** (collected 2026-09-24) → **Not found** (with every source tried). Then spec PDFs fill blanks.
Precedence: live page > SerpApi > catalog. Every live/catalog difference becomes a Note.
SerpApi quota out / key rejected → Redis flag `serpapi:exhausted` for 1 h. `--offline` = catalog + PDFs only.

## Commands
```bash
.venv/bin/python -m pytest -q tests                    # all tests (≈121, ~55 s); backend tests use a temp SQLite
(cd frontend && npx tsc -p . && npx vite build)        # typecheck + build (TS 7, Vite 8 / Rolldown)
scripts/chrome.sh                                      # debug Chrome on :9333 (profile ~/chrome-debug-profile)
scripts/dev.sh                                         # API :8000, supervised worker, web :5173
.venv/bin/uvicorn backend.app.main:app --port 8000     # API alone
.venv/bin/python -m backend.app.run_worker             # worker alone (never plain `arq ...`)
.venv/bin/python rfq/build.py emails/email-1-ids-in-body.eml --out out --offline --no-llm   # CLI
curl -s localhost:8000/api/health                      # db, redis, queue, chrome, serpapi, rate, sending
```
Auth: header `X-API-Key: <API_KEY from .env>` (or `?key=` for SSE/downloads). `X-User` = editor name.
Frontend reads `frontend/.env.local` (`VITE_API_URL`, `VITE_API_KEY`).

## Local environment (this Mac)
- Python venv `.venv` (3.12), Node 24. **No Docker.** Redis is not a brew service: start it with
  `redis-server --daemonize yes --dir "$PWD/out"` (started from the repo root without `--dir` it drops a
  `dump.rdb` there; it's git-ignored but delete it). Postgres 14 is still installed as a brew service but is **no
  longer used** (data migrated to `out/rfq.sqlite3`).
- The debug Chrome on 9333 gets closed by the user sometimes: CDP "connection refused" means relaunch it with
  `scripts/chrome.sh`; don't assume the scraper broke.
- `.env` has real OpenAI, SerpApi (Developer plan) and Gmail bot credentials. **Gmail sending currently fails:**
  Google returns `535 BadCredentials` for the App Password. That's the user's config, not code: they need a new
  App Password for exactly `BOT_EMAIL`. Use "Test mail login" / `POST /api/mail/test` (logs in, sends nothing).
- For send-flow testing use a local sink (aiosmtpd on 127.0.0.1:8025 with `ready_timeout=30`) and env overrides
  `SMTP_HOST=127.0.0.1 SMTP_PORT=8025 SMTP_SSL=false BOT_EMAIL=rfq-bot@example.com`. Never send real mail in tests.

## Gotchas learned the hard way
- **ferguson.com pages:** `/product/<id>.html` redirects to the canonical page; a missing product redirects to the
  homepage (= not found). Some pages have **no JSON-LD**: use h1 / `ul.js-product-features-list` / `data-sku` /
  image regex. Text uses pseudo-tags (`<CQUOTA/>` → `'`). Comma lists → `|` for Application/Material/ASTM.
- **Catalog quirks:** `"[]"` means empty; some Picture values are **two URLs joined by `|`**: use
  `primary_picture()` (prefers `_primary`) for Image formula, embedding and thumbnails; keep the stored value.
- **SerpApi** fresh searches take 20–60 s (`SERPAPI_TIMEOUT_S`, default 45). Google often ignores `site:` for
  products it hasn't indexed (e.g. 225123, 4570880) and returns junk. The exact product-URL regex rejects it.
- **SMTP:** `smtplib.login()` retries a second mechanism after Gmail has hung up, hiding `535` behind
  "Connection unexpectedly closed". `mail._login()` does a single AUTH; auth errors are permanent (no retry).
- **Concurrency invariants** (all tested): version-checked `PATCH /sheet` (409 on stale); `recheck` stores its
  report only `WHERE version = checked version`, else re-runs; jobs claimed with an atomic `UPDATE … RETURNING`;
  sends claimed atomically + unique idempotency key; the recovery cron re-queues `queued` jobs older than 60 s
  and dead `running` ones.
- **arq** exits when Redis drops → always use `run_worker.py`. arq de-duplicates `_job_id`s, so use distinct ids
  for retries/recovery.
- **SQLite:** use the portable types only (`JSON`, `Uuid`, `UTCDateTime`). Python-side `default=utcnow` (no
  `server_default=func.now()`). `Uuid` is stored as hex without dashes, so raw SQL with dashed ids won't match:
  use the ORM. No `TRUNCATE`/`interval`.
- **openpyxl:** external text must be written as string cells (`data_type = "s"`; only our `=IMAGE()` is a
  formula). It cannot re-save a workbook it loaded with images; tests that re-save use `embed_images=False`.
  Excel 365 re-saves `IMAGE()` as `=_xlfn.IMAGE(...)`.
- **Formats:** CSV can't carry colours or the version stamp; `.xls` can't carry pictures, links or comments.
  Write CSV with a BOM and the `'` injection guard, and read it back with delimiter sniffing (`;` from European Excel)
  and a cp1252 fallback. xlwt needs `cell_overwrite_ok=True` to rewrite a cell and has 0x21–0x3F custom colour slots.
- **Quick Look doesn't render embedded drawings** and shows `=IMAGE()` as `0`. To see what a user sees, export
  via Numbers (`osascript … export doc … as PDF`) and quit Numbers afterwards.
- **Frontend:** React `useId()` returns `:r1:` (invalid CSS id): strip colons. Use explicit `<label htmlFor>`;
  wrapping a `<select>` puts all option texts in its accessible name. AG Grid v36: register only the modules used
  (incl. `RowApiModule` for `getRowNode`); `tooltipValueGetter` is deprecated, use `tooltip`; columns are
  virtualised (off-screen cells are not in the DOM; use the keyboard (End) in UI tests). Every prop passed to `<AgGridReact>` must keep
  its identity between renders (module constants, `useCallback`, `useMemo`): an inline object/function makes the grid
  refresh its rows and silently breaks double-click editing. Grid popups use `popupParent=document.body` (the grid is
  only as tall as its rows). Dropdown options come from `GET /sheet` → `options`. React Query structural
  sharing returns the same object on refetch: restore rejected grid values with `node.setData`. Never let an
  older response overwrite newer data (`keepNewest`). Vite 8 rejects object `manualChunks`. After renaming files,
  restart the Vite dev server (stale module graph).
- **Gmail extension:** confirmed working in real Gmail (full raw MIME). `looksLikeMime` must require the text to
  *start* with a header line (an HTML wrapper contains "From:" too).

## Verifying changes (expected standard here)
Don't stop at "tests pass": run the real thing. For backend/pipeline: a CLI run + compare email 1 with the
reference; a live job through the API/worker (`/api/health` first). For UI: Playwright over CDP on the debug Chrome
(`connect_over_cdp("http://127.0.0.1:9333")`, new page, screenshot to the scratchpad, read it), check console errors.
For Excel output: open with openpyxl (sheet order, active sheet, `ws._images`, hyperlinks) and, for visuals, Numbers.
For rate limiting: read the Redis sorted set `rate:ferguson` timestamps (≤ limit in any 60 s window).
Always report honestly what was and wasn't verified (e.g. real SerpApi vs mocked, real Gmail vs mock).

## Conventions
- Python: type hints, small single-purpose modules, docstrings that explain *why*. Errors become readable
  messages (never crash a job for a picture/PDF/LLM problem; note it instead).
- Frontend: TypeScript strict; feature folders; all colours from tokens; filter options and labels come from
  `GET /api/jobs/facets` (don't hardcode statuses/sources in the UI); filters live in the URL.
- Every change: update `README.md` (user-facing) and append to the implementation notes in `spec.md`.
- Don't commit unless asked (nothing has been committed so far beyond the starter kit).

## Docs, deck and how they were made
- Keep `docs/` accurate to the code. The lookup diagram shows the Ferguson product API as a dashed plug-in point
  (not implemented). The **deck** shows "Ferguson API → SerpApi → page → catalog" at the user's request, and slide 7
  states that the Ferguson API step needs credentials. Keep that disclosure if the deck is edited.
- Render or verify Mermaid in a **separate headless Chrome** (`p.chromium.launch(executable_path=<Google Chrome>,
  headless=True)` + mermaid@11 from jsdelivr): the scraping Chrome on :9333 refused new browser contexts at one
  point, and headless also gives clean screenshots/PDFs. The deck PDF = 2× screenshots of each slide (UI
  button hidden) joined with Pillow.

## Status / not built yet
Not built: the competitor finder (option 1), user accounts (one shared API key; editor name typed in the
header), the Azure Function (`function_app.py` wrapping `rfq.pipeline.run` offline, route `/rfq`), and official
Brand Connect colours (current tokens are read from ferguson.com, marked TODO verify). Gmail sending is blocked on a
valid App Password (see above).
