# Evidence Currency Monitor

Watches published research and flags when new studies challenge, confirm, or extend an earlier finding. Phase 1 covers **data ingestion and storage only**.

## Project structure

```
SAGE/
  backend/          ← Python API (FastAPI + SQLAlchemy + LangGraph)
    src/evidence_monitor/
    tests/
    data/           ← needs.json, demo DB fixtures
    pyproject.toml
    .env            ← secrets (never commit)
  frontend/         ← React + Vite + TypeScript + Tailwind
    src/
    ...
  .venv/            ← virtual environment (stays at root, paths baked in)
  README.md
```

## Setup

```bash
# 1. Create and activate a virtual environment (from D:\SAGE root)
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate # macOS/Linux

# 2. Install all Python dependencies
pip install -r backend/requirements.txt
pip install -e "backend/[dev]"

# 3. Configure environment
cp backend/.env.example backend/.env
# Edit backend/.env and fill in your keys
```

## Commands

All CLI commands run from `D:\SAGE` root (the venv is there):

```bash
# Search and ingest papers
python -m evidence_monitor.cli ingest-topic "mindfulness wellbeing students" \
    --from-year 2018 --to-year 2026 --max-papers 40

# Fetch works that cite papers already in the DB
python -m evidence_monitor.cli ingest-citers --since-date 2024-01-01

# Check for retractions / corrections via Crossref
python -m evidence_monitor.cli check-integrity

# Show row counts and last 5 runs
python -m evidence_monitor.cli stats
```

Add `--refresh` to any command to bypass the disk cache.

## Data model

| Table | Key columns |
|---|---|
| `papers` | `id` (OpenAlex id, PK), `doi`, `title`, `abstract`, `publication_date`, `journal`, `authors_json` (JSON list), `openalex_is_retracted`, `fetched_at` |
| `citations` | `citing_id`, `cited_id` (both OpenAlex ids), unique pair |
| `integrity_notices` | `paper_id`, `kind` (retraction/correction/concern/withdrawal), `source` (crossref/openalex), `notice_doi`, `notice_date` |
| `ingest_runs` | `id`, `query`, `status`, counts (`papers_new`, `papers_updated`, `citations_new`, `notices_found`) |

All upserts are idempotent — running the same ingest twice produces no duplicates.

## Tests

```bash
# Backend (from D:\SAGE root)
.venv\Scripts\python -m pytest backend/tests/

# Frontend (from D:\SAGE\frontend)
npm test
```

## Configuration (`.env`)

| Variable | Description |
|---|---|
| `OPENALEX_API_KEY` | Free key from openalex.org |
| `CROSSREF_MAILTO` | Your email for Crossref polite pool |
| `DB_URL` | SQLAlchemy URL (default: `sqlite:///evidence.db`) |
| `CACHE_DIR` | Directory for raw JSON cache (default: `.cache`) |

## Running the application (Phase 4)

### Prerequisites

```bash
# Install Python dependencies
pip install -e ".[dev]"

# Install frontend dependencies
cd frontend && npm install && cd ..
```

### Start the API server

```bash
# From D:\SAGE root
.venv\Scripts\activate
uvicorn evidence_monitor.api.main:app --reload --port 8000
# API:  http://localhost:8000
# Docs: http://localhost:8000/docs
```

### Start the frontend dev server

```bash
# In a second terminal, from D:\SAGE\frontend
npm run dev
# UI: http://localhost:5173
```

### Agent Run View (new in Phase 7)

When you click **Discover new papers** on the Dashboard or **Run need** on the Needs page, the UI replaces the content with a live animated graph of the agent pipeline:

