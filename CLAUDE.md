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

# Update cv_dimension_evaluator prompts with template variable placeholders
# (required after first migration — run once after seed.py)
uv run python seed.py update-cv-evaluator

# Switch both interview prompts to OpenAI (gpt-4o-mini / gpt-4o)
uv run python seed.py use-openai

# Switch both interview prompts back to Anthropic (claude-sonnet-4-6)
uv run python seed.py use-anthropic

# Push updated interview_dialogue_conductor prompt to DB (no server restart needed)
uv run python seed.py update-dialogue

# Run FastAPI dev server
uv run fastapi dev main.py

# Run all tests
uv run pytest

# Run only unit tests (no DB required)
uv run pytest tests/test_unit.py -v

# Run interview unit tests (no DB, no AI, no Redis required)
uv run pytest tests/test_interview_unit.py -v

# Run dialogue manager unit tests (no DB, no AI, no Redis required)
uv run pytest tests/test_dialogue_manager_unit.py -v

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
API_KEY_CANDIDATES=<openssl rand -hex 32>   # legacy shared key — optional, kept for compat
DEBUG=true
LOG_LEVEL=INFO
```

> **Auth:** Three levels — public (no header), admin (`X-API-Key: {API_KEY_ADMIN}`), candidate token (`Authorization: Bearer {token}`). Both keys empty → admin/candidate auth bypassed (dev/test).
> Generate keys: `openssl rand -hex 32`

## Project status

| Phase | Status | Deliverable |
|-------|--------|-------------|
| 0 | ✅ Done | Docker Compose, FastAPI factory, Alembic, middleware, structured logging |
| 1 | ✅ Done | Pydantic v2 contracts, SQLAlchemy models, Alembic env |
| 1.5 | ✅ Done | `seed.py` — 1 job, 6 candidates, 6 evals, 24 dim scores, 6 prompts |
| 2 | ✅ Done | `AIClient` dual-provider dispatch, audit writer, score validator |
| 3 | ✅ Done | `profile.py`, `ko_checker.py`, `scorer.py` — 10/10 unit tests passing |
| 4/5 | ✅ Done | Interview chatbot: Redis NX lock, state machine + AI eval pipeline, 4 endpoints |
| 4 rest | ✅ Done | `report_writer.py` — `GET /api/v1/jobs/{id}/report` |
| 6 | ✅ Done | Job Offer API (`api/jobs.py`) |
| 4.6 | ✅ Done | Hybrid interview: `dialogue_manager.py` — intent detection, follow-ups, v2 state schema |
| 4.7 | ✅ Done | CV upload (public, PDF/.md, capped at 5/job), auto-evaluation on 5th upload, per-candidate Bearer tokens, mock email (`CandidateInvitation` table) |
| 7 | ⏳ Next | Rate limiting |
| 8 | ⏳ | Acceptance test CI run |
| 9 | ⏳ | `/health` metrics, Prometheus, CloudWatch alarms |
| 10 | ⏳ | Mangum handler, SAM/CDK, GitHub Actions CI, staging deploy |

## Architecture

NovaHiring is an AI-assisted hiring platform. Core principle: **Python code is the brain; AI is only a language processing tool.** Hard decisions (knock-outs, scores) are always executed by code, never delegated to the model.

### Full pipeline

```
Candidate uploads CV  →  KO screening (Python, instant)
                              │
                    FALLA → DESCARTADO saved, done
                    PASA  → candidate saved
                              │
                   (5th CV triggers batch eval)
                              │
                    AI scores 8 dimensions per candidate
                    Scorer calculates weighted score
                              │
                    DESCARTADO → saved, no token
                    APTO       → token generated, simulated email logged
                              │
                    Candidate uses Bearer token → interview chatbot
                    8-dimension LLM conversation → AI scoring → final eval
                              │
                    Recruiter views ranking report
