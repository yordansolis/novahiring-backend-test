# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# First-time setup: install deps, start Docker, migrate DB, seed data
make init

# Start dev server (starts Docker if needed, then launches FastAPI)
make start-dev

# Delete all interview sessions and AI call logs; restore DB to post-seed state
# Preserves: job_openings, candidates, prompt_versions, question_bank, seeded evaluations
make clean-sessions
```

```bash
# Install dependencies
uv sync

# Start infrastructure (PostgreSQL + Redis)
docker compose up -d

# Run Alembic migrations
uv run alembic upgrade head

# Seed reference case + prompt versions into DB (run after migrations)
uv run python seed.py

# Seed only reference case
uv run python seed.py case

# Seed only prompt versions
uv run python seed.py prompts

# Cambiar el evaluador de entrevista a OpenAI (gpt-4o-mini)
uv run python seed.py use-openai

# Volver al evaluador de entrevista con Anthropic (claude-sonnet-4-6)
uv run python seed.py use-anthropic

# Run FastAPI dev server
uv run fastapi dev main.py

# Run all tests
uv run pytest

# Run only unit tests (no DB required)
uv run pytest tests/test_unit.py -v

# Run interview unit tests (no DB, no AI, no Redis required)
uv run pytest tests/test_interview_unit.py -v

# Run acceptance tests (requires seeded DB)
uv run pytest tests/test_acceptance.py -v

# Generate a new Alembic migration
uv run alembic revision --autogenerate -m "description"

