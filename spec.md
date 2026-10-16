# Spec — Ferguson RFQ Agent

> Paste this whole file into a coding agent (or hand it to a developer) to build the system.
> It is self-contained: role, rules, spec, guardrails, edge cases, fallbacks, design rules and acceptance tests.
> **Status: implemented** — see README.md for how to run it.

## Role & working rules for the implementer
You are a senior full-stack engineer building a production-quality RFQ automation system in this repo
(`ferguson-rfq-starter-kit`). Work **spec-driven**: first copy this spec into `spec.md`, then implement in the
order given under "Implementation order"; after each step run its tests before moving on.

Non-negotiable rules:
1. **Never guess a value.** Blank means unknown. Every filled cell has a row on the Sources sheet. Anything not found is listed in the Summary with the reason and the sources tried.
2. **Keep the CLI contract:** `python rfq/build.py <eml> --out out [--offline]` must write `out/<eml stem>/RFQ.xlsx` (+ `reply.eml`), because `mailbot.py` depends on it. Do not modify `mailbot.py`.
3. **Email 1 offline must match `reference/email-1 reference output.xlsx` cell by cell** (RFQ + Sources).
4. **Clean structure:** small single-purpose modules, typed (Python type hints + pydantic; TypeScript strict), no god files, no copy-paste, errors handled with clear messages instead of crashes. Secrets only in `.env`.
5. **Frontend design:** Ferguson brand tokens, flat enterprise data UI. No purple, no gradients, no glassmorphism, no "AI sparkle" components, no default UI-kit demo look (details in §7).
6. Respect ferguson.com: use the user's own Chrome via CDP with polite rate limits; no captcha solving or fingerprint evasion. The fallback for blocks is the backup catalog.
7. Use OpenAI (`OPENAI_API_KEY`, `OPENAI_MODEL`) only for **flagging** (Quality Agent) and optional PDF quote extraction. The LLM never writes cell values on its own.

Tech stack: Python 3.11+, FastAPI, SQLAlchemy 2 (async) + Postgres, Redis (queue + cache + pub/sub), arq workers,
Playwright (CDP), openpyxl, pdfplumber, httpx, pytest · React 18 + Vite + TypeScript, React Router, TanStack Query,
AG Grid Community, DOMPurify · Chrome Extension Manifest V3 · docker-compose for Postgres + Redis.

---