```

**CV upload cap:** maximum 5 candidates per job opening. The 5th upload triggers evaluation; any further upload returns 409 `applications_closed`.

### CV upload & evaluation flow (`api/candidates.py` + `services/cv_evaluator.py`)

1. `POST /api/v1/candidates/upload` (public) — validates file (.pdf / .md), extracts text via `pypdf` or UTF-8 decode, runs KO screening (`ProfileBuilder` + `KOChecker`), saves `Candidate`. Returns 409 if job is at 5-candidate cap or if duplicate SHA256 detected.
2. On the 5th upload, `BackgroundTasks` runs `_run_evaluation_batch_task(job_id)` — creates its own DB session, instantiates `CVEvaluator`.
3. `CVEvaluator.evaluate_job_candidates(job_id)` — finds all unevaluated candidates for the job, evaluates each:
   - Reuses stored `profile_json` for KO check (or rebuilds via `ProfileBuilder`)
   - DESCARTADO: creates `Evaluation(passed_ko=False)`, updates `candidate.passed_ko`
   - APTO: calls AI `cv_dimension_evaluator` (one call per dimension), runs `Scorer`, creates `Evaluation` + `DimensionScoreRecord` rows, calls `NotificationService`
4. `NotificationService.send_interview_invitation(candidate, job_id)` — generates UUID token via `TokenManager`, stores in Redis (`candidate_token:{uuid}`, 7-day TTL), creates `CandidateInvitation` in DB, logs `[SIMULATED EMAIL] To: ... | Token: ... | InvitationID: ...`.
5. `POST /api/v1/candidates/{job_id}/evaluate` (admin) — manually triggers the same `CVEvaluator` pipeline for any unevaluated candidates; idempotent.
6. `GET /api/v1/candidates/{job_id}` (admin) — lists all candidates with current status and score.

### Interview chatbot flow (hybrid — `api/interviews.py` + `services/interview_conductor.py`)

Auth: `Authorization: Bearer {candidate_token}` or `X-API-Key` (legacy/dev). Bearer token carries `{candidate_id, job_id}` — no body needed for `POST /sessions` when using a token.

1. `POST /api/v1/interviews/sessions` — creates session for an APTO candidate; returns welcome message + D1 question. Blocks DESCARTADO (422). Blocks duplicate active sessions (409).
2. `POST /api/v1/interviews/sessions/{id}/message` — receives answer, routes through `DialogueManager` (one LLM call via `interview_dialogue_conductor`). Intents:
   - **`requesting_correction`** → clears current dimension's turns, re-asks question
   - **`abandoning`** → closes session gracefully (`status=abandoned`)
   - **`asking_clarification`** → answers briefly, re-asks dimension question
   - **`answering`** (vague/relevant) → one targeted follow-up; `MAX_TURNS_PER_DIMENSION=3` then force-complete
   - **Off-topic (1st time)** → explains what is needed, prompts again
   - **Off-topic (2nd time)** → accepts "no experience", advances
   - **"I don't know"** → acknowledges with empathy, advances immediately
   - When `is_complete=True` → lock `answer_summary`, advance to next dimension
   - After all 8 dimensions locked → AI eval pipeline: one `interview_response_evaluator` call per dimension, `Scorer`, writes `Evaluation` + `DimensionScoreRecord`, marks `completed`
3. Redis NX lock (`session:{id}:processing`, TTL=30s) prevents concurrent messages → 409 `session_busy`.
4. `POST /api/v1/interviews/sessions/{id}/interrupt` — sets interrupt flag; eval pipeline checks it between AI calls.
5. `GET /api/v1/interviews/sessions/{id}` — full message history + current question index.
6. `GET /api/v1/jobs/{id}/report` — markdown ranking report (latest eval per candidate).

Session status values: `active` → `completed` | `abandoned` | `expired`.

Session state (v2 schema stored in `ChatSession.context_summary`):
```json
{"version":"2","current_dimension_index":3,"dimension_turns":{"D1":[{"role":"assistant","content":"..."},{"role":"user","content":"..."}]},"locked_answers":{"D1":"answer summary","D2":"..."},"evaluation_id":null}
```
`_load_state()` auto-migrates v1 state → v2 on first read.

### Infrastructure

| Component | Role |
|-----------|------|
| FastAPI | REST API |
| PostgreSQL 16 | All persistent state + audit log |
| Redis 7 | Session locks, interrupt flags, candidate tokens (7-day TTL) |
| Pydantic v2 | Data contracts (`contracts.py`) |
| SQLAlchemy 2 (async) | ORM with NullPool (Lambda-compatible) |
| Alembic | DB migrations |
| pypdf | PDF text extraction for CV upload |
| pytest + httpx | Tests (async, `asyncio_mode=auto`) |
| Claude Sonnet / GPT-4o | AI layer — provider set per prompt in DB |

### Prompt versions (6 active)

| Name | Provider | Model | Temp | Use |
|------|----------|-------|------|-----|
| `cv_dimension_evaluator` | anthropic | claude-sonnet-4-6 | 0.0 | CV scoring per dimension (v2 with `{{rubric_5}}`, `{{rubric_3}}`, `{{rubric_1}}`, `{{candidate_cv}}` placeholders) |
| `cv_dimension_evaluator_openai` | openai | gpt-4o-mini | 0.0 | Same, OpenAI variant |
| `narrative_report_writer` | anthropic | claude-sonnet-4-6 | 0.3 | Narrative ranking report |
| `narrative_report_writer_openai` | openai | gpt-4o | 0.3 | Same, OpenAI variant |
| `interview_response_evaluator` | anthropic | claude-sonnet-4-6 | 0.0 | Interview answer scoring |
| `interview_dialogue_conductor` | anthropic | claude-sonnet-4-6 | 0.3 | Per-dimension dialogue: follow-ups, clarifications, intent detection |

### AIClient template substitution pattern

`AIClient.call(prompt_name, template_vars, conversation_history)` copies `prompt.system_prompt`, substitutes `{{var}}` placeholders → sends the result as the **user message**. The original unsubstituted system_prompt is still sent as the system role. All prompts that receive dynamic data must have matching `{{...}}` placeholders in their system_prompt.

### Adding a new AI provider

1. Add a backend class to `services/ai_client.py` implementing `complete(system_prompt, messages, model, max_tokens, temperature) -> tuple[str, int, int]`.
2. Register it in `AIClient.__init__` under `self._backends["<provider>"]`.
3. Insert a `prompt_versions` row with `provider="<provider>"`. No code change needed after that.

### Intentionally excluded
LangChain, LangGraph, MongoDB, Kubernetes (for MVP), RAG, Streamlit/Gradio, Flowise/n8n, fine-tuning.

## Module structure

```
nova-hiring/
├── main.py                ← FastAPI app factory + CORS + request-ID middleware
├── config.py              ← Pydantic Settings (from .env)
├── database.py            ← Async SQLAlchemy (NullPool) + Redis singleton
├── contracts.py           ← All Pydantic v2 data contracts in one file
├── seed.py                ← Seed reference case + prompt versions
├── api/
│   ├── auth.py            ← require_admin / require_interview_access (Bearer or X-API-Key)
│   ├── jobs.py            ← GET /offer, /profile, /ranking, /report  [admin]
│   ├── candidates.py      ← POST /upload [public], GET /{job_id}, POST /{job_id}/evaluate [admin]
│   └── interviews.py      ← POST /sessions, /message, GET /sessions/{id}, /interrupt
│                             [Bearer candidate token or X-API-Key]
├── models/
│   ├── base.py            ← Base, TimestampMixin, new_uuid
│   ├── job.py             ← job_openings (discovery_json JSONB + offer_text)
│   ├── candidate.py       ← candidates (cv_text, cv_sha256, passed_ko, profile_json)
│   ├── evaluation.py      ← evaluations + dimension_scores
│   └── ops.py             ← prompt_versions, ai_call_logs, questions,
│                             chat_sessions, messages, candidate_invitations
├── services/
│   ├── profile.py              ← ProfileBuilder — keyword KO screening, zero AI
│   ├── ko_checker.py           ← KOChecker — first failing KO short-circuits
│   ├── scorer.py               ← Scorer — Σ(score × peso) / Σ(pesos)
│   ├── ai_client.py            ← AIClient + AnthropicBackend + OpenAIBackend + validators
│   ├── session_manager.py      ← Redis NX lock (Lua), interrupt flag, session meta hash
│   ├── dialogue_manager.py     ← LLM-driven per-dimension dialogue (intents, follow-ups)
│   ├── interview_conductor.py  ← Interview orchestrator: v2 state machine + AI eval pipeline
│   ├── cv_evaluator.py         ← CV eval: KO check + AI dim scoring + notification trigger
│   ├── token_manager.py        ← Per-candidate Bearer tokens in Redis (7-day TTL)
│   ├── notification_service.py ← Mock email: logs token, saves CandidateInvitation to DB
│   └── report_writer.py        ← Markdown ranking report generator
├── alembic/
│   └── env.py             ← Async migration runner
├── notebooks/
│   ├── demo_interview.ipynb        ← Offline scoring demo (no API calls)
│   ├── e2e_interview.ipynb         ← Live E2E: calls API + OpenAI
│   ├── e2e_hybrid_interview.ipynb  ← Hybrid dialogue E2E: exercises all 5 intents
│   └── e2e_hybrid_dataset.json     ← Scenario datasets for hybrid E2E
└── tests/
    ├── conftest.py                   ← discovery_fixture (full 8-dim scorecard)
    ├── test_unit.py                  ← 10 tests: Scorer + KOChecker
    ├── test_interview_unit.py        ← 37 tests: question structure, v1→v2 migration, scorer
    ├── test_dialogue_manager_unit.py ← 23 tests: DialogueManager, validator, intents
    └── test_acceptance.py            ← 5 tests requiring seeded DB