- **Purple nodes** = AI agent steps (discovery, evidence, skeptic, …)
- **Coral gate** = human decision point (review gate / approval gate)
- **Teal tracker** = final action/tracker node
- Each node shows: idle → running (pulsing ring) → done ✓ / paused ⏸ / failed ✕
- A dot travels along each edge when traversed
- Live log panel shows every event message in chronological order
- Counters strip: pairs found, cases created, seconds elapsed
- Mode banner: "Live model calls" vs "Replaying saved model responses"
- On completion: summary card with Run again / Clear buttons
- Fully accessible: `aria-live` log, `prefers-reduced-motion` respected, keyboard-navigable

### Full demo path

1. **Ingest papers** (if not already done):
   ```bash
   python -m evidence_monitor.cli ingest-topic "mindfulness wellbeing students" --from-year 2018 --to-year 2026 --max-papers 40
   python -m evidence_monitor.cli ingest-topic "ego depletion self-control" --from-year 2018 --to-year 2026 --max-papers 20
   python -m evidence_monitor.cli check-integrity
   ```

2. **Extract claims** (requires `GROQ_API_KEY` in `.env`):
   ```bash
   python -m evidence_monitor.cli extract-claims --limit 60
   ```

3. **Build cases** (compare claims, classify, rank):
   ```bash
   python -m evidence_monitor.cli build-cases --limit 60
   ```

