# Ferguson RFQ Agent

Turns an RFQ request email into a filled, sourced RFQ workbook, then lets the sourcing team review it, edit what is missing and send it to the point of contact.

- **Base (Part A):** email → product IDs → **SerpApi (Google) first** → ferguson.com product page (your own Chrome, **max 12 page loads/min**) → backup catalog → spec sheet PDFs → `RFQ.xlsx` (Summary, RFQ, **Supplier**, Sources with **links**, Notes) + `reply.eml`.
- **Agentic arm (Part B, option 2): RFQ Quality Agent.** It standardizes units, marks missing cells grey and suspicious ones orange, runs an AI contradiction check, and adds a **Summary** sheet with fill rates and a list of what was *not* found and why. It **flags only and never overwrites a value**.
- **Product around it:** a Gmail Chrome extension, a FastAPI backend with Postgres + Redis + arq workers (jobs run in parallel), and a React web app. The web app shows each email, its live phase and the approximate time left, and has an Excel-like editor (human in the loop) and a **Send to POC** flow.

Ground rules enforced everywhere: blank means unknown, every value has a row on the Sources sheet, nothing is guessed, and every requested ID stays on the sheet (as `Not found` when needed).

## Architecture

```
Gmail tab ──(extension: raw MIME, or visible text as fallback)──┐
Web app ──(paste body / upload .eml)────────────────────────────┼─► FastAPI ──► Postgres (jobs, items, edits, sends)
mailbot.py ──(unchanged)──► rfq/build.py (CLI)                   │       └─► Redis queue ──► arq workers (N × 4 jobs)
                                                                 │                              │
                                                rfq.pipeline.run()  ◄── one core for CLI, worker and (later) Azure
                                                                 │
     parse email → extract IDs → lookup: cache → SerpApi (Google) → ferguson.com page (CDP :9333, 12/min) → catalog → Not found
                 → spec sheet PDFs (blanks only) → RFQ + Sources + Notes → Quality Agent → Summary → reply
                                                                 │
Web app ◄── Server-Sent Events (phase, %, time left) ◄── Redis pub/sub
Web app ── edit cells (versioned, validated) → re-check → regenerate RFQ_vN.xlsx → Send (SMTP job, idempotent)
```

| Folder | What it is |
|---|---|
| `rfq/` | The core flow: `parse_email`, `extract_ids`, `lookup/` (live, catalog, specsheet, cache, resolve), `excel/` (writer, reader), `quality/` (units, checks, llm_checks, summary, agent), `reply`, `pipeline`, `build.py` (CLI) |
| `backend/app/` | FastAPI (`main`, `api/`), services (`jobs`, `sheet` = human-in-the-loop, `mail`), `worker` (arq), `run_worker` (restarts the worker if Redis drops) |
| `frontend/` | React + Vite + TypeScript. Design tokens in `src/theme/tokens.css`, primitives in `src/components/ui/`, features in `src/features/{jobs,review,send}` |
| `extension/` | Chrome Manifest V3 extension for Gmail |
| `tests/` | 78 pytest tests: email 1 equals the reference, emails 2–4, edge cases, live-page parsing (saved fixtures), quality agent, backend API |
| `spec.md` | The spec this was built from (`prompt.md` is the same content as the original prompt) |
| `emails/`, `data/`, `templates/`, `reference/` | The starter kit: sample emails, backup catalog, RFQ template, the reference output for email 1 |

## Setup

Requirements: Python 3.11+, Node 20+, Postgres, Redis, Google Chrome. (Docker is optional: `docker compose up -d` starts Postgres and Redis.)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
createdb rfq                        # skip if you use docker compose
cp .env.example .env                # then fill in the values below
(cd frontend && npm install && cp .env.example .env.local)   # put the same API key in VITE_API_KEY
```

`.env` values:

| Key | Needed for |
|---|---|
| `API_KEY` | Shared by the web app and the extension. Use a long random string. |
| `SERPAPI_API_KEY` | SerpApi is tried first for every Ferguson ID. Empty, or quota used up → products are read from ferguson.com directly. |
| `FERGUSON_RATE_PER_MINUTE` | ferguson.com page loads per minute across all workers (default 12; spec-sheet PDFs count too). |
| `SCRAPE_AFTER_SERPAPI` | After a SerpApi hit, also open the product page? `missing` (default: only when the catalog lacks the product), `always`, `never`. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | AI contradiction check. Without a key, the code checks still run and the Summary says the AI check was skipped. |
| `BOT_EMAIL`, `BOT_PASSWORD` | Sending the RFQ (Gmail address + 16-letter **App Password**) and `mailbot.py` |
| `DATABASE_URL`, `REDIS_URL` | Defaults: local Postgres database `rfq`, Redis on 6379 |
| `RFQ_OFFLINE` | `true` = catalog and spec sheets only, never opens Chrome |
| `ALLOWED_RECIPIENT_DOMAINS` | Optional allowlist for the Send flow |

## Run

```bash
scripts/chrome.sh        # Chrome with remote debugging on 9333; open ferguson.com once in it
scripts/dev.sh           # API :8000, worker, web app :5173
```

Or one part at a time:

```bash
.venv/bin/uvicorn backend.app.main:app --port 8000
.venv/bin/python -m backend.app.run_worker          # start more of these for more throughput
(cd frontend && npm run dev)
```

**Gmail extension:** go to `chrome://extensions`, turn on Developer mode, click **Load unpacked** and choose `extension/`. In its Settings, enter the backend URL, web app URL and `API_KEY`, then click **Test connection**. Open an RFQ email in Gmail and click the extension button. The web app opens on that request.

