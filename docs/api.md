# API reference

Base URL `http://localhost:8000`. Every `/api/*` route except `/api/health` needs the shared key:
header `X-API-Key: <API_KEY>`, or `?key=` for links and Server-Sent Events. `X-User: <name>` puts the editor's
name in the edit log.

## Jobs
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/jobs` | Create a job. JSON: `source` (`extension`/`paste`/`upload`/`mailbot`), `raw_eml_b64` *or* `body_text` (+ `subject`, `sender`), optional `gmail_msg_id` (idempotent: the same id returns the existing job unless `force: true`). Returns `{job_id, url, created, queued}`. If the queue is down the job is saved with `queued: false` and starts automatically later. |
| POST | `/api/jobs/upload` | Create a job from a `.eml` file (multipart `file`, max 15 MB). |
| GET | `/api/jobs` | Search & list (database). Query: `q` (subject, sender, email body, product ID; every word must match), `subject`, `sender`, `product`, `status` (repeat or comma-separate), `source`, `created_from`/`created_to` (ISO 8601, UTC if no zone), `sort`, `page`, `page_size`. Returns `{items, total, page, page_size, pages}`. `%` and `_` are searched literally. |
| GET | `/api/jobs/facets` | Every filter option with label and live count: statuses, sources, sorts, page sizes, field labels, date range, `date_presets` (label + days back). The web app builds its filters from this. |
| GET | `/api/jobs/suggest?q=` | Up to 8 suggestions (product IDs, subjects, senders) for ≥ 2 characters. |
| GET | `/api/jobs/{id}` | Detail: email, items, report, notes, warnings, events, edits, sends. |
| POST | `/api/jobs/{id}/retry` | Re-queue a failed job. |
| DELETE | `/api/jobs/{id}` | Delete the job, its email and every RFQ version. |

## Review (human in the loop)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/jobs/{id}/sheet` | The editable RFQ: `version`, rows (cells with source + link, supplier), flags, report, `incomplete`, and `options` (per column: `choices` = the only allowed values, or `suggestions` = valid values already in use) for the grid's dropdowns. |
| PATCH | `/api/jobs/{id}/sheet` | `{version, edits: [{product_id, column, value, note}], remove_rows: [{product_id, reason}]}`. 409 if the version is stale; 422 with per-cell errors if a value is invalid (nothing is applied). Picture edits also update Image. |
| POST | `/api/jobs/{id}/sheet/import` | Preview an uploaded edited file (`.xlsx`, `.xlsm`, `.xls`, `.csv`; multipart `file`). Returns changes with status `ok` / `invalid` / `conflict`, errors and warnings. **Writes nothing.** Apply the chosen changes with PATCH. |
| POST | `/api/jobs/{id}/recheck` | Re-run code checks + the AI check; stored only for the version it checked. |
| POST | `/api/jobs/{id}/review?done=true&version=N` | Mark version N reviewed (or `done=false` to reopen). 409 if N is no longer current. |

## Downloads
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/exports/formats` | Download formats (`xlsx`, `xls`, `csv`) with descriptions, and accepted upload types. |
| GET | `/api/jobs/{id}/export?what=rfq\|summary&format=xlsx\|xls\|csv&version=N` | The RFQ or the Summary in that format (older versions are rebuilt from that version's file). |
| GET | `/api/jobs/{id}/rfq.xlsx`, `/summary.xlsx` | Shortcuts for the `.xlsx` downloads. |
| GET | `/api/jobs/{id}/reply.eml` | The reply email with the RFQ attached. |

## Sending
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/jobs/{id}/send` | `{to, cc[], subject, body, confirm_incomplete, resend, idempotency_key}`. Validates addresses (and `ALLOWED_RECIPIENT_DOMAINS`), requires `confirm_incomplete` when fields are missing, sends once per key (202). |
| POST | `/api/mail/test` | Log in to the mail server with `BOT_EMAIL`/`BOT_PASSWORD` and report the result. Sends nothing. |

## Live updates and health
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/jobs/{id}/events` | SSE for one job: snapshot, then `progress` (phase, %, time left), `status`, `sheet`, `done`. |
| GET | `/api/events` | SSE for the jobs list. The web app falls back to polling every 3 s if the stream drops. |
| GET | `/api/health` | `api`, `db`, `redis`, `queue`, `chrome`, `serpapi`, `ferguson_rate_per_minute`, `mode`, `sending` (no key needed). |

## CLI
```bash
python rfq/build.py <email.eml> --out out [--offline] [--no-llm] [--no-pdf] [--no-images]
python -m rfq.quality.agent <RFQ.xlsx> [--out checked.xlsx] [--no-llm]
python mailbot.py [--once] [--offline]
```