## Context
Ferguson sourcing staff spend days copy-pasting product specs into RFQ sheets. The Day-4 challenge
(https://ferguson-day4-agentic-fest.vercel.app/) asks for:
- **Part A (base):** `.eml` → extract product IDs → look up live ferguson.com (fallback: `data/product_catalog.json`) → fill `templates/rfq_template.xlsx` → `out/<email>/RFQ.xlsx` + `reply.eml`.
- **Part B (agentic arm):** we build **Option 2, the RFQ Quality Agent**. It standardizes units, flags missing values (grey) and odd values (orange), and adds a **Summary sheet**. It flags values and never overwrites them.

On top of that, we wrap it in a product: a **Gmail Chrome extension** that sends the open email to a **FastAPI backend with Postgres + Redis + arq workers**, so RFQ jobs run in parallel. A **React frontend** shows each email, the current phase and an approximate time remaining. We **never hallucinate**: anything not found goes into the Summary as "not found / why".

Decisions made: Quality Agent only (no competitor web search), Postgres + Redis + arq, OpenAI, local first with Azure as a later phase.

### Facts from the repo (verified)
- `spec.md` is **empty**, so this spec becomes its content (step 0).
- `mailbot.py` calls `python rfq/build.py <eml> --out out [--offline]` and expects `out/<eml stem>/RFQ.xlsx` and optionally `reply.eml`. **The CLI contract must stay stable.**
- Template columns (RFQ sheet, 23): `product_id … ASTM, Image, Picture, Lookup Status`. Sources sheet: `product_id, column, value, source_type, confidence, source`. The reference also has a **Notes** sheet (`product_id, note`).
- **The catalog matches the email-1 reference with 0 differences** on every shared column, so offline mode can reproduce the reference exactly. Sources rows come from `data/product_catalog_sources.csv`.
- IDs missing from the catalog that appear in the test emails: `9677533` (email 4) and `225123` (email 2; live on ferguson.com again since 14 Oct). Competitor codes `17783-79-3000`, `31-024`, `MTX-4409-XQ` and `17774-79-3000` must become **Not found** rows.
- Email 2: the IDs are in `rfq_items.xlsx` (sheet `Items`, column `Item number`, with Qty). Email 4: `#` prefixes, IDs inside sentences, `5106926` appears twice. We keep one row and record the duplicate in Notes.
- Spec PDFs: `data/spec_sheet_links.csv` (39 products, not blocked).

---

## Architecture

```
Gmail tab ──(extension: raw MIME or DOM text)──┐
React UI  ──(paste body / upload .eml)─────────┼─► FastAPI  ──► Postgres (jobs, items, events)
mailbot.py ──(CLI, unchanged)──► rfq/build.py   │      │
                                                │      └─► Redis queue ──► arq workers (N, max_jobs=4 each)
                                                │                            │
                                                │             rfq.pipeline.run(job) ◄── same core as the CLI
                                                │                │
                                                │    extract → lookup(live CDP │ cache │ catalog) → spec PDF
                                                │    → fill xlsx → Quality Agent → Summary → reply.eml
                                                │                │
React UI ◄──── SSE /api/jobs/{id}/events ◄── Redis pub/sub (phase, %, ETA)
```

**Single core:** `rfq/` is a plain Python package. The CLI (`rfq/build.py`), the arq worker and later `function_app.py` (Azure) are thin wrappers around it.

## Repo layout (new)
```
spec.md                     # filled from this prompt (spec-driven)
rfq/
  build.py                  # CLI: python rfq/build.py <eml> --out out [--offline] [--no-llm]
  pipeline.py               # run(eml_bytes|text, out_dir, opts, progress_cb) -> Result
  parse_email.py            # .eml/text → body, subject, sender, xlsx attachments
  extract_ids.py            # regex ID extraction + qty + dedupe + competitor tokens
  lookup/
    live.py                 # ferguson.com via Chrome CDP (port 9333), block detection
    catalog.py              # product_catalog.json + product_catalog_sources.csv
    specsheet.py            # spec PDF download + text extraction (pdfplumber)
    cache.py                # Redis cache (no-op in CLI without Redis)
  fill_rfq.py               # template → RFQ + Sources + Notes sheets
  quality/
    units.py                # code: unit standardization
    checks.py               # code: missing values, format checks
    llm_checks.py           # OpenAI: contradiction checks (flags only)
    summary.py              # Summary sheet + cell highlighting
  reply.py                  # reply.eml with RFQ.xlsx attached
  eta.py                    # stage timing estimates (EMA)
backend/
  app/main.py, api/jobs.py, models.py, db.py, schemas.py, worker.py, settings.py
  docker-compose.yml        # postgres + redis (api/worker run natively → access to local Chrome)
frontend/                   # React (Vite + TS)
extension/                  # Chrome MV3: manifest.json, content.js, background.js, popup.html
tests/                      # pytest: email 1 = reference, emails 2–4 behavior
```

---

## Spec by component

### 1. Email parsing + ID extraction (code only, deterministic)
- Inputs: raw `.eml` bytes (extension/upload/mailbot) **or** plain text (paste). Reuse the `email` + `email.policy.default` approach from `mailbot.py`.
- Body: prefer `text/plain`, otherwise strip `text/html` to text. Read xlsx attachments with openpyxl and find the column whose header contains "item"/"product"/"part", plus Qty if present.
- Ferguson IDs: regex `(?<![\w-])#?(\d{6,7})(?![\w-])`, with filters so quantities ("x 40 rolls"), dates and phone numbers don't match. Order of first appearance; duplicates go to Notes ("listed 2×").
- Competitor/unknown codes: list lines with alphanumeric codes containing `-` (e.g. `17783-79-3000`, `MTX-4409-XQ`) plus an optional brand prefix. Each becomes its own row with `Lookup Status = Not found` and Notes "Competitor part number – not a Ferguson ID; not searched (competitor finder not in scope)".
- **Anti-hallucination rule:** every extracted token must appear verbatim in the source text. No LLM in extraction.

### 2. Product lookup (live → cache → catalog) and bot blocking
Order per ID: **Redis cache → live ferguson.com → backup catalog → Not found**.
- **Live:** Playwright `connect_over_cdp("http://127.0.0.1:9333")` to the user's **real Chrome** (as the guide requires: `chrome --remote-debugging-port=9333`). A real browser profile with real cookies is the legitimate and most robust way around bot blocking. No captcha solving or fingerprint tricks.
  - Shared browser, **global rate limiter in Redis** (max 1–2 concurrent ferguson.com tabs across all workers, 2–5 s jitter between page loads). Parallel jobs therefore don't trigger a block together.
  - Open the product URL `https://www.ferguson.com/product/.../<id>.html` via search `https://www.ferguson.com/search?q=<id>` (or the catalog's `Ferguson URL`). Parse JSON-LD / embedded state / spec table (exact selectors are confirmed during implementation on a live page and saved as fixture HTML for tests).
  - **Block detection:** HTTP 403/429, "Access Denied", captcha/challenge markers, empty spec table, or a timeout above 20 s. Then retry once with backoff, then fall back to the catalog. Notes record "live blocked → catalog used".
  - "Live wins": if live and catalog differ, use the live value and write the difference to Notes.
- **Catalog:** `product_catalog.json` (keyed by `product_id`). Sources rows come 1:1 from `product_catalog_sources.csv` (source_type, confidence, source). The CSV covers all 56 products, so email 1 is reproduced exactly.
- **Spec PDF:** if a link exists in `spec_sheet_links.csv`, download it (cache by URL) and extract text. Use it only to fill **blank** fields, with source_type `spec_sheet` and the PDF URL. Code regexes run first; an optional LLM extraction must return the **verbatim quote** from the PDF, otherwise the value is dropped.
- **Cache:** Redis `lookup:{id}` (24 h TTL), `pdf:{url}` (7 d), `blocked:ferguson` (cool-down flag after repeated blocks, so jobs go straight to the catalog for N minutes).
- `--offline`: catalog and PDFs only (tests, Azure).

### 3. Fill the RFQ (`fill_rfq.py`)
- Copy the template. One row per requested ID in request order. Found rows get values, `Image = =IMAGE("<url>")`, `Picture = url`, `Lookup Status = Found`. **Not found** rows keep only `product_id` and `Lookup Status = Not found`, with all spec columns blank.
- Every filled value gets a Sources row. Blank stays blank.
- Add a Notes sheet (as in the reference): duplicates, live/catalog differences, block fallbacks, competitor codes.

### 4. Agentic arm: RFQ Quality Agent + Summary (`rfq/quality/`)
Runs on the finished `RFQ.xlsx`. **Flag, never overwrite** (cell values stay unchanged).
- **Code: unit standardization.** Parse Length→ft, Width→in, Thickness→mil, Weight→lb (`1000`, `1000 ft`, `333.33 yds.`, `6"`, `3 in`). If a value isn't already in the standard form, flag it orange "non-standard unit: `333.33 yds.` = 1000 ft". The normalized value goes **only into the Summary flag text**, not the cell. (If cell normalization is wanted later, this stays a single switch.)
- **Code: missing values.** Blank cell in a Found row → grey + flag "missing – no source had this value". Not-found row → one flag per product "product not found on ferguson.com live or in backup catalog" (not 20 grey cells).
- **Code: format/plausibility.** Width > 24 in, Length not in {100…3000 ft}, Thickness not in mil, Price/Weight not numeric, Picture URL ≠ the Image formula URL, and so on. These are orange flags.
- **LLM (OpenAI, JSON schema output):** contradictions per row, e.g. Application "Gas" vs Lettering "…Water Line…", Color vs Lettering, Description "3 in" vs Width "6 in". The prompt gets only the row's cell values and must answer `[{cell, column, reason}]`. Validate: the cell exists and the column is in the row, otherwise discard. The LLM never supplies values. Timeout/error → code checks still run and Summary records "LLM check skipped: <reason>".
- **Summary sheet:** overall fill rate · fill rate per column · fill rate per product · **"Not found" section** (ID, raw text from the email, reason, sources tried) · **"Missing fields" section** per product (which columns no source provided) · complete flag list `cell | product_id | column | type (missing/suspicious/not_found) | check (code/llm) | reason`.
- Colors: grey `D9D9D9` = missing, orange `F8CBAD` = suspicious.

### 5. reply.eml
Short text: "N of M products found; X not found (list); fill rate Y %; Z flags — see Summary sheet", with RFQ.xlsx attached. Compatible with `mailbot.make_reply`, which replaces the headers.

### 6. Backend (FastAPI + Postgres + Redis + arq)
- **Tables:** `jobs`(id uuid, source [extension|paste|upload|mailbot], subject, sender, gmail_msg_id, body_text, raw_eml (bytea), status [queued|running|needs_review|ready|sending|sent|failed], version (int), poc_email, sent_at, sent_message_id, phase, progress 0–100, eta_seconds, error, result_xlsx_path, summary_json, created/started/finished_at), `job_items`(job_id, position, raw_token, product_id, kind [ferguson|competitor], qty, lookup_status, lookup_source [live|cache|catalog|none], notes), `job_events`(job_id, ts, phase, message), `rfq_cells`(job_id, product_id, column, value, source_type, confidence, source; this is the editable truth the xlsx is regenerated from), `job_edits`(job_id, cell, old, new, note, user, ts).
  - HITL endpoints: `GET /api/jobs/{id}/sheet`, `PATCH /api/jobs/{id}/sheet` (batch of cell edits + `version`), `POST /api/jobs/{id}/recheck`, `POST /api/jobs/{id}/send` (`{to, cc?, subject, body, confirm_incomplete, idempotency_key}`).
- **API:**
  - `POST /api/jobs` (JSON: `raw_eml_b64?`, `subject`, `sender`, `body_text`, `gmail_msg_id?`), returns `{job_id, url}`. Idempotent per `gmail_msg_id`, so a double click doesn't run twice.
  - `POST /api/jobs/upload` (multipart .eml) and paste text through the same endpoint.
  - `GET /api/jobs`, `GET /api/jobs/{id}` (incl. items + summary), `GET /api/jobs/{id}/events` (**SSE**), `GET /api/jobs/{id}/rfq.xlsx`, `GET /api/jobs/{id}/reply.eml`.
  - CORS for the frontend origin and `chrome-extension://<id>`. Simple shared API key header for the extension.
- **Worker (arq):** `run_rfq_job(job_id)` → `rfq.pipeline.run(..., progress_cb)`. `max_jobs=4` per worker; scale by starting more `arq` processes. Jobs are independent; only ferguson.com access is throttled globally. `job_timeout=900`, 1 retry on crash, `status=failed` + error in the UI.
- **Phase + ETA:** the pipeline reports phases `Parsing email → Extracting IDs → Looking up products (k/n) → Reading spec sheets → Filling RFQ → Quality checks → AI contradiction check → Writing summary → Done`. ETA = Σ(remaining steps × moving average of that stage's duration), with averages stored in Redis per stage (live lookup ≈ 6 s, catalog ≈ 0.01 s, PDF ≈ 2 s, LLM ≈ 8 s as start values). Shown as "≈ 1 min left".
- Run locally: `docker compose up -d` (postgres, redis). API (`uvicorn`) and worker (`arq`) run **natively**, because Chrome CDP only accepts localhost.

### 7. Frontend (React + Vite + TS)
**Screens**
- **Jobs list:** subject, sender, source icon, status badge, current phase, progress bar, "≈ 40 s left", created time. Live updates over SSE.
- **Job detail:** left pane shows the **email as received** (subject, from, date, body; the extracted IDs highlighted in the text). Right pane shows the items table (ID, kind, status Found/Not found, source live/catalog, qty), the Summary (fill rates, Not-found list, flags), the event timeline and download buttons.
- **New job:** a textarea to paste the email body (+ subject) and a .eml upload.
- **Review & edit (HITL)** and **Send to POC**: see §9.

**Design system: Ferguson brand, not a generic AI look**
- Source of truth: the Ferguson Brand Connect guide (https://brandconnect.ferguson.com/guidelines/guide/173422f5-b7f3-41e3-b594-dea52e03a1ac/page/8791fcc7-76da-46e9-a737-8575ea4e31da). That page is a login-gated JS app and returned no content to automated fetching. **Action for the user:** export or screenshot the Color, Typography and Digital/UI pages, or paste the hex values and font names. Until then, tokens are taken from the public ferguson.com CSS (computed styles inspected during implementation) and marked `// TODO verify vs Brand Connect`.
- All colors, type, spacing and radius live in **one** file, `frontend/src/theme/tokens.css` (CSS variables) + `tokens.ts`. Components never hard-code colors.
- **Banned:** purple/violet gradients, any gradient backgrounds, glassmorphism, neon glow, emoji icons, sparkle "✨ AI" badges, oversized rounded cards with drop shadows, the default shadcn/Tailwind demo look.
- **Style:** flat, dense, enterprise data UI. White/light-grey surfaces, Ferguson navy/blue as the primary color, one accent only for actions, small radius (2–4 px), 1 px borders, tabular numbers, high contrast (WCAG AA), visible focus rings, status colors only for status (found/missing/suspicious matches the Excel grey/orange).
- **Component structure:** `src/components/ui/` (Button, Badge, ProgressBar, Table, Modal, Toast, EmptyState: small, brand-styled, no UI kit), `src/features/jobs/`, `src/features/review/`, `src/features/send/`, `src/api/` (typed client + SSE hook), `src/hooks/`, `src/theme/`. Every feature folder is self-contained: components, hooks, types, tests.

### 8. Gmail extension (Chrome MV3)
- `content.js` on `https://mail.google.com/*`. Toolbar click (or an injected "Send to RFQ" button in the message header) triggers the flow:
  1. Find the open message's ID (`[data-legacy-message-id]` / `data-message-id`) and the `ik` from the page.
  2. **Primary:** same-origin `fetch("/mail/u/N/?ik=…&view=om&permmsgid=msg-f:<id>")` returns the **raw MIME**, including xlsx attachments, so email 2 works too.
  3. **Fallback:** DOM text (subject `h2.hP`, sender, body `.a3s`) when raw fails. The UI then shows "attachments not included".
  4. `background.js` POSTs to `{backendUrl}/api/jobs` and opens a frontend tab `…/jobs/{id}`. The popup shows the last jobs and their status.
- Settings in `chrome.storage`: backend URL, API key. Gmail DOM selectors are fragile, so they live in one place and are verified during implementation.

### 9. Human-in-the-loop review, Excel editing and sending to the POC
**Flow:** job `done` → status `needs_review` → the sourcing team edits → `ready` → Send → `sent`.
- **Grid editor:** the RFQ sheet rendered in an editable grid (**AG Grid Community**, MIT license, keyboard/paste support, virtualized). Cells are color-coded like the Excel: grey = missing, orange = flagged, and Not-found rows are marked. Filter "show only missing/flagged". Hovering a cell shows its source (Sources row) and flag reason.
- **Editing rules:**
  - The `product_id` and `Lookup Status` columns are read-only. Image/Picture can only be changed as a URL.
  - Every edit requires an optional **source note** (e.g. "Supplier quote 16 Oct"). It is stored as a Sources row `source_type=manual_edit, confidence=high, source="<user> on <ts>: <note>"`. The automated values are kept in history (edit log table `job_edits`: cell, old, new, user, ts).
  - Per-column validation: units (Length ft, Width in, Thickness mil, Weight lb), numbers, a pipe list for ASTM/Application, and URLs. Invalid input is rejected inline.
  - **Autosave with debounce** (PATCH per cell batch) and **optimistic concurrency** (`version` per job, 409 → reload hint), so two team members don't overwrite each other.
  - After saving, the **code quality checks rerun** at once (fast). The LLM check only runs on demand ("Re-check"). The Summary and fill rate update live.
  - Not-found rows can be filled by hand (Lookup Status becomes `Manual`) or removed with a required reason (recorded in Notes; never deleted silently).
- **Excel regeneration:** the xlsx is always regenerated from DB state + template (Sources, Notes, Summary, highlighting), so the UI and the file can't drift apart. Versioned files: `RFQ_v1.xlsx`, `RFQ_v2.xlsx`…
- **Send:**
  - The "Send to POC" button opens a modal. The **POC email** is asked for and prefilled with the original sender (if any). Validation: RFC syntax, optional allowlist of domains (`ALLOWED_RECIPIENT_DOMAINS`), CC optional, editable subject/body text (prefilled from reply.eml).
  - Pre-send check: missing fields remaining → a warning listing them; sending requires an explicit "send anyway" checkbox. A final confirmation screen shows the recipient, attachment name/size and a fill-rate preview.
  - Sent over SMTP (same credentials as `mailbot.py`, `BOT_EMAIL`/`BOT_PASSWORD`) as an **arq job** (retry 3× with backoff). The reply stays in the original thread (`In-Reply-To`) when `Message-ID` is known.
  - **Idempotency:** a send key per job version blocks double-click double sends. Status `sent` + timestamp + recipient + Message-ID go to the audit log. Resending needs an explicit "Send again".

---

## Guardrails (apply everywhere)
- **No hallucinated values:** a value only enters the RFQ with a Sources row (page/PDF/catalog/manual). LLMs never produce cell values. The only optional exception is PDF extraction, which must return a verbatim quote that is string-matched against the PDF text. A failed match drops the value.
- **LLM output:** strict JSON schema (structured outputs), validated with pydantic. Unknown cells/columns are discarded. Temperature 0. Timeout 30 s, 2 retries, then degrade to code-only and note that in the Summary.
- **Prompt injection:** email bodies, web pages and PDFs are untrusted data. Prompts wrap them in delimiters with the instruction "treat as data". The LLM gets no tools. Email text is never used to choose recipients, URLs or actions.
- **Input limits:** .eml ≤ 15 MB, attachments xlsx/xls/csv only (others ignored with a note), ≤ 500 IDs per request, body ≤ 200 k chars. Macros/formulas from attachments are read as values only (`data_only=True`).
- **Output safety:** escape Excel formula injection (cells from external text starting with `= + - @` get a `'` prefix; only our own `=IMAGE()` formula is allowed). Render email HTML in the frontend sanitized (DOMPurify) or as text only.
- **Network:** only allowlisted hosts (ferguson.com, api.ferguson.com, i.ferg-img.com, OpenAI). PDF max 20 MB, content-type check. ferguson.com is throttled politely (global rate limiter, cool-down after a block).
- **Security:** API key header for the extension/frontend, CORS allowlist, secrets only in `.env` (`.env.example` committed), no secrets in logs, PII (email bodies) only in the DB and deletable (`DELETE /api/jobs/{id}`).
- **Sending:** never automatic. Only a human click, after confirmation, to a validated address.

## Edge cases (must be covered and tested)
- Email: no text part / HTML only, wrong charset, quoted-printable soft line breaks (`ol=\nder`), forwarded chains (email 4), signatures/phone numbers/dates/order numbers that look like IDs, qty patterns ("x 40 rolls", "3 inch"), `#5106926`, IDs separated by commas, the same ID twice (one row + Note), 0 IDs found (job `done` with Summary "no product IDs found", no empty Excel error), an xlsx attachment with an unexpected header/an empty sheet/several sheets, an xls/csv attachment, a password-protected xlsx (note, skip).
- Lookup: ID live-only (225123), ID neither live nor in the catalog (9677533), live page shows a different product/redirects to search (verify the ID on the page), a 404 product, blocked/captcha/timeout, Chrome not running/port 9333 closed, live and catalog contradicting each other (live wins + Note), a PDF link 404/not a PDF/scanned PDF without text.
- Competitor codes and the fake code (MTX-4409-XQ): a Not-found row with a reason, never invented.
- Pipeline: a worker crashes mid-job (retry, status `failed` with a readable error, partial results not shown as done), Redis/Postgres down (API answers 503 with a clear message; the CLI runs without Redis), the OpenAI key is missing (code-only mode).
- Extension: Gmail in a different account `u/1`, conversation view with several messages (use the one that is open/expanded and last), raw fetch fails (DOM fallback + note "attachments not included"), backend unreachable (popup error + retry), double click (idempotent per gmail_msg_id).
- HITL: concurrent edits (409), edit after `sent` (new version, the old one stays immutable), an invalid email address, an SMTP auth error (shown in the UI, job stays `ready`).

## Fallback chain (overview)
| Stage | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|
| Email in | raw MIME (extension) | DOM text | manual paste / .eml upload |
| Product data | Redis cache | live ferguson.com (CDP) | catalog → `Not found` + reason |
| Spec PDF | cache | download | skip + Note |
| Quality LLM | OpenAI | retry ×2 | code-only checks + Summary note |
| Progress UI | SSE | polling every 3 s | — |
| Send | SMTP job | retry ×3 | error in UI, manual download of RFQ.xlsx |

## Optimizations
- **Parallelism:** independent jobs on arq workers. Inside a job, catalog lookups run in batches (O(1) dict). Live lookups and PDF downloads run concurrently with `asyncio.gather` behind the global ferguson.com semaphore. Spec PDFs load in parallel with live lookups.
- **Caching:** Redis lookup cache (24 h), PDF cache (7 d, keyed by URL + ETag), LLM result cache keyed by a hash of row values (the re-check after edits only re-asks changed rows), the catalog loaded once per worker process (module singleton).
- **Short-circuit:** the cool-down flag after blocks skips live lookups; IDs found in the cache skip Chrome entirely; offline mode never opens Chrome.
- **Fewer LLM calls:** one call per batch of rows (≈ 10 rows/call) instead of per row, only for rows with filled values, small model for checks (configurable `OPENAI_MODEL`).
- **DB/API:** indexes on `jobs(status, created_at)`, `job_items(job_id)`. Progress updates are throttled (max 2/s per job) to pub/sub. The xlsx is written by streaming. Downloads use `FileResponse`.
- **Frontend:** route-level code splitting (the grid only loads on the review page), a virtualized grid, React Query cache, SSE instead of polling.

---

## Implementation order (each step testable)
0. Write `spec.md` from this prompt; set up `requirements.txt` and `.env.example` (`OPENAI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `CHROME_CDP_URL`, `API_KEY`).
1. `parse_email` + `extract_ids` with tests for all 4 emails (expected ID lists, duplicate, competitor codes).
2. `lookup/catalog` + `fill_rfq` + `build.py --offline` → **email 1 matches the reference cell by cell** (RFQ + Sources).
3. `reply.py`, then `mailbot.py --offline` runs without changes.
4. Quality Agent (code checks → Summary → highlighting), then the LLM check with fallback.
5. `lookup/live` via CDP + block detection + Redis cache/rate limiter; check live against `225123`.
6. Spec-PDF filler (blanks only, verbatim source).
7. Backend (models, API, arq worker, SSE, ETA).
8. Frontend: design tokens (Ferguson) → UI primitives → jobs list/detail.
9. HITL: grid editor, edit log, regenerate xlsx, send modal + SMTP job.
10. Extension.
11. README (architecture diagram, setup, screenshots). Azure (`function_app.py`, route `/rfq`, offline, `/tmp`) is a later phase and stays a thin wrapper around `rfq.pipeline`.

## What you need to provide / do
- `OPENAI_API_KEY` in `.env`; Docker Desktop (Postgres/Redis); Node 20+; Python 3.11+.
- Start Chrome with `--remote-debugging-port=9333 --user-data-dir=<profile>` and visit ferguson.com once by hand (cookies, any challenge).
- Load the extension as unpacked in Chrome (`chrome://extensions` → Developer mode).
- Optional: BOT_EMAIL/BOT_PASSWORD for `mailbot.py`.

## Verification
- `pytest`: email 1 offline matches `reference/email-1 reference output.xlsx` (RFQ + Sources cell by cell). Email 2 has 8 rows, `225123` = Not found offline. Email 3 has 4 Found + 3 Not found (competitor). Email 4: `5106926` once + Notes duplicate, `9677533` + `17774-79-3000` = Not found.
- Quality Agent: no RFQ cell value changes (hash compare before/after). Summary has fill rates + a Not-found section. Grey/orange fills are present. Monkeypatching an OpenAI error → Summary shows "LLM check skipped" and code flags remain.
- Live: with Chrome on 9333, `python rfq/build.py emails/email-2-ids-in-attachment.eml --out out` → `225123` Found (live). With Chrome closed, the catalog fallback runs and Notes says why.
- Parallelism: submit 4 jobs at once → all 4 show `running` at the same time and a slow live job doesn't block the catalog-only jobs.
- Edge-case suite: a pytest fixture email per edge case listed above (HTML-only, 0 IDs, broken xlsx, formula injection `=HYPERLINK(...)` in the body…).
- HITL: edit a missing Weight → grey disappears, a Sources row `manual_edit` exists, fill rate goes up, the downloaded xlsx contains it. Two concurrent PATCHes with the same version → one gets 409. Send with an invalid address → 422. A double click on Send → exactly one email (check with a local SMTP sink such as `aiosmtpd`/MailHog).
- Design review: no gradients/purple anywhere (grep CSS for `gradient`, `#7c3aed`-like hues); all colors come from tokens.
- E2E: open an RFQ email in Gmail → click the extension → the frontend shows the email, phase and ETA → download RFQ.xlsx.


---

## Implementation notes (where the build differs from the text above, and why)

- **Editable RFQ storage:** instead of a separate `rfq_cells` table, the sheet is one JSONB document on `jobs.sheet` plus an integer `jobs.version`. A single versioned document makes optimistic locking atomic (one conditional UPDATE). Every change is still logged per cell in `job_edits`. Sends are audited in their own `job_sends` table (idempotency key, attempts, Message-ID).
- **Email rendering:** the web app always renders the email as plain text (never as HTML), so DOMPurify is not needed. Extracted product tokens are highlighted with React elements, not injected HTML.
- **Sources for Description:** the reference output has no Sources row for `Description`. Because "every value has a source" is a hard rule, we add one (catalog / product page). The test checks that the Sources sheet equals the reference apart from these rows.
- **Spec-sheet extraction** is code-only (regex) with a "single stated value" rule. Family sheets list several values, so the optional LLM PDF extraction was not added; this keeps the "never guess" rule simple to verify.
- **Formula injection:** external text is always written as a string cell (data type `s`), so a leading `-` (e.g. `-60 to 250 Deg F`) keeps its value exactly as in the reference. Only our own `=IMAGE("https://…")` is a formula. Human edits that start with `= + @` are rejected.
- **Gmail extension:** the toolbar button (popup) triggers the send. No button is injected into Gmail's own toolbar, which keeps it robust against Gmail markup changes.
- **Resilience added beyond the spec:**
  - `backend.app.run_worker` restarts arq when Redis drops.
  - A cron sweep (every minute and at start-up) re-queues jobs saved while Redis was down, and jobs left running by a dead worker.
  - Jobs and sends are claimed with atomic UPDATEs.
  - Creating a job never fails just because the queue is down: it is saved and starts later.
- **docker-compose** only starts Postgres + Redis. The API and worker run on the host because Chrome's debugging port only accepts local connections.
- **AI prompt:** the APWA colour code is in the prompt, and the model is told to flag the odd value out (it first blamed the consistent colour instead of the wrong Application).

### Round 2 (2026-10-16): SerpApi first, rate limit, supplier info, source links, branding
- **Lookup order:** SerpApi (Google `site:ferguson.com "<id>"`, exact product URL match only) → ferguson.com product page via Chrome → catalog → Not found. SerpApi has no spec table, so the page is read only when SerpApi isn't usable or found nothing, or when the catalog lacks the product (`SCRAPE_AFTER_SERPAPI=missing|always|never`). A used-up quota (429 / "run out of searches") or a rejected key pauses SerpApi for an hour (Redis flag `serpapi:exhausted`) and the run falls back to scraping, with a warning.
- **Rate limit:** `FERGUSON_RATE_PER_MINUTE` (default 12): a Redis sliding window shared by all workers plus about 5 s spacing. Spec-sheet PDFs on api.ferguson.com use the same budget. The time-left estimate never assumes a page faster than 60/limit seconds.
- **Supplier info:** `Row.supplier` holds sourced cells (Supplier, Brand, Manufacturer Part #, Ferguson Part #, UPC, Price (USD), Availability, Product page, Spec sheet) and is shown on a new Supplier sheet. Precedence: live page > SerpApi > catalog.
- **Source links:** `Cell.url`. The Sources sheet gets a 7th `link` column with real hyperlinks (http(s) only), and supplier values are listed as `Supplier: <column>`. A URL named in a catalog source text is used as its link (e.g. a sibling's family spec sheet). Rules get no link.
- **Branding re-checked on ferguson.com:** utility bar `#03324C`, header `#00446A` (`bg-brand-md`), actions `#1379C8`, ink `#0A2433`, system fonts. The real `ferguson-light.svg` logo is used in the web app and the extension. The favicon and extension icons are made from the logo's symbol.
- The API key for SerpApi is kept out of logs (httpx INFO logging, which prints full URLs, is turned off in the worker).

### Round 3 (2026-10-16): review/re-check fixes, Excel upload, mail errors, SerpApi live
- **Re-check race:** `recheck()` stored AI results computed from the sheet it read at the start, even if an edit landed during the AI call. Now the report is saved only with `WHERE version = <checked version>`; otherwise it re-runs on the newest version (up to 3 tries, then 409). The web app pauses editing during a re-check and ignores responses older than what's on screen.
- **Review state:** `POST /review?done=&version=` is tied to the version the reviewer saw (409 if stale) and logs "Reviewed by <user>". An edit to a reviewed RFQ logs "Review reopened". The web app has one review control and a single Send button.
- **Workbook order:** RFQ is the first and active sheet (RFQ, Supplier, Summary, Sources, Notes, How to fill), plus a hidden `_rfq_meta` sheet (job_id, version).
- **Excel upload:** `POST /api/jobs/{id}/sheet/import` returns a preview only (`rfq/excel/importer.py`): file and column checks, job match, a three-way compare against the downloaded version (conflicts), per-cell validation, and row checks. Changes are applied through `PATCH /sheet` with "Uploaded Excel '<file>'" as their source.
- **Mail:** smtplib's `login()` retried a second auth method after Gmail had already hung up, hiding the real `535 BadCredentials` behind "Connection unexpectedly closed". Now there is a single AUTH attempt, Google's message and a hint are shown, auth failures are not retried, and `POST /api/mail/test` checks the login without sending anything.
- **SerpApi live:** `SERPAPI_TIMEOUT_S` (default 45 s) and up to 8 parallel searches.

### Round 4 (2026-10-16): SQLite, database search, summary download, embedded pictures
- **Database:** Postgres → SQLite (`sqlite+aiosqlite`, WAL, busy_timeout 30 s, foreign_keys on). The models only use portable types (`JSON`, `Uuid`, a `UTCDateTime` type that stores naive UTC and returns aware UTC). Data was migrated with `scripts/migrate_pg_to_sqlite.py` (24 jobs, 131 items, 195 events, 21 edits, 7 sends; counts verified).
- **Search:** `GET /api/jobs` (q / subject / sender / product / status / source / created_from / created_to / sort / page / page_size → `{items, total, page, page_size, pages}`), `GET /api/jobs/facets` (all options + labels + counts) and `GET /api/jobs/suggest`. LIKE input is escaped, enums are allow-listed, and the URL holds the filters.
- **Header:** the white-on-white field was "Your name" (inputs inherited the navy header's white text). It is now a real search with database suggestions; the name moved to the utility bar, and `.input` always uses ink-coloured text.
- **Pictures:** embedded thumbnails in the Image cells (`rfq/excel/images.py`; Ferguson CDN only, cached, with type/size/pixel guards), and Picture is a hyperlink. Image follows Picture in edits and uploads. For multi-URL values (`a|b`), the primary one is used. The cell values are unchanged, so the reference still matches.
- **Summary download:** `GET /api/jobs/{id}/summary.xlsx` (Summary + Notes).
- **Accessibility:** explicit `<label for>` on the filter fields (wrapping labels gave each select the option texts as its name) and valid element IDs (React's `useId()` returns `:r1:`).

### Round 5 (2026-10-16): download/upload formats and Excel colours
- **Colours:** one palette (`rfq/excel/palette.py`). RFQ sheet: missing grey, suspicious orange (with an Excel comment holding the reason), manual edits blue, not-found row tint, coloured Lookup Status. Supplier and Sources: coloured status and confidence. The Summary legend lists every colour. Values are unchanged (the reference still matches).
- **Downloads:** `rfq/excel/exports.py`. `.xlsx` (master), `.xls` (converted from the `.xlsx` with xlwt: same values and colours, custom palette, hidden meta sheet kept, `IMAGE()` → URL, 32 767-character / 65 536-row limits guarded) and `.csv` (UTF-8 BOM, CSV-injection guard, Review notes column). `GET /api/exports/formats`, `GET /api/jobs/{id}/export`. The old `rfq.xlsx` / `summary.xlsx` routes use the same code.
- **Uploads:** `importer.load_table()` reads .xlsx/.xlsm (openpyxl), .xls (xlrd, version stamp kept) and .csv (sniffed delimiter, utf-8-sig/cp1252, strips our `'` guard, which is then refused by validation if it was a formula). Every format goes through the same three-way compare and validation.

### Round 6 (2026-10-16): compact UI, dropdowns, removing rows
- **Compact layout:** smaller header (28 + 52 px), page/card/table/button spacing tightened, 1600 px page width. Detail page: Download ▾, Send, and a **More ▾** menu (upload edited file, hide/show the email, delete). The email panel can be hidden (remembered per browser). The grid is as tall as its rows, capped by the viewport.
- **Dropdowns:** a shared `Menu` component (`components/ui/Menu.tsx`, rendered into `<body>` so it is never clipped, keyboard support). Review toolbar: **Show** dropdown replaces the "only issues" checkbox. Requests list: one row with search, status, received preset and sort; the rest behind **More filters**. Date presets come from `GET /api/jobs/facets` → `date_presets`.
- **Dropdown cell editors:** `ChoiceEditor` (AG Grid custom popup editor). `GET /sheet` returns `options` per column, built by `rfq.validation.column_options()` from this RFQ's values plus `catalog.column_values()`: `choices` (strict, from `validation.CHOICES`, e.g. UL Listed Yes/No; validation uses the same table) or `suggestions` (only values that pass validation; list columns also offer single items). Free-text columns (Description, Product details, Image, Picture) have none.
- **Removing rows:** ⋯ menu on every row (open product page / spec sheet / remove) and multi-select checkboxes with a bulk **Remove N rows…** bar. Uses the existing `remove_rows` PATCH (reason required, Notes + edit log), now with several rows at once; warns when it would empty the RFQ.
- **Bug fixed:** double-click editing in the grid did nothing once a cell had been clicked. Inline `rowClassRules`/`rowSelection`/callback props were new objects on each render, so the grid refreshed its rows between the two clicks. All grid props are now stable (`useCallback`/`useMemo`/module constants).
- Verified in headless Chrome against the live API: dropdown pick saves a new version, strict list shows Yes/No, Escape cancels without saving, row menu and bulk remove work, popups float over the page, no console errors, no horizontal scroll at 390 px. Tests: 122 passed.