**CLI (the Part A contract, used by `mailbot.py`):**

```bash
.venv/bin/python rfq/build.py emails/email-1-ids-in-body.eml --out out            # live + catalog
.venv/bin/python rfq/build.py emails/email-1-ids-in-body.eml --out out --offline  # no Chrome
.venv/bin/python -m rfq.quality.agent out/email-1-ids-in-body/RFQ.xlsx            # Quality Agent on any RFQ.xlsx
.venv/bin/python mailbot.py --offline                                             # answer the Gmail inbox
```

## How the important parts work

**ID extraction** is deterministic, with no LLM. Every token returned appears verbatim in the email. Ferguson IDs are 6–7 digits, also written as `#5106926`. Competitor codes are dashed or mixed codes such as `17783-79-3000` or `MTX-4409-XQ`. Before scanning, the extractor masks phone numbers, dates, PO and order numbers, URLs and e-mail addresses. A product listed twice is kept once and noted. Excel and CSV attachments are read as values only (never formulas or macros).

**Lookup order (SerpApi first).**
1. **SerpApi** searches Google for `site:ferguson.com "<id>"`. A hit is only accepted if its link is that exact product's page (`/product/…/<id>.html`). It gives the page URL and title, and usually the price and stock, without touching ferguson.com. Results are cached for 24 h to save quota.
2. **SerpApi gives no spec table.** So when the backup catalog has the product, its specs are used, and SerpApi's price and URL go on the Supplier sheet. When the catalog *doesn't* have it, the product page is read. If that fails too, only the Google title is kept and the specs stay blank (never guessed).
3. **If SerpApi isn't configured, its quota is used up (HTTP 429 / "run out of searches"), the key is rejected or it finds nothing**, the product page is read directly. A used-up quota pauses SerpApi for an hour for all jobs, and the run says so in its warnings.

**Supplier info and links.**
- **Supplier sheet:** supplier, brand, manufacturer and Ferguson part numbers, UPC, price, availability, product page and spec sheet links, and how each product was found.
- **Source precedence:** the live page wins over SerpApi, which wins over the catalog. Catalog prices date from 2026-09-24.
- **Sources sheet:** every value, including the supplier values (as `Supplier: <column>`), plus a 7th **link** column with a clickable hyperlink to the page or PDF it came from. Rule-based values have no single document, so they get no link instead of a made-up one.
- **In the web app:** a Sources tab, a Supplier table on the Summary, and a cell inspector in the editor, all with clickable links.

**ferguson.com blocking.** The lookup drives *your* Chrome profile over the DevTools protocol (port 9333), so the site sees a normal browser with normal cookies. On top of that it is polite:
- **at most 12 page loads per minute** (`FERGUSON_RATE_PER_MINUTE`), enforced across all workers by a Redis sliding window, plus about 5 s spacing so there are no bursts. Measured on a live run with two jobs at once: 17 calls, never more than 12 in any 60 s window. Spec-sheet PDFs (api.ferguson.com) share the same budget.
- images and fonts are not downloaded
- results are cached for 24 h
- block pages (HTTP 403/429, "Access Denied", captcha markers, pages without product data) are detected and retried once; after 3 blocks in 10 minutes there is a 10-minute cool-down

There is no captcha solving or fingerprint spoofing. When a lookup is blocked, the product comes from the backup catalog and the Notes sheet says so. A product that redirects away from `/<id>.html` is "not on ferguson.com". When the live page and the catalog differ, **live wins** and the difference is written to Notes.

**Spec sheets** describe whole product families ("2, 2.5, 3, 4 and 6 Mil"). So a spec sheet only fills a **blank** cell when the PDF states exactly one value for it, and it stores the verbatim quote as the source.

