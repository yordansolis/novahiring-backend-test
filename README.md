# NovaHiring

AI-assisted hiring platform. Core principle: **Python code is the brain; AI is only a language processing tool.** Hard decisions (knock-outs, scores) are always executed by code, never delegated to the model.

---

## Quickstart

```bash
# First-time setup: deps + Docker + migrations + seed data
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
uv run python seed.py update-cv-evaluator   # seeds v2 prompt with template placeholders
uv run fastapi dev main.py
```

### Common commands

| Command | What it does |
|---------|--------------|
| `make init` | First-time setup (deps + Docker + migrations + seed) |
| `make start-dev` | Start Docker + FastAPI dev server |
| `make seed` | Re-seed reference case and prompts |
| `make clean-sessions` | Delete interview sessions and AI call logs; keep seeded reference data |
| `make test` | Run all tests |
| `make test-unit` | Unit tests only — no DB, no Redis, no AI required |
| `make test-acceptance` | Acceptance tests — requires seeded DB |
| `uv run python seed.py update-cv-evaluator` | Push updated `cv_dimension_evaluator` prompt to DB |
| `uv run python seed.py update-dialogue` | Push updated `interview_dialogue_conductor` prompt to DB |
| `uv run python seed.py use-openai` | Switch both interview prompts to OpenAI |
| `uv run python seed.py use-anthropic` | Switch both interview prompts back to Anthropic |

---

## How it works — the full pipeline

```
Candidate uploads CV
        │
        ▼
KO screening (Python, instant, no AI)
        │
        ├── FALLA → marked DESCARTADO, no further action
        │
        └── PASA → candidate saved, waiting for batch
                        │
              (when job reaches 5+ CVs)
                        │
                        ▼
           AI evaluates each APTO candidate
           8 dimensions × 1 AI call each
           Scorer calculates weighted score
                        │
                        ├── DESCARTADO → saved, no token
                        │
                        └── APTO → token generated
                                   simulated email logged
                                        │
                                        ▼
                              Candidate uses token
                              to access chatbot
                                        │
                              8-dimension interview
                              (LLM drives conversation)
                                        │
                                        ▼
                              AI scores each answer
                              Final evaluation saved
                                        │
                                        ▼
                              Recruiter sees ranking report
```

---

## API reference

### Access levels

| Level | Header | Who uses it |
|-------|--------|-------------|
| **Public** | _(none)_ | Candidates uploading their CV |
| **Admin** | `X-API-Key: {API_KEY_ADMIN}` | Recruiters and internal tools |
| **Candidate token** | `Authorization: Bearer {token}` | Selected (APTO) candidates in the chatbot |

In dev mode (keys not set in `.env`), auth is bypassed on all endpoints.

---

### CV upload — public

**`POST /api/v1/candidates/upload`**

Any candidate can submit a CV for a job opening. No account or auth required.

- Accepted formats: `.pdf` (text-based) or `.md`
- KO screening runs immediately (keyword matching, no AI)
- **Maximum 5 CVs per job.** When the 5th CV is received, the position closes and AI evaluation starts automatically in the background. Any further upload attempt returns 409 `applications_closed`.
- The same CV (identical content) cannot be submitted twice for the same job → 409 `duplicate_cv`

```bash
curl -X POST http://localhost:8000/api/v1/candidates/upload \
  -F "job_id=job-clinica-salud-valencia-001" \
  -F "nombre=María García" \
  -F "email=maria@example.com" \
  -F "cv_file=@my-cv.pdf"
```

```json
{ "candidate_id": "uuid", "status": "received", "passed_ko": true }
```

---

### Candidate list — admin

**`GET /api/v1/candidates/{job_id}`**

Returns all candidates for a job with their current status. `resultado` is `null` if evaluation hasn't run yet.

```bash
curl http://localhost:8000/api/v1/candidates/job-clinica-salud-valencia-001 \
  -H "X-API-Key: {API_KEY_ADMIN}"
```

```json
[
  { "candidate_id": "...", "nombre": "Sofía Delgado", "email": "sofia@example.com",
    "passed_ko": true, "resultado": "APTO", "weighted_score": "4.84" },
  { "candidate_id": "...", "nombre": "Jhordan Solis", "email": "jhordan@example.com",
    "passed_ko": false, "resultado": "DESCARTADO", "weighted_score": null }
]
```

