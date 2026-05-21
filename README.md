# NovaHiring

AI-assisted hiring platform. Core principle: **Python code is the brain; AI is only a language processing tool.** Hard decisions (knock-outs, scores) are always executed by code, never delegated to the model.

## Quickstart

```bash
# First-time setup: install deps, start Docker, migrate DB, seed data
make init

# Daily: start the API (ensures Docker is up)
make start-dev
```

Or step by step:

```bash
uv sync
docker compose up -d
uv run alembic upgrade head
uv run python seed.py
uv run fastapi dev main.py
```

### Common commands

| Command | What it does |
|---------|--------------|
| `make init` | First-time setup (deps + Docker + migrations + seed) |
| `make start-dev` | Start Docker + FastAPI dev server |
| `make seed` | Re-seed reference case and prompts |
| `make clean-sessions` | Delete all interview sessions and AI call logs (keeps seeded reference data) |
| `make test` | Run all tests |
| `make test-unit` | Unit + interview unit tests (no DB needed) |
| `make test-acceptance` | Acceptance tests (requires seeded DB) |

## Reference case — Clínica Salud Valencia

This is the system's acceptance test. All inputs and expected outputs live in `docs/`.

**Client:** Clínica Salud Valencia S.L. — private multi-specialty clinic in Valencia, Spain
**Problem:** 15–20 lost appointments/week (~€4,000/month). Single receptionist managing everything manually.
**Budget:** €8,000–12,000, 3-month deadline.

### Expected ranking (acceptance test must reproduce exactly)

| Rank | Candidate | Score | Status |
|------|-----------|-------|--------|
| #1 | Sofía Delgado | 4.84 / 5 | APTA |
| #2 | Carlos Rivas | 4.74 / 5 | APTO |
| #3 | Elena Martínez | 4.58 / 5 | APTA |
| — | Jhordan Solis | — | DESCARTADO (KO2) |
| — | Miguel Torres | — | DESCARTADO (KO1 + KO2 + KO3) |
| — | Ana Lombard | — | DESCARTADA (KO1 + KO2 + KO3) |

### KO criteria (evaluated before scoring — any failure = immediate discard)

| ID | Criterion |
|----|-----------|
| KO1 | No experience with WhatsApp Business API (Meta) |
| KO2 | No demonstrated understanding of RGPD/LOPDGDD for health data |
| KO3 | Can only work with external technical supervision |

### Scorecard dimensions (8 total, weights sum to 19)

| ID | Dimension | Weight |
|----|-----------|--------|
| D1 | Technical integrations (WhatsApp, Google Calendar, reception panel) | ×3 |
| D2 | RGPD/LOPDGDD compliance for health data | ×3 |
| D3 | Autonomy and technical decision-making | ×3 |
| D4 | Build-vs-buy pragmatism | ×3 |
| D5 | Delivery under tight deadlines | ×2 |
| D6 | Communication with non-technical profiles | ×2 |
| D7 | Health sector experience | ×2 |
| D8 | Stack fit for budget | ×1 |

**Scoring formula:** `Score final = Σ(score × peso) / Σ(pesos)`, scale 1–5 per dimension.

## API endpoints

```
GET  /health
GET  /api/v1/jobs/{job_id}/offer                          ← Job description markdown
GET  /api/v1/jobs/{job_id}/profile                        ← KO criteria + scorecard
GET  /api/v1/jobs/{job_id}/ranking                        ← Ranked candidates (APTO first, ordered by score)

POST /api/v1/interviews/sessions                          ← Start interview for an APTO candidate
POST /api/v1/interviews/sessions/{session_id}/message     ← Send answer; returns next question or final score
GET  /api/v1/interviews/sessions/{session_id}             ← Session state + full message history
POST /api/v1/interviews/sessions/{session_id}/interrupt   ← Cancel an in-progress evaluation
```

After seeding, use `job_id = job-clinica-salud-valencia-001`.

### Interview flow

APTO candidates (those who passed KO screening): `cand-11-elena-martinez`, `cand-12-carlos-rivas`, `cand-13-sofia-delgado`.

```bash
# Start an interview session
curl -X POST http://localhost:8000/api/v1/interviews/sessions \
  -H "Content-Type: application/json" \
  -d '{"job_id": "job-clinica-salud-valencia-001", "candidate_id": "cand-11-elena-martinez"}'
# → 201: session_id, welcome message with D1 question

# Send an answer (repeat 8 times — one per dimension D1–D8)
curl -X POST http://localhost:8000/api/v1/interviews/sessions/{session_id}/message \
  -H "Content-Type: application/json" \
  -d '{"content": "your answer here..."}'
# → next question (D2–D8), or final evaluation result after the 8th answer

# Check session state at any time
curl http://localhost:8000/api/v1/interviews/sessions/{session_id}
```

