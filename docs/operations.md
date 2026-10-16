# Operations: setup, running, troubleshooting

## Setup
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                      # fill in the keys (see the table)
(cd frontend && npm install && cp .env.example .env.local)   # VITE_API_KEY = API_KEY from .env
redis-server --daemonize yes --dir "$PWD/out"                # or: docker compose up -d
```
The database is a SQLite file (`out/rfq.sqlite3`), created on first start. No database server is needed.
Data from an older Postgres setup: `pip install asyncpg && python scripts/migrate_pg_to_sqlite.py postgresql+asyncpg://localhost/rfq`.

## Run
```bash
scripts/chrome.sh     # Chrome with remote debugging on :9333; open ferguson.com once in it
scripts/dev.sh        # API :8000 + supervised worker + web app :5173
```
Gmail extension: `chrome://extensions` → Developer mode → Load unpacked → `extension/` → Settings: backend URL,
web app URL, `API_KEY` → Test connection.

## Configuration (`.env`)
| Key | Default | Purpose |
|---|---|---|
| `API_KEY` | — | Shared key for the web app and the extension |
| `DATABASE_URL` | `sqlite+aiosqlite:///out/rfq.sqlite3` | Any SQLAlchemy async URL works |
| `REDIS_URL` | `redis://localhost:6379/0` | Queue, cache, live updates, rate limit |
| `SERPAPI_API_KEY` | empty | SerpApi lookups (empty → read ferguson.com directly) |
| `SERPAPI_TIMEOUT_S` | 45 | Wait for SerpApi before reading the page instead |
| `SCRAPE_AFTER_SERPAPI` | `missing` | After a SerpApi hit, read the page too: `missing` (only if not in catalog), `always`, `never` |
| `FERGUSON_RATE_PER_MINUTE` | 12 | ferguson.com page loads per minute across all workers (PDFs included) |
| `CHROME_CDP_URL` | `http://127.0.0.1:9333` | Your debug Chrome |
| `RFQ_OFFLINE` | false | Catalog + spec sheets only |
| `RFQ_USE_LLM` / `OPENAI_API_KEY` / `OPENAI_MODEL` | true / — / `gpt-5-mini` | AI contradiction check |
| `RFQ_EMBED_IMAGES` | true | Pictures inside the Excel |
| `BOT_EMAIL` / `BOT_PASSWORD` | — | Gmail address + 16-letter App Password for sending |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_SSL` | `smtp.gmail.com` / 465 / true | Mail server |
| `ALLOWED_RECIPIENT_DOMAINS` | empty | Optional allow-list for Send |
| `WORKER_MAX_JOBS` | 4 | Jobs in parallel per worker process |

## Health check first
`curl -s localhost:8000/api/health` reports db, redis, queue, chrome, serpapi, the rate limit and the mail setup.

## Troubleshooting
| Symptom | Cause → fix |
|---|---|
| `chrome: down`, products read from the catalog | Debug Chrome closed → `scripts/chrome.sh` |
| Jobs stay "Queued" | Redis or the worker is down → start Redis, run `python -m backend.app.run_worker` (never plain `arq`, which exits when Redis drops) |
| "SerpApi did not answer within 45 s" | Slow SerpApi → normal; the page is read instead. Raise `SERPAPI_TIMEOUT_S` if wanted. |
| "SerpApi quota used up" | Plan limit → paused for 1 h; scraping continues |
| "Sending failed: mail login rejected (535)" | Gmail refuses the App Password → create a new one for exactly `BOT_EMAIL` (2-Step Verification on). Check with **Test mail login** in the Send dialog. |
| Picture missing in the Excel | See Notes ("Picture not embedded…"); the Picture link still works |
| Upload says "different RFQ request" | The file was downloaded from another request |

## Tests
```bash
.venv/bin/python -m pytest -q tests          # core + backend (temporary SQLite, fake queue, fake SMTP)
(cd frontend && npx tsc -p . && npx vite build)
```