```

## Key design constraints

- **AI never makes hard decisions.** KO criteria and score calculations are always Python code.
- **Prompts versioned in the database.** Never hardcode prompts in source files — a prompt change is a behavior change and must be auditable.
- **Data contracts first.** `DiscoveryJSON` and `CandidateProfile` are defined before any business logic.
- **Audit log from commit 1.** Every AI call logged in `ai_call_logs`. Non-negotiable.
- **AI evaluation inputs.** Always pass the full candidate text (CV or interview answer), never a summary. Include rubric with numeric examples. Validate output range (1–5); retry max 2 times.
- **Session processing lock.** Redis NX mutex prevents concurrent messages to the same session. `409 session_busy` if lock held.
- **Provider set per prompt in DB.** Each `PromptVersion` row has a `provider` field. `AIClient` dispatches to the matching backend at call time — switching providers is a DB change, not a code change.
- **5-candidate cap per job.** `POST /upload` returns 409 `applications_closed` once the job has 5 candidates. Evaluation fires automatically on the 5th upload.
- **Background tasks use their own DB session.** Never pass a request-scoped `AsyncSession` to `BackgroundTasks` — create a new one via `async_session_factory()`.

## Reference case — Clínica Salud Valencia

All inputs and expected outputs exist in `docs/`.

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

**Expected ranking:**
| Rank | Candidate | Score | Status |
|------|-----------|-------|--------|
| #1 | Sofía Delgado | 4.84/5 | APTA |
| #2 | Carlos Rivas | 4.74/5 | APTO |
| #3 | Elena Martínez | 4.58/5 | APTA |
| — | Jhordan Solis | — | DESCARTADO (KO2) |
| — | Miguel Torres | — | DESCARTADO (KO1+KO2+KO3) |
| — | Ana Lombard | — | DESCARTADA (KO1+KO2+KO3) |

APTO candidate IDs (dev/testing): `cand-11-elena-martinez`, `cand-12-carlos-rivas`, `cand-13-sofia-delgado`

## Docs structure

```
docs/
├── specs/
│   ├── 03-discovery_dataset.json                          ← Question bank (niche: clinica_medica)
│   └── 03-discovery_simulation_clinica_salud_valencia.md  ← Full client discovery simulation
├── data/
│   ├── discovery-clinica-salud-valencia.json              ← Stage 1 output → seeded into job_openings
│   ├── conversations/                                     ← 4 interview scenario datasets
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
├── cv-20-06-2026/                                         ← 6 sample candidate CVs (Markdown)
├── architecture/
│   └── 00-arquitectura-novahiring.md
├── vacante-clinica-salud-valencia.md                      ← Job description (seeded as offer_text)
└── 04-backend-architecture.md                             ← Full backend architecture plan
```