Gates: DESCARTADO candidates are rejected (422). A duplicate active session returns 409 with the existing `session_id`. Concurrent messages to the same session return 409 `session_busy`.

## AI providers

Both Anthropic and OpenAI are supported. The provider is set **per prompt version in the database** — switching providers is a DB row change, not a code change.

| Prompt name | Provider | Model | Temp | Use |
|-------------|----------|-------|------|-----|
| `cv_dimension_evaluator` | Anthropic | claude-sonnet-4-6 | 0.0 | CV screening (default) |
| `narrative_report_writer` | Anthropic | claude-sonnet-4-6 | 0.3 | Final report narrative |
| `cv_dimension_evaluator_openai` | OpenAI | gpt-4o-mini | 0.0 | CV screening (OpenAI variant) |
| `narrative_report_writer_openai` | OpenAI | gpt-4o | 0.3 | Final report (OpenAI variant) |
| `interview_response_evaluator` | Anthropic | claude-sonnet-4-6 | 0.0 | Interview answer scoring |

To switch a prompt to a different provider: deactivate the current row (`is_active=false`) and insert a new one with the desired `provider`. To add a third provider: implement a new backend class in `services/ai_client.py` and register it in `AIClient.__init__`.

## Project structure

```
nova-hiring/
├── main.py               ← FastAPI app factory + middleware
├── config.py             ← Settings from .env
├── database.py           ← Async SQLAlchemy (NullPool) + Redis pool
├── contracts.py          ← All Pydantic v2 data contracts
├── seed.py               ← Seeds reference case + 5 prompt versions
├── api/
│   ├── jobs.py           ← GET /offer, /profile, /ranking
│   └── interviews.py     ← Interview session endpoints (4 routes)
├── models/
│   ├── base.py           ← Base, TimestampMixin, new_uuid
│   ├── job.py            ← job_openings
│   ├── candidate.py      ← candidates (passed_ko field)
│   ├── evaluation.py     ← evaluations + dimension_scores
│   └── ops.py            ← prompt_versions, ai_call_logs, chat_sessions, messages
├── services/
│   ├── profile.py              ← ProfileBuilder — zero AI, pure Python
│   ├── ko_checker.py           ← KOChecker — first failing KO short-circuits
│   ├── scorer.py               ← Scorer — Σ(score × peso) / Σ(pesos)
│   ├── ai_client.py            ← AIClient + AnthropicBackend + OpenAIBackend
│   ├── session_manager.py      ← Redis NX lock (Lua), interrupt flag, meta hash
│   └── interview_conductor.py  ← Interview state machine + AI eval pipeline
├── alembic/
│   └── env.py            ← Async migration runner
└── tests/
    ├── conftest.py        ← discovery_fixture (full 8-dim scorecard)
    ├── test_unit.py       ← 10 unit tests (scorer + ko_checker), no DB required
    └── test_acceptance.py ← 5 tests requiring seeded DB

docs/
├── specs/03-discovery_dataset.json                    ← Question bank (niche: clinica_medica)
├── data/discovery-clinica-salud-valencia.json         ← Stage 1 output → seeded into DB
├── data/evaluations/eval-{id}-{name}.json            ← 6 candidate evaluations
├── cv-20-06-2026/                                     ← 6 candidate CVs
├── reports/ranking-clinica-salud-valencia.md          ← Final ranking report
├── vacante-clinica-salud-valencia.md                  ← Job description (seeded as offer_text)
└── 04-backend-architecture.md                         ← Full backend architecture plan
```

## Development

**Dependencies:** `fastapi`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `redis`, `pydantic-settings`, `anthropic`, `openai`, `httpx`, `pytest`, `pytest-asyncio`.

**Required `.env` keys:**
```
DATABASE_URL=postgresql+asyncpg://nova:nova_dev@localhost:5432/nova_hiring
REDIS_URL=redis://localhost:6379
ANTHROPIC_API_KEY=sk-ant-...   # required for Anthropic prompts
OPENAI_API_KEY=sk-...          # required for OpenAI prompts
```

Unit tests (`tests/unit/`) need no running services and no API keys.

## Implementation status

| Phase | Status | Deliverable |
|-------|--------|-------------|
| 0 | ✅ Done | Docker Compose, FastAPI factory, Alembic, middleware |
| 1 | ✅ Done | All Pydantic v2 contracts + SQLAlchemy models |
| 1.5 | ✅ Done | `seed.py` — 1 job, 6 candidates, 6 evals, 24 dim scores, 5 prompts |
| 2 | ✅ Done | AIClient, prompt versioning, audit writer |
| 3 | ✅ Done | `scorer.py`, `ko_checker.py`, `profile.py` — 10/10 unit tests |
| 4/5 | ✅ Done | Interview chatbot: session manager (Redis NX lock), interview conductor (state machine + AI eval), 4 API endpoints |
| 7–10 | ⏳ Pending | Auth middleware, rate limiting, CI/CD, Lambda deploy |