4. **Open the UI** at [http://localhost:5173](http://localhost:5173):
   - **Dashboard** — stat tiles and label breakdown chart
   - **Cases** — filterable inbox sorted by priority; click any case to review
   - **Case review** — source sentences side by side, field comparison table, assessment meters, Copilot, decision form, audit trail
   - **Revisions** — all papers flagged for update

5. **Record a decision** via the UI or curl:
   ```bash
   curl -s -X POST http://localhost:8000/cases/<case_id>/decision \
     -H "Content-Type: application/json" \
     -d '{"action":"no_action","reason":"Reviewed; context difference is expected.","decided_by":"editor@example.com"}'
   ```

### Run all tests

```bash
# Backend (pytest)
pytest

# Frontend (vitest)
cd frontend && npx vitest run
```

## Phase 3 schema additions

| Table | New columns |
|---|---|
| `claims` | `direction`, `population`, `design`, `outcome_measure`, `sample_size`, `country_or_setting`, `follow_up`, `embedding_json` |
| `claim_pairs` | `anchor_claim_id`, `new_claim_id`, `cosine_sim` |
| `field_comparisons` | `claim_pair_id`, `field_name`, `anchor_value`, `new_value`, `result` |
| `cases` | `label`, `confidence`, `rationale`, `priority_score`, `skeptic_verdict`, `alternative_label`, `skeptic_argument`, `state`, `thread_id`, `notice_id` |
| `affected_items` | `case_id`, `paper_id`, `score`, `score_components_json`, `relation` |

## Phase 4 architecture

```
FastAPI (port 8000)
  ├── POST /runs          → starts pipeline in background thread
  │                         LangGraph: discovery→evidence→integrity→skeptic→ranker→review_gate→[interrupt]→action
  ├── GET  /cases         → list (excludes unrelated, sorted by priority)
  ├── GET  /cases/{id}    → full detail (claims, comparisons, timeline, next_step, decision, audit)
  ├── POST /cases/{id}/decision      → records editor decision; resumes LangGraph
  ├── POST /cases/{id}/copilot       → AI assistant (Groq); never mutates case
  ├── GET  /cases/{id}/assessment    → deterministic risk scores
  ├── POST /cases/{id}/draft-author-message
  ├── GET  /stats
  └── GET  /revision-items

React frontend (port 5173)
  ├── Dashboard    /          → stats tiles + bar chart
  ├── CaseInbox    /cases     → filterable list + run trigger
  ├── CaseReview   /cases/:id → full review screen
  └── RevisionList /revision  → flagged papers table
```

## Use Case 2 — Evidence-to-Impact Agent (Phase 6)

Takes a policy or practice need, matches it to corpus evidence, checks currency using UC1 results, checks context fit, drafts a plain-language brief, and tracks approval, submission and outcome. **Humans approve every brief. The system never contacts policymakers or sends anything.**

### Flow

```
needs.json (editor-maintained)
    │
    ▼
POST /needs/import          → load & validate needs into DB
POST /needs/{id}/run        → background agent:
    need_intake             validate + store Need
    │   matcher             embed need_text, cosine-sim top 8 claims, LLM relevance check
    │   currency_gate       rules engine: retracted|challenged|under_review excluded;
    │                       differs_in_context → current_with_note (included with note)
    │   context_fit         population + setting similarity → good|partial|poor|unknown
    │   gap_check           <2 usable matches → CoverageGap + commissioning idea draft
    │   brief_writer        LLM: 220-word brief, "What research shows" + "Limits", claim ids
    │   brief_checker       overclaiming words, limits section, length, currency, no excluded claims
    │   approval_gate       ── interrupt() ──
    │   tracker             sets state=approved
    ▼
POST /needs/{id}/approve    → resume graph, set brief status=approved
POST /needs/{id}/submit     → mark submitted (system sends nothing)
POST /needs/{id}/outcome    → record cited|acknowledged|no_visible_use + LLM impact summary
```

### UC2 commands

```bash
# Load the 4 example needs into the DB
curl -X POST http://localhost:8000/needs/import

# List needs
curl http://localhost:8000/needs

# Run the agent for a need (returns run_id)
curl -X POST http://localhost:8000/needs/need-001/run

# Check run status
curl http://localhost:8000/needs/runs/{run_id}

# Get full need detail (matches, brief, checks, gap, audit trail)
curl http://localhost:8000/needs/need-001

# Approve a brief
curl -X POST http://localhost:8000/needs/need-001/approve \
  -H "Content-Type: application/json" \
  -d '{"approver": "policy.lead@example.gov", "reason": "Evidence is sound and well-scoped."}'

# Reject a brief (returns to draft)
curl -X POST http://localhost:8000/needs/need-001/reject \
  -H "Content-Type: application/json" \
  -d '{"reason": "Limits section needs to mention the retracted paper."}'

# Submit (after approval)
curl -X POST http://localhost:8000/needs/need-001/submit \
  -H "Content-Type: application/json" \
  -d '{"submitted_by": "policy.lead@example.gov", "channel_note": "Sent via email to evidence team"}'

# Record outcome
curl -X POST http://localhost:8000/needs/need-001/outcome \
  -H "Content-Type: application/json" \
  -d '{"outcome": "cited", "note": "Referenced in paragraph 3 of the consultation response."}'

# Copilot
curl -X POST http://localhost:8000/needs/need-001/copilot \
  -H "Content-Type: application/json" \
  -d '{"preset": "risks_and_limits"}'

# Impact stats
curl http://localhost:8000/impact/stats
```

### UC2 data files

- **`data/needs.json`** — editor-maintained list of policy needs. All 4 bundled entries are `"is_example": true` and clearly labelled as illustrative. The loader validates required fields; edit the file to add real needs.

### UC2 database tables

| Table | Purpose |
|---|---|
| `needs` | Policy or practice need |
| `need_matches` | Claim → need relevance matches, editor-overridable |
| `currency_checks` | UC1-derived currency status per match |
| `context_fits` | Population + setting fit per match |
| `briefs` | Plain-language evidence brief (versioned) |
| `brief_checks` | Deterministic checks (overclaiming, limits, length, …) |
| `submission_records` | Submission log (no actual sending) |
| `outcomes` | Cited / acknowledged / no visible use |
| `coverage_gaps` | Commissioning ideas when evidence is thin |

## Next phases

- **Postgres + pgvector**: migrate from SQLite for production scale.
- **Scheduled runs**: daily/weekly pipeline via cron or Celery.
- **Email integration**: actually send author-contact drafts after human approval.
- **UC2 frontend**: need inbox, brief editor, approval flow, impact dashboard.