---

### Trigger evaluation — admin

**`POST /api/v1/candidates/{job_id}/evaluate`**

Manually run AI evaluation for all candidates without an existing result. Use this to evaluate before the 5-candidate threshold, or to pick up newly uploaded CVs.

```bash
curl -X POST http://localhost:8000/api/v1/candidates/job-clinica-salud-valencia-001/evaluate \
  -H "X-API-Key: {API_KEY_ADMIN}"
```

```json
{ "job_id": "job-clinica-salud-valencia-001", "queued_candidates": 3, "status": "evaluation_started" }
```

After this call returns, check the server logs for `[SIMULATED EMAIL]` lines — each one contains the access token for an APTO candidate.

---

### Job reports — admin

```
GET /api/v1/jobs/{job_id}/offer     → Job description (markdown)
GET /api/v1/jobs/{job_id}/profile   → KO criteria + scorecard dimensions + required skills
GET /api/v1/jobs/{job_id}/ranking   → Candidates sorted by score (APTO first, then DESCARTADO)
GET /api/v1/jobs/{job_id}/report    → Full narrative markdown report
```

All require `X-API-Key: {API_KEY_ADMIN}`.

---

### Interview chatbot — candidate token

After evaluation, APTO candidates get a personal access token. The server logs a line like:

```
[SIMULATED EMAIL] To: sofia@example.com | Candidate: Sofía Delgado | Token: abc-123-... | InvitationID: ...
```

That token is valid for 7 days and unlocks the interview endpoints.

---

**`POST /api/v1/interviews/sessions`** — start the interview

```bash
# Production: token in header, no body needed
curl -X POST http://localhost:8000/api/v1/interviews/sessions \
  -H "Authorization: Bearer {candidate_token}"

# Dev/testing: admin key + body
curl -X POST http://localhost:8000/api/v1/interviews/sessions \
  -H "Content-Type: application/json" \
  -d '{"job_id": "job-clinica-salud-valencia-001", "candidate_id": "cand-11-elena-martinez"}'
```

```json
{
  "session_id": "uuid",
  "status": "active",
  "message": { "role": "assistant", "content": "Welcome! Let's start..." },
  "next_question": { "dimension_id": "D1", "question_text": "Describe your experience..." }
}
```

Gates:
- Candidate with `passed_ko=false` → 422 `candidate_not_eligible`
- Active session already exists → 409 `session_already_exists` (returns existing `session_id`)

---

**`POST /api/v1/interviews/sessions/{id}/message`** — send an answer

```bash
curl -X POST http://localhost:8000/api/v1/interviews/sessions/{session_id}/message \
  -H "Authorization: Bearer {candidate_token}" \
  -H "Content-Type: application/json" \
  -d '{"content": "I integrated WhatsApp Business API at my previous company..."}'
```

Returns the next question, a follow-up, or the final evaluation result once all 8 dimensions are complete. Returns 409 `session_busy` if a previous message is still being processed.

---

**`GET /api/v1/interviews/sessions/{id}`** — session state

Full message history + current question index + status.

**`POST /api/v1/interviews/sessions/{id}/interrupt`** — abort evaluation

Cancels an in-progress AI scoring pipeline (checked between each of the 8 AI calls).

---

### How the interview conversation works

For each of the 8 dimensions, one LLM call classifies the candidate's intent and decides what to do next:

| Candidate says | System does |
|---|---|
| Clear, direct answer | Locks the answer, moves to the next dimension |
| Vague but relevant answer | Asks one targeted follow-up (phrasing always varies) |
| Off-topic answer (1st time) | Explains what the question is looking for, asks again |
| Off-topic answer (2nd time) | Accepts "no experience in this area", advances |
| "I don't know" / "no experience" | Acknowledges with empathy, advances immediately |
| Asks for clarification | Answers briefly, re-asks the original question |
| "I want to correct my answer" | Clears the dimension history, re-asks the question |
| "I want to quit" | Closes the session gracefully |

After 3 candidate turns per dimension, answers are force-collected and the next dimension begins.
After all 8 dimensions are locked, one AI call per dimension scores the answers (validated 1–5).

