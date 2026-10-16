# Architecture

How the RFQ Agent turns a sourcing email into a reviewed, sourced RFQ workbook. Diagrams are
[Mermaid](https://mermaid.js.org); GitHub renders them in place.

- [1. System overview](#1-system-overview)
- [2. From email to RFQ (the pipeline)](#2-from-email-to-rfq-the-pipeline)
- [3. Product lookup and fallbacks](#3-product-lookup-and-fallbacks)
- [4. The agentic arm: RFQ Quality Agent](#4-the-agentic-arm-rfq-quality-agent)
- [5. Job lifecycle](#5-job-lifecycle)
- [6. Gmail extension → live progress](#6-gmail-extension--live-progress)
- [7. Human in the loop: review, upload, send](#7-human-in-the-loop-review-upload-send)
- [8. Data model](#8-data-model)
- [9. Reliability and guardrails](#9-reliability-and-guardrails)

## 1. System overview

```mermaid
flowchart LR
    subgraph IN["Inputs"]
        direction TB
        GM["Gmail extension<br/>one click, raw MIME"]
        UI["Web app<br/>review · edit · send"]
        MB["mailbot.py<br/>inbox bot"]
    end
    subgraph BE["Backend"]
        direction TB
        API["FastAPI<br/>REST + SSE"]
        DB[("SQLite<br/>jobs · edits · sends")]
        Q[["Redis<br/>queue · cache · pub/sub<br/>rate limit"]]
    end
    W["arq workers<br/>N × 4 jobs in parallel"]
    P["rfq/ core<br/>pipeline.run()"]
    subgraph SRC["Data sources"]
        direction TB
        SERP["SerpApi (Google)"]
        FC["ferguson.com pages<br/>via Chrome :9333"]
        CAT["Backup catalog"]
        PDF["Spec sheet PDFs<br/>api.ferguson.com"]
        LLM["OpenAI<br/>contradiction check"]
    end
    POC["Point of contact"]

    GM -->|POST /api/jobs| API
    UI <-->|REST + live progress| API
    API --- DB
    API -->|enqueue| Q
    Q --> W
    W -->|progress events| Q
    W --> DB
    W --> P
    MB -->|rfq/build.py| P
    P --> SRC
    W -->|SMTP, only after a human clicks Send| POC
```

| Part | Where | Job |
|---|---|---|
| Core flow | `rfq/` | Parse email → extract IDs → lookup → fill template → Quality Agent → Excel + reply. Plain Python; the CLI, the worker and an Azure wrapper call the same `rfq.pipeline.run()`. |
| Backend | `backend/app/` | API, SQLite storage, versioned editing, search, exports. Live progress: the worker publishes to Redis, the API relays it to the browser as Server-Sent Events. |
| Workers | `backend/app/worker.py`, `run_worker.py` | Run jobs in parallel, send email, recover stuck work; the supervisor restarts arq if Redis drops. |
| Web app | `frontend/` | Jobs list with database search, live progress, review grid, upload/download, send dialog. Ferguson branding. |
| Extension | `extension/` | One click in Gmail sends the open email (full raw message, including attachments). |

## 2. From email to RFQ (the pipeline)

```mermaid
flowchart TD
    A["Email<br/>.eml · pasted text · Gmail raw MIME"] --> B["parse_email<br/>plain/HTML body, xlsx/csv attachments, size limits"]
    B --> C["extract_ids (no LLM)<br/>6–7 digit IDs, #IDs, competitor codes,<br/>masks phones/dates/PO numbers, dedupe + qty"]
    C --> D["resolve: lookup per product<br/>(see section 3)"]
    D --> E["spec sheets<br/>fill BLANK Thickness/ASTM only if the PDF states one value"]
    E --> F["Quality Agent<br/>(see section 4)"]
    F --> G["pictures<br/>thumbnails from the Ferguson CDN"]
    G --> H["Excel writer<br/>RFQ · Supplier · Summary · Sources(+links) · Notes"]
    H --> I["reply.eml<br/>found / not found / fill rate"]
```

Every value placed on the RFQ sheet gets a row on the Sources sheet: source type, confidence, the
source text and a **clickable link** to the page or PDF it came from. A blank cell means "no source had
it". Values are never guessed.

## 3. Product lookup and fallbacks

```mermaid
flowchart TD
    S([Ferguson product ID]) --> C{Cached in Redis?}
    C -- yes --> M
    C -- no --> FA["Ferguson product API<br/>(plug-in point, needs Ferguson credentials)"]:::planned
    FA -. not configured .-> SA
    SA{"SerpApi<br/>site:ferguson.com &quot;id&quot;"}
    SA -- "exact product URL found" --> INCAT{In backup catalog?}
    INCAT -- yes --> CATSPEC["Specs from catalog<br/>+ page URL &amp; price from Google"]
    INCAT -- no --> PAGE
    SA -- "no key / quota used up /<br/>timeout / no result" --> PAGE["Read the ferguson.com page<br/>your Chrome, max 12 loads/min"]
    PAGE -- found --> LIVE["Live values win;<br/>catalog fills the gaps; differences → Notes"]
    PAGE -- "blocked / error" --> CAT{In backup catalog?}
    PAGE -- "redirects away (not on site)" --> CAT
    CAT -- yes --> CATV["Catalog values<br/>(collected 2026-09-24) + Note why"]
    CAT -- no --> NF["Not found<br/>row kept, blank, every source tried listed"]
    CATSPEC --> M([Row with sourced values])
    LIVE --> M
    CATV --> M
    classDef planned stroke-dasharray: 5 5,fill:#f6f8fa,color:#555
```

- **Competitor part numbers** (e.g. `17783-79-3000`, `MTX-4409-XQ`) are recognised and kept as `Not found` with
  the reason. The competitor finder arm is not built.
- **Rate limit:** a Redis sliding window shared by all workers, `FERGUSON_RATE_PER_MINUTE` (default 12), plus
  ~5 s spacing. Spec-sheet PDFs count against it too. Blocked pages are detected and retried once, and repeated
  blocks trigger a 10-minute cool-down.
- **SerpApi:** results are cached for 24 h. A used-up quota or a rejected key pauses SerpApi for 1 h. Fresh
  searches can take 20–60 s (`SERPAPI_TIMEOUT_S`, default 45).
- **Precedence:** live page > SerpApi > catalog, for both specs and supplier info (price, stock, part numbers).

## 4. The agentic arm: RFQ Quality Agent

```mermaid
flowchart LR
    R["Filled RFQ"] --> U["Code: units<br/>ft · in · mil · lb<br/>333.33 yds = 1000 ft"]
    R --> MI["Code: missing cells"]
    R --> PL["Code: plausibility<br/>ranges, APWA colours vs lettering,<br/>description vs width/length"]
    R --> AI["AI (OpenAI, strict JSON)<br/>cross-field contradictions<br/>may only point at filled cells"]
    U & MI & PL & AI --> MG["Merge flags per cell"]
    MG --> X["Excel: grey / orange cells<br/>+ comment with the reason"]
    MG --> SUM["Summary sheet<br/>fill rates, not found + why, flags"]
    AI -. "timeout / error / no key" .-> SKIP["AI skipped, noted;<br/>code checks still stand"]
```

The agent **flags and never overwrites**. Re-checks only re-ask the AI about rows that changed (cached per
row), and a re-check result is stored only for the version it checked.

## 5. Job lifecycle

```mermaid
stateDiagram-v2
    [*] --> queued: email received
    queued --> running: worker claims it (atomic)
    running --> queued: crash → retried once
    running --> failed: second failure
    failed --> queued: Retry button
    running --> needs_review: RFQ written (version 1)
    needs_review --> ready: Mark reviewed (by name, for this version)
    ready --> needs_review: edited after review
    needs_review --> sending: Send (confirmed)
    ready --> sending: Send (confirmed)
    sending --> sent: delivered
    sending --> needs_review: permanent failure (e.g. bad login)
    sent --> needs_review: edited → new version
    sent --> sending: Send again
```

## 6. Gmail extension → live progress

```mermaid
sequenceDiagram
    actor U as Sourcing manager
    participant X as Extension (Gmail tab)
    participant A as API
    participant R as Redis
    participant W as Worker
    participant UI as Web app

    U->>X: click "Send this email to the RFQ Agent"
    X->>X: read open message: raw MIME via "Show original"<br/>(fallback: visible text)
    X->>A: POST /api/jobs (idempotent per Gmail message id)
    A->>R: enqueue run_rfq_job
    A-->>X: job id → opens the web app
    R->>W: job
    loop each phase
        W->>R: publish phase, %, time left
        R-->>UI: Server-Sent Events
    end
    W->>A: sheet + report saved (version 1)
    UI-->>U: email, products, flags, Summary
```

## 7. Human in the loop: review, upload, send

```mermaid
sequenceDiagram
    actor U as Sourcing team
    participant UI as Web app
    participant A as API
    participant W as Worker

    U->>UI: edit cells (with a source note)
    UI->>A: PATCH /sheet {version, edits}
    A->>A: validate → apply if version matches (else 409)<br/>code checks re-run, RFQ_vN.xlsx regenerated
    U->>UI: Download ▾ (.xlsx / .xls / .csv), edit offline
    U->>UI: Upload edited file
    UI->>A: POST /sheet/import
    A-->>UI: preview: ready / invalid / conflict per cell (nothing written)
    U->>UI: Apply ticked changes → PATCH /sheet
    U->>UI: Send to POC (email, confirm gaps, confirm screen)
    UI->>A: POST /send {idempotency key}
    A->>W: send_rfq_email (claimed once)
    W-->>U: reply in the original thread with RFQ_vN.xlsx
```

## 8. Data model

```mermaid
erDiagram
    JOB ||--o{ JOB_ITEM : requests
    JOB ||--o{ JOB_EVENT : logs
    JOB ||--o{ JOB_EDIT : "edited by"
    JOB ||--o{ JOB_SEND : "sent as"
    JOB {
        uuid id PK
        string source "extension | paste | upload | mailbot"
        string subject
        string sender
        blob raw_eml
        string status
        int version "optimistic lock"
        json sheet "rows, cells with sources + links, supplier, notes"
        json report "flags, fill rates, AI status"
        datetime created_at "UTC"
    }
    JOB_ITEM {
        int id PK
        uuid job_id FK
        int position
        string product_id
        string kind "ferguson | competitor"
        string lookup_status
        string lookup_source
    }
    JOB_EVENT {
        int id PK
        uuid job_id FK
        string phase
        string message
    }
    JOB_EDIT {
        int id PK
        uuid job_id FK
        int version
        string column
        string old
        string new
        string note
        string user
    }
    JOB_SEND {
        int id PK
        uuid job_id FK
        int version
        string idempotency_key UK
        string to
        string status
        string message_id
    }
```

The editable RFQ is one versioned JSON document (`jobs.sheet` + `jobs.version`), so optimistic locking is a
single conditional `UPDATE`. The Excel file for each version is regenerated from it and kept as `RFQ_vN.xlsx`.

## 9. Reliability and guardrails

| Risk | What happens |
|---|---|
| ferguson.com blocks scraping | Real Chrome profile, 12 loads/min across all workers, block detection, retry, cool-down, catalog fallback with a Note |
| SerpApi slow, out of quota, key rejected | Timeout → page read; quota/key → paused 1 h, warning on the RFQ |
| AI fails or returns junk | Strict schema, unknown cells dropped, code checks still run, Summary says "AI skipped" |
| Redis down | API still serves reads; new jobs are saved and start when the queue is back (recovery sweep); CLI uses an in-memory cache |
| Worker dies mid-job | Atomic claim + recovery sweep re-queues; a job never runs twice |
| Two people edit at once | Version check → 409 for the slower one |
| Double click on Send | Idempotency key + atomic status claim → exactly one email |
| Prompt injection in emails/pages/PDFs | Treated as data, AI has no tools, can't choose recipients or URLs |
| Formula injection | External text is written as text; CSV export prefixes `=` `+` `@`; uploads refuse formulas |
| Bad uploads | Type/size/column/job checks, per-cell validation, conflicts unticked, nothing written before Apply |
| Images | Ferguson CDN only, type/size/pixel caps, cached; failures noted, link kept |