# Add a dependency
uv add <package>
```

Python 3.11 (CPython 3.11.14), managed via `uv`. Virtualenv at `.venv/`.

## Environment variables (`.env`)

```
DATABASE_URL=postgresql+asyncpg://nova:nova_dev@localhost:5432/nova_hiring
REDIS_URL=redis://localhost:6379
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
API_KEY_ADMIN=<openssl rand -hex 32>        # recruiters / admin tools — required in prod
API_KEY_CANDIDATES=<openssl rand -hex 32>   # chatbot frontend — required in prod
DEBUG=true
LOG_LEVEL=INFO
```

> **Auth:** `X-API-Key` header. Both keys empty → auth bypassed (dev/test). Admin key works on all endpoints; candidates key only on `/api/v1/interviews/*`.
> Generate keys: `openssl rand -hex 32`

Both API keys are optional for unit tests. Acceptance tests and seeded prompt calls require whichever key the active prompt's `provider` field maps to.

## Project status

**Phase 0–3 + Interview flow + Report writer implemented.** The acceptance test (`tests/test_acceptance.py`) requires Docker + seeded DB.

| Phase | Status | Deliverable |
|-------|--------|-------------|
| 0 | ✅ Done | Docker Compose, FastAPI factory, Alembic, middleware, structured logging |
| 1 | ✅ Done | Pydantic v2 contracts, SQLAlchemy models, Alembic env |
| 1.5 | ✅ Done | `seed.py` — 1 job, 6 candidates, 6 evals, 24 dim scores, 5 prompts |
| 2 | ✅ Done | PromptVersion model (`provider` field), `AIClient` with dual-provider backend dispatch, audit writer, score validator |
| 3 | ✅ Done | `services/profile.py`, `ko_checker.py`, `scorer.py` — 10/10 unit tests passing |
| 4/5 | ✅ Done | Interview chatbot: `session_manager.py` (Redis NX lock), `interview_conductor.py` (state machine + AI eval pipeline), `api/interviews.py` (4 endpoints) |
| 4 rest | ✅ Done | `report_writer.py` — `GET /api/v1/jobs/{id}/report` returns markdown ranking report |
| 6 | ✅ Done | Job Offer API (`api/jobs.py`) |
| 7 | ⏳ Next | API key auth middleware, rate limiting |
| 8 | ⏳ | Acceptance test CI run |
| 9 | ⏳ | `/health` metrics, Prometheus, CloudWatch alarms |
| 10 | ⏳ | Mangum handler, SAM/CDK, GitHub Actions CI, staging deploy |

## Architecture

NovaHiring is an AI-assisted hiring platform. Core principle: **Python code is the brain; AI is only a language processing tool.** Hard decisions (knock-outs, scores) are always executed by code, never delegated to the model.

The system runs in three sequential stages:

### Stage 1 — Discovery Engine (deferred for MVP)
Conversational flow with the hiring client to extract structured context. **For MVP, replaced by the DB seeder** — `docs/data/discovery-clinica-salud-valencia.json` is loaded directly.

### Stage 2 — Profile Builder (zero AI)
Pure deterministic Python. Maps the discovery JSON → candidate profile using fixed rules. Implemented in `services/profile.py`.

### Stage 3 — Interview & Evaluation
Code drives question flow. AI evaluates free-text responses (temperature=0). Code applies KO criteria and calculates weighted scores. Scoring formula: `Score final = Σ(score × peso) / Σ(pesos)`, scale 1–5.

**Interview chatbot flow (implemented):**
1. `POST /api/v1/interviews/sessions` — creates session for an APTO candidate; returns welcome message + D1 question. Blocks DESCARTADO candidates (422). Blocks duplicate active sessions (409).
2. `POST /api/v1/interviews/sessions/{id}/message` — receives candidate answer, returns next question. Special intents detected by keyword matching (no AI):
   - **Correction:** "me equivoqué / quiero corregir..." → goes back one question, erases prior answer, re-asks
   - **Abandonment:** "no quiero continuar / quiero abandonar..." → closes session gracefully (`status=abandoned`), returns farewell message
   - After the 8th answer, triggers the AI evaluation pipeline (one AI call per dimension, score validated 1–5, retry ≤2), runs `Scorer`, writes new `Evaluation` + `DimensionScoreRecord` rows, marks session `completed`.
3. Redis NX lock (`session:{id}:processing`, TTL=30s) prevents concurrent messages → 409 `session_busy`.
4. `POST /api/v1/interviews/sessions/{id}/interrupt` — sets interrupt flag; evaluation pipeline checks it between AI calls and exits early.
5. `GET /api/v1/interviews/sessions/{id}` — full message history + current question index.
6. `GET /api/v1/jobs/{id}/report` — returns final markdown ranking report (latest eval per candidate, APTO ranked by score, DESCARTADO section with KO reason).

Session status values: `active` → `completed` | `abandoned` | `expired`. A candidate can start a new session after abandonment.

Session state is stored as JSON in `ChatSession.context_summary`:
```json
{"version":"1","current_question_index":3,"answers":{"D1":"...","D2":"...","D3":"..."},"evaluation_id":null}
```

### Infrastructure
| Component | Role |
|-----------|------|
| FastAPI | REST API (`main.py` → `api/jobs.py`) |
| PostgreSQL 16 | Audit log, all persistent state |
| Redis 7 | Session state, processing lock, 7-day TTL |
| Pydantic v2 | Data contracts (`contracts.py`) |
| SQLAlchemy 2 (async) | ORM with NullPool for Lambda |
| Alembic | DB migrations |
| pytest + httpx | Tests (async, `asyncio_mode=auto`) |
| Claude Sonnet / GPT-4o | AI layer (temperature=0 for evaluation calls) — provider set per prompt in DB |

**Seeded prompt versions (5 total):**
| Name | Provider | Model | Temp | Use |
|------|----------|-------|------|-----|
| `cv_dimension_evaluator` | anthropic | claude-sonnet-4-6 | 0.0 | CV screening |
| `narrative_report_writer` | anthropic | claude-sonnet-4-6 | 0.3 | Narrative report |
| `cv_dimension_evaluator_openai` | openai | gpt-4o-mini | 0.0 | CV screening (OpenAI) |
| `narrative_report_writer_openai` | openai | gpt-4o | 0.3 | Narrative report (OpenAI) |
| `interview_response_evaluator` | anthropic | claude-sonnet-4-6 | 0.0 | Interview answer scoring |

### Adding a new AI provider

1. Add a new backend class to `services/ai_client.py` implementing `complete(system_prompt, messages, model, max_tokens, temperature) -> tuple[str, int, int]`.
2. Register it in `AIClient.__init__` under `self._backends["<provider>"]`.
3. Insert a `prompt_versions` row with `provider="<provider>"`. No code change needed after that.

### Intentionally excluded
LangChain, LangGraph, MongoDB, Kubernetes (for MVP), RAG, Streamlit/Gradio, Flowise/n8n, fine-tuning.

## Module structure

```
nova-hiring/
├── main.py                ← FastAPI app factory + inline middleware
├── config.py              ← Pydantic Settings (from .env)
├── database.py            ← Async SQLAlchemy (NullPool) + Redis pool
├── contracts.py           ← All Pydantic v2 data contracts in one file
├── seed.py                ← Seed reference case + prompt versions (5 prompts)
├── api/
│   ├── jobs.py            ← GET /offer, /profile, /ranking
│   └── interviews.py      ← POST /sessions, POST /sessions/{id}/message,
│                             GET /sessions/{id}, POST /sessions/{id}/interrupt
├── models/
│   ├── base.py            ← Base, TimestampMixin, new_uuid
│   ├── job.py             ← job_openings (discovery_json JSONB + offer_text)
│   ├── candidate.py       ← candidates (passed_ko field)
│   ├── evaluation.py      ← evaluations + dimension_scores
│   └── ops.py             ← prompt_versions, ai_call_logs, questions, chat_sessions, messages
├── services/
│   ├── profile.py         ← ProfileBuilder — pure Python, zero AI
│   ├── ko_checker.py      ← KOChecker — first failing KO short-circuits
│   ├── scorer.py          ← Scorer — Σ(score × peso) / Σ(pesos)
│   ├── ai_client.py       ← AIClient + AnthropicBackend + OpenAIBackend + validators
│   ├── session_manager.py ← Redis NX lock (Lua release), interrupt flag, meta hash
│   ├── interview_conductor.py ← Interview state machine, correction/abandonment detection, AI eval pipeline, DB writes
│   └── report_writer.py   ← Markdown ranking report generator (latest eval per candidate)
├── alembic/
│   └── env.py             ← Async migration runner
├── notebooks/
│   ├── demo_interview.ipynb   ← Offline demo: loads 4 conversation scenarios, runs Scorer, shows ranking (no API calls)
│   └── e2e_interview.ipynb    ← Real E2E test: calls live API + OpenAI, evaluates 3 APTO candidates
└── tests/
    ├── conftest.py             ← discovery_fixture (full 8-dim scorecard)
    ├── test_unit.py            ← 10 unit tests (scorer + ko_checker), no DB required
    ├── test_interview_unit.py  ← 34 unit tests (question structure, state machine, scorer from dataset), no DB/AI/Redis
    └── test_acceptance.py      ← 5 tests requiring seeded DB
```

## Key design constraints

- **AI never makes hard decisions.** KO criteria and score calculations are always Python code.
- **Prompts versioned in the database.** Never hardcode prompts in source files — a prompt change is a behavior change and must be auditable.
- **Data contracts first.** `DiscoveryJSON` and `CandidateProfile` Pydantic models are defined before any business logic.
- **Audit log from commit 1.** Every AI call logged in `ai_call_logs`. Non-negotiable.
- **AI evaluation inputs.** Always pass the full candidate response text, never a summary. Include rubric with numeric examples. Validate output range; retry max 2 times.
- **Session processing lock.** Redis NX mutex prevents concurrent messages to the same session. `409 session_busy` if lock held.
- **Provider set per prompt in DB.** Each `PromptVersion` row has a `provider` field (`"anthropic"` | `"openai"`). `AIClient` dispatches to the matching backend at call time — switching providers is a DB change, not a code change.

## Reference case — Clínica Salud Valencia

This is the acceptance test for the system. All inputs and expected outputs exist in `docs/`.

**Client:** Clínica Salud Valencia S.L., Valencia, Spain — private multi-specialty clinic
**Job ID (seeded):** `job-clinica-salud-valencia-001`

**KO criteria:**
| ID | Criterion |
|----|-----------|
| KO1 | No experience with WhatsApp Business API (Meta) |
| KO2 | No demonstrated understanding of RGPD/LOPDGDD for health data |
| KO3 | Can only work with external technical supervision |

**Scorecard:** 8 dimensions, weights sum to 19
D1 Integrations (×3) · D2 RGPD/LOPDGDD (×3) · D3 Autonomy (×3) · D4 Build-vs-buy (×3) · D5 Delivery (×2) · D6 Communication (×2) · D7 Health sector (×2) · D8 Stack (×1)

**Expected ranking (acceptance test must reproduce exactly):**
| Rank | Candidate | Score | Status |
|------|-----------|-------|--------|
| #1 | Sofía Delgado | 4.84/5 | APTA |
| #2 | Carlos Rivas | 4.74/5 | APTO |
| #3 | Elena Martínez | 4.58/5 | APTA |
| — | Jhordan Solis | — | DESCARTADO (KO2) |
| — | Miguel Torres | — | DESCARTADO (KO1+KO2+KO3) |
| — | Ana Lombard | — | DESCARTADA (KO1+KO2+KO3) |

## Docs structure

```
docs/
├── specs/
│   ├── 03-discovery_dataset.json                          ← Question bank (niche: clinica_medica)
│   └── 03-discovery_simulation_clinica_salud_valencia.md  ← Full client discovery simulation
├── data/
│   ├── discovery-clinica-salud-valencia.json              ← Stage 1 output → seeded into job_openings
│   ├── conversations/                                     ← 4 interview scenario datasets (used by test_interview_unit.py + demo_interview.ipynb)
│   │   ├── ganador_claro.json                             ← Scores (5,5,5,4,5,5,5,5) → 4.84/5
│   │   ├── buen_candidato.json                            ← Scores (5,4,5,5,5,5,4,5) → 4.74/5
│   │   ├── candidato_promedio.json                        ← Scores (4,4,4,3,4,3,3,3) → 3.58/5
│   │   └── respuestas_debiles.json                        ← Scores (2,2,2,2,2,2,1,2) → 1.89/5
│   └── evaluations/
│       ├── eval-10-jhordan-solis.json                     ← DESCARTADO (KO2)
│       ├── eval-11-elena-martinez.json                    ← APTA #3 — 4.58/5
│       ├── eval-12-carlos-rivas.json                      ← APTO #2 — 4.74/5
│       ├── eval-13-sofia-delgado.json                     ← APTA #1 — 4.84/5
│       ├── eval-14-miguel-torres.json                     ← DESCARTADO (KO1+KO2+KO3)
│       └── eval-15-ana-lombard.json                       ← DESCARTADA (KO1+KO2+KO3)
├── reports/
│   └── ranking-clinica-salud-valencia.md                  ← Final ranking report
├── cv-20-06-2026/                                         ← 6 candidate CVs
├── architecture/
│   └── 00-arquitectura-novahiring.md
├── vacante-clinica-salud-valencia.md                      ← Job description (seeded as offer_text)
└── 04-backend-architecture.md                             ← Full backend architecture plan
```