---

## Reference case — Clínica Salud Valencia

All inputs and expected outputs are in `docs/`. Use `job_id = job-clinica-salud-valencia-001`.

**Client:** Clínica Salud Valencia S.L. — private multi-specialty clinic, Valencia, Spain
**Problem:** 15–20 lost appointments/week (~€4,000/month). Single receptionist, fully manual.
**Budget:** €8,000–12,000, 3-month deadline.

### KO criteria

| ID | Criterion |
|----|-----------|
| KO1 | No experience with WhatsApp Business API (Meta) |
| KO2 | No demonstrated understanding of RGPD/LOPDGDD for health data |
| KO3 | Can only work with external technical supervision |

### Scorecard (8 dimensions, weights sum to 19)

| ID | Dimension | Weight |
|----|-----------|--------|
| D1 | Technical integrations — WhatsApp, Google Calendar, reception panel | ×3 |
| D2 | RGPD/LOPDGDD compliance for health data | ×3 |
| D3 | Autonomy and technical decision-making | ×3 |
| D4 | Build-vs-buy pragmatism | ×3 |
| D5 | Delivery under tight deadlines | ×2 |
| D6 | Communication with non-technical profiles | ×2 |
| D7 | Health sector experience | ×2 |
| D8 | Stack fit for budget | ×1 |

**Formula:** `Score = Σ(score × weight) / Σ(weights)`, scale 1–5.

### Expected ranking

| Rank | Candidate | Score | Status |
|------|-----------|-------|--------|
| #1 | Sofía Delgado | 4.84 / 5 | APTA |
| #2 | Carlos Rivas | 4.74 / 5 | APTO |
| #3 | Elena Martínez | 4.58 / 5 | APTA |
| — | Jhordan Solis | — | DESCARTADO (KO2) |
| — | Miguel Torres | — | DESCARTADO (KO1 + KO2 + KO3) |
| — | Ana Lombard | — | DESCARTADA (KO1 + KO2 + KO3) |

APTO candidate IDs (for dev/testing): `cand-11-elena-martinez`, `cand-12-carlos-rivas`, `cand-13-sofia-delgado`.

---

## AI providers

Both Anthropic and OpenAI are supported. The provider is set **per prompt version in the database** — switching is a DB row change, not a code change.

| Prompt | Provider | Model | Temp | Purpose |
|--------|----------|-------|------|---------|
| `cv_dimension_evaluator` | Anthropic | claude-sonnet-4-6 | 0.0 | Score CV against each dimension rubric |
| `cv_dimension_evaluator_openai` | OpenAI | gpt-4o-mini | 0.0 | Same, OpenAI variant |
| `interview_response_evaluator` | Anthropic | claude-sonnet-4-6 | 0.0 | Score interview answers |
| `interview_dialogue_conductor` | Anthropic | claude-sonnet-4-6 | 0.3 | Drive per-dimension conversation (intents, follow-ups) |
| `narrative_report_writer` | Anthropic | claude-sonnet-4-6 | 0.3 | Generate markdown ranking report |
| `narrative_report_writer_openai` | OpenAI | gpt-4o | 0.3 | Same, OpenAI variant |

To add a new provider: implement a backend in `services/ai_client.py`, register it in `AIClient.__init__`, then insert a `prompt_versions` row with the new `provider` value.

---

## Project structure