**Quality Agent.**
- **Code checks** always run:
  - units: Length ft, Width in, Thickness mil, Weight lb (`333.33 yds.` = 1000 ft)
  - missing cells
  - plausible ranges
  - the description's size or colour against the columns
  - the APWA colour code against the Lettering and Application
  - URL, Yes/No and number formats
- **AI check** (OpenAI, strict JSON schema, no tools, email and page text marked as untrusted data):
  - may only point at cells that already hold a value; anything else it returns is discarded
  - answers are cached per row
  - on a timeout or error, the code checks still stand and the Summary says the AI check was skipped

**Human in the loop.**
- The RFQ is stored as one versioned document, and every save needs the current version: two people can't overwrite each other (409).
- Typed values are validated: a number with its unit, Yes/No, URLs, no formulas. Each edit is saved with a `manual_edit` source row (who, when, the note) and goes into the edit log.
- The code checks re-run at once, and **Re-check with AI** re-runs the AI check. The workbook is regenerated as `RFQ_vN.xlsx`, and old versions stay downloadable.
- **Send to POC**:
  - asks for the email address (pre-filled with the requester)
  - warns when there are gaps, and needs an explicit "send anyway"
  - shows a confirmation screen before anything goes out
  - sends through SMTP as a background job, in the original thread
  - a double click never sends twice (idempotency key plus an atomic status change)

**Workers.**
- Each worker runs 4 jobs at once, and you can start more workers. A job is claimed with an atomic UPDATE, so it never runs twice.
- A job is retried once after a crash; a send is retried 3 times. If sending fails for good (for example a bad password), the job goes back to review with the error shown.
- `run_worker` restarts arq when Redis drops. A sweep every minute picks up jobs that were saved while Redis was down, or left behind by a dead worker.

## Verification (what was run)

- `pytest`: **94 passed**. Email 1 offline matches `reference/email-1 reference output.xlsx` cell by cell (RFQ sheet). The Sources sheet is identical too, plus one extra source row per product for `Description`, which the reference leaves unsourced. Emails 2–4 flag their not-found rows. The edge-case suite covers extraction, attachments, formula injection, lookup fallbacks, the Quality Agent with a failing or invalid AI answer, and the backend (auth, locking, validation, the send flow and its failures, recovery).
- **Live, through Chrome on 9333**, all 4 emails. 225123 and 9677533 (not in the catalog) were found live. Pages without JSON-LD are handled. Three jobs ran at the same time with live progress over SSE.
- **The AI check ran for real** with gpt-5-mini. It caught the Application-versus-Lettering contradiction in email 1 (5106891) and a "Non-Detectable" description with aluminium backing (9677531). Email 1 values were unchanged afterwards.
- **Human-in-the-loop flow in the browser:**
  - an edit autosaved and the grey flag cleared
  - an invalid value was rejected and reverted
  - stale-version and concurrent edits returned 409
  - a double click on Send delivered exactly one email (local SMTP sink), with the attachment `RFQ_v2.xlsx` and `In-Reply-To` set
- **Outages:**
  - Redis stopped: the API kept answering, and the CLI fell back to an in-memory cache
  - the worker was restarted by the supervisor, and jobs saved during the outage finished on their own
  - Chrome closed: catalog fallback with a warning
  - `mailbot.py` (unchanged) builds and replies through the new base

## Honest limits

- **Gmail extension:** the extraction logic was tested against a mocked Gmail page and the real backend. It was not tested inside a logged-in Gmail, because Chrome does not let tools load unpacked extensions. Gmail markup changes over time; all selectors are in one place (`SELECTORS` in `extension/gmail.js`). If "Show original" can't be read, it falls back to the visible text and says that attachments were not included.
- **SerpApi** has not been run against the real API yet: there's no key in `.env`. It is tested with recorded-shape responses and a mocked HTTP transport (hit, wrong product, truncated title, no results, quota used up, invalid key, caching). Add `SERPAPI_API_KEY` and check one live run.
- **Brand:** the header copies ferguson.com: the `#03324C` utility bar, the `#00446A` main header, the real white Ferguson logo (`ferguson-light.svg` from ferguson.com) and `#1379C8` actions. The extension icons come from the logo's symbol. The Brand Connect guide needs a login, so `frontend/src/theme/tokens.css` is marked *TODO verify*.
- **Competitor part numbers** become `Not found` with the reason "not searched". The web-search competitor finder (option 1) is not in this version.
- **Time left** is a moving average per kind of work. It starts rough and improves as jobs run; with many jobs competing for ferguson.com it can be optimistic.
- **Not built yet:** user accounts (one shared API key; the editor's name is entered in the header), and the Azure Function. `rfq.pipeline.run` is ready to be wrapped by `function_app.py` in offline mode.