```
nova-hiring/
├── main.py               ← FastAPI app factory + CORS + request-ID middleware
├── config.py             ← Pydantic Settings (reads .env)
├── database.py           ← Async SQLAlchemy (NullPool) + Redis singleton
├── contracts.py          ← All Pydantic v2 data contracts in one file
├── seed.py               ← Seeds reference case + prompt versions
│
├── api/
│   ├── auth.py           ← require_admin / require_interview_access (Bearer or X-API-Key)
│   ├── jobs.py           ← GET /offer, /profile, /ranking, /report          [admin]
│   ├── candidates.py     ← POST /upload [public], GET + POST /evaluate      [admin]
│   └── interviews.py     ← POST /sessions, /message, GET /sessions, /interrupt
│
├── models/
│   ├── base.py           ← Base, TimestampMixin, new_uuid
│   ├── job.py            ← job_openings
│   ├── candidate.py      ← candidates (cv_text, cv_sha256, passed_ko, profile_json)
│   ├── evaluation.py     ← evaluations + dimension_scores
│   └── ops.py            ← prompt_versions, ai_call_logs, chat_sessions,
│                            messages, candidate_invitations
│
├── services/
│   ├── profile.py              ← ProfileBuilder — keyword KO screening, zero AI
│   ├── ko_checker.py           ← KOChecker — first failing KO short-circuits
│   ├── scorer.py               ← Scorer — Σ(score × peso) / Σ(pesos)
│   ├── ai_client.py            ← AIClient + AnthropicBackend + OpenAIBackend + validators
│   ├── session_manager.py      ← Redis NX lock (Lua), interrupt flag, session meta hash
│   ├── dialogue_manager.py     ← LLM dialogue per dimension: intent detection, follow-ups
│   ├── interview_conductor.py  ← Interview orchestrator: v2 state machine + AI eval pipeline
│   ├── cv_evaluator.py         ← CV eval pipeline: KO + AI dim scoring + notification
│   ├── token_manager.py        ← Per-candidate Bearer tokens in Redis (7-day TTL)
│   ├── notification_service.py ← Mock email: logs token, saves CandidateInvitation to DB
│   └── report_writer.py        ← Markdown ranking report generator
│
├── alembic/
│   └── env.py            ← Async migration runner
│
└── tests/
    ├── conftest.py                   ← discovery_fixture (8-dim scorecard)
    ├── test_unit.py                  ← 10 tests: Scorer + KOChecker
    ├── test_interview_unit.py        ← 37 tests: question structure, v1→v2 migration, scoring
    ├── test_dialogue_manager_unit.py ← 23 tests: DialogueManager, validator, intents
    └── test_acceptance.py            ← 5 tests: full flow, requires seeded DB
```

---

## Development

**Dependencies:** `fastapi`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `redis`, `pydantic-settings`, `anthropic`, `openai`, `pypdf`, `httpx`, `pytest`, `pytest-asyncio`.

**`.env` keys:**

```
DATABASE_URL=postgresql+asyncpg://nova:nova_dev@localhost:5432/nova_hiring
REDIS_URL=redis://localhost:6379
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
API_KEY_ADMIN=...        # leave empty in dev to bypass auth
API_KEY_CANDIDATES=...   # leave empty in dev to bypass auth
```

Unit tests need no running services and no API keys:

```bash
uv run pytest tests/test_unit.py tests/test_interview_unit.py tests/test_dialogue_manager_unit.py -v
# → 70 tests, 0 DB, 0 Redis, 0 AI calls
```

---

## Implementation status

| Phase | Status | Deliverable |
|-------|--------|-------------|
| 0 | ✅ | Docker Compose, FastAPI factory, Alembic, middleware, structured logging |
| 1 | ✅ | Pydantic v2 contracts, SQLAlchemy models |
| 1.5 | ✅ | `seed.py` — 1 job, 6 candidates, 6 evals, 24 dim scores, 6 prompt versions |
| 2 | ✅ | AIClient dual-provider dispatch, audit log, score validator |
| 3 | ✅ | `profile.py`, `ko_checker.py`, `scorer.py` — 10/10 unit tests |
| 4/5 | ✅ | Interview chatbot: Redis NX lock, state machine, AI eval pipeline, 4 endpoints |
| 4 rest | ✅ | `report_writer.py` — `GET /api/v1/jobs/{id}/report` |
| 4.6 | ✅ | Hybrid dialogue: `dialogue_manager.py` — intent detection, follow-ups, v2 state schema |
| 4.7 | ✅ | CV upload (public), auto-evaluation (≥5 candidates), per-candidate Bearer tokens, mock email |
| 6 | ✅ | Job Offer API (`api/jobs.py`) |
| 7 | ⏳ | Rate limiting |
| 8 | ⏳ | Acceptance test CI run |
| 9 | ⏳ | `/health` metrics, Prometheus, CloudWatch alarms |
| 10 | ⏳ | Mangum handler, SAM/CDK, GitHub Actions CI, staging deploy |
