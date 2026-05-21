╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 Plan: Hybrid Interview System — Conversational Dialogue with Deterministic Evaluation

 Context

 The current interview chatbot (interview_conductor.py) is a rigid linear state machine: one candidate message = one answer locked = advance to next dimension. It cannot handle
 candidate questions, cannot ask follow-ups when answers are vague, and detects intent only via brittle keyword matching. The goal is to transform it into a hybrid system where:

 - The LLM drives natural conversation per dimension (follow-ups, clarification answers, intent detection)
 - Python code remains the brain: question order, KO criteria, score formula, and evaluation rubrics are all unchanged and deterministic

 The evaluation pipeline (interview_response_evaluator) and scoring layer (Scorer) are untouched. Only what happens between "question asked" and "answer locked" changes.

 ---
 Architecture Overview

 Candidate message
       │
       ▼
 [InterviewConductor.handle_answer()]
       │
       ├─ Load state (v1→v2 migration if needed)
       ├─ Save user message to DB
       │
       ▼
 [DialogueManager.process_turn()]           ← NEW
       │  (calls interview_dialogue_conductor prompt)
       │  Returns: response, is_complete, answer_summary, intent
       │
       ├─ intent == "abandoning"  → close session (existing logic)
       ├─ intent == "requesting_correction" → clear dimension turns, re-ask
       ├─ is_complete == True     → lock answer_summary, advance dimension
       │       └─ all 8 locked   → trigger _run_evaluation_pipeline()
       └─ is_complete == False    → save turn, return same dimension info

 The deterministic layers (unchanged):
 - 8 fixed questions, fixed order (D1–D8)
 - KO criteria: ko_checker.py
 - Score formula: Scorer.calculate() — Σ(score×peso)/Σ(pesos)
 - Evaluation: interview_response_evaluator prompt called once per dimension after all answers locked

 ---
 New File: services/dialogue_manager.py

 MAX_TURNS_PER_DIMENSION = 3  # candidate turns per dimension before force-complete

 class DialogueResponseValidator:
     VALID_INTENTS = {"answering", "asking_clarification", "requesting_correction", "abandoning"}
     def validate(self, response_text: str) -> bool: ...  # checks JSON schema + intent value

 class DialogueManager:
     def __init__(self, ai_client: AIClient) -> None: ...

     async def process_turn(
         self,
         dimension: ScorecardDimension,   # from contracts.py
         question_text: str,
         turns: list[dict],               # prior turns for this dimension (role/content)
         candidate_message: str,
         session_id: str,
         request_id: str,
     ) -> dict:                           # {response, is_complete, answer_summary, intent}

 Key behaviors:
 - If candidate turns already in turns >= MAX_TURNS_PER_DIMENSION: call _force_complete_summary() — concatenates all prior + current candidate messages, returns is_complete=True
  without an LLM call.
 - Otherwise: call ai_client.call("interview_dialogue_conductor", template_vars, conversation_history=[], ...) with DialogueResponseValidator.
 - On malformed LLM JSON: fallback to is_complete=True, answer_summary=raw_text, intent="answering" (prevents stuck sessions).

 _force_complete_summary logic: Join all role=="user" content from turns + candidate_message with "\n\n". The evaluator handles multi-paragraph text fine (proven by dataset
 scenarios).

 ---
 New Prompt: interview_dialogue_conductor

 Seeded via seed.py. Parameters:
 - provider: "anthropic", model: "claude-sonnet-4-6", temperature: 0.3 (slight variation for natural phrasing), max_tokens: 1024

 Template variables: {{dimension_id}}, {{dimension_name}}, {{rubric_5}}, {{rubric_3}}, {{rubric_1}}, {{question_text}}, {{conversation_history}}, {{candidate_message}}

 The prompt instructs the LLM to:
 1. Classify intent (answering / asking_clarification / requesting_correction / abandoning)
 2. For asking_clarification: answer briefly, re-ask the question, is_complete=false
 3. For requesting_correction: is_complete=false (system clears turns and re-asks)
 4. For abandoning: is_complete=false (system closes session)
 5. For answering: if answer maps clearly to any rubric level → is_complete=true + answer_summary; if too vague → one follow-up question, is_complete=false
 6. candidate_message is wrapped in <candidate_message> tags with a prompt injection warning
 7. Returns ONLY JSON: {"response": "...", "is_complete": bool, "answer_summary": str|null, "intent": "..."}

 ---
 State Schema: Version "2" + Migration

 New structure (stored in ChatSession.context_summary):

 {
   "version": "2",
   "session_type": "interview",
   "job_id": "...",
   "candidate_id": "...",
   "current_dimension_index": 3,
   "dimension_turns": {
     "D1": [
       {"role": "assistant", "content": "Question text"},
       {"role": "user", "content": "Candidate answer"},
       {"role": "assistant", "content": "Follow-up from LLM"}
     ]
   },
   "locked_answers": {
     "D1": "Answer summary used for evaluation"
   },
   "evaluation_id": null
 }

 Migration in _load_state():

 def _load_state(session) -> dict:
     raw = json.loads(session.context_summary) if session.context_summary else {}
     if raw.get("version") == "2": return raw
     return _migrate_v1_to_v2(raw)   # promotes "answers" → "locked_answers"

 def _migrate_v1_to_v2(v1: dict) -> dict:
     return {
         "version": "2", ...,
         "current_dimension_index": v1.get("current_question_index", 0),
         "dimension_turns": {},
         "locked_answers": {k: v for k, v in v1.get("answers", {}).items()},
         "evaluation_id": v1.get("evaluation_id"),
     }

 No Alembic migration needed — context_summary is a Text column; schema lives in application JSON.

 ---
 Changes to Existing Files

 services/interview_conductor.py

 - InterviewConductor.__init__: add dialogue_manager: DialogueManager parameter
 - create_session: emit v2 state dict instead of v1
 - handle_answer (major rewrite):
   a. Load + migrate state to v2
   b. Save user message to DB immediately (before LLM call)
   c. Load job once for rubric access → build ScorecardDimension for current dim
   d. Call self._dm.process_turn(...)
   e. Dispatch on intent: abandoning → close; requesting_correction → _handle_correction_v2
   f. Append assistant response to dimension_turns
   g. If is_complete: lock answer_summary → locked_answers[dim_id], advance index
       - If all 8 locked → _run_evaluation_pipeline(locked_answers)
     - Else → send next dimension's question, seed dimension_turns[next_dim_id]
   h. Else: save turns, return same QuestionInfo (same dimension, still active)
 - _run_evaluation_pipeline: call site changes state["answers"] → state["locked_answers"]; method signature unchanged
 - _handle_correction_v2: clears dimension_turns[current_dim_id], pops from locked_answers, re-sends question (corrects only current active dimension — prior locked dimensions
 are unaffected)
 - _handle_abandonment_v2: skips re-saving user message (already saved before process_turn)

 api/interviews.py

 - _get_conductor factory: instantiate and inject DialogueManager(ai_client)
 - get_session endpoint: read current_dimension_index from v2 state (fallback to current_question_index for v1)

 seed.py

 - Add interview_dialogue_conductor to PROMPTS list (6th prompt, anthropic, temperature=0.3)

 contracts.py

 - Add DialogueTurn = TypedDict("DialogueTurn", {"role": str, "content": str})
 - No existing models changed

 ---
 Test Strategy

 Existing tests that break (4 in test_interview_unit.py):

 - State tests that reference state["current_question_index"] and state["answers"]

 Fix strategy (Option B — preferred):
 - Keep old state tests as-is → they become regression tests for _migrate_v1_to_v2
 - Add a new TestStateMigration class with 4 tests:  test_v1_migrates_answers_to_locked, test_v1_migrates_index, test_v2_passes_through, test_empty_returns_v2_defaults
 - Add TestV2State class replacing the broken tests: test_v2_locked_answers_accumulate, test_v2_dimension_turns_roundtrip

 New test file: tests/test_dialogue_manager_unit.py (no DB, no real AI)

 Uses FakeAIClient returning canned JSON. Tests:
 1. test_complete_on_first_answer — LLM returns is_complete=True
 2. test_incomplete_triggers_followup — LLM returns is_complete=False
 3. test_asking_clarification_intent
 4. test_abandoning_intent
 5. test_requesting_correction_intent
 6. test_max_turns_forces_complete_without_llm_call — fill 3 user turns, verify no AI call
 7. test_force_complete_concatenates_all_user_turns
 8. test_validator_valid_json
 9. test_validator_missing_intent
 10. test_validator_bad_intent_value
 11. test_parse_fallback_on_bad_json

 Acceptance tests (test_acceptance.py): unchanged

 - Score assertions test seeded evaluations from seed.py (not live interviews) → no breakage

 ---
 Implementation Order

 1. contracts.py — add DialogueTurn (no breaking changes)
 2. services/dialogue_manager.py — new file, write with unit tests
 3. seed.py — add new prompt entry
 4. interview_conductor.py — add migration functions + rewrite handle_answer
 5. api/interviews.py — inject DialogueManager, fix state key read
 6. Update test_interview_unit.py — add migration + v2 state tests
 7. Run uv run python seed.py prompts to seed new prompt to DB

 ---
 Verification

 # Unit tests (no DB/AI/Redis required)
 uv run pytest tests/test_interview_unit.py tests/test_dialogue_manager_unit.py -v
     Verification

     # Unit tests (no DB/AI/Redis required)
     uv run pytest tests/test_interview_unit.py tests/test_dialogue_manager_unit.py -v

     # Acceptance tests (requires seeded DB)
     uv run pytest tests/test_acceptance.py -v

     # Full test suite
     uv run pytest

     # Live E2E (optional): start server + exercise hybrid interview
     make start-dev
     # Then POST /api/v1/interviews/sessions to create session, POST /sessions/{id}/message
     # with ambiguous answers — verify follow-up questions appear
     # with clarification questions ("¿qué significa WhatsApp Business API?") — verify LLM answers and re-asks
     # with abandonment ("quiero abandonar") — verify session closes

     Key behavior to verify manually:
     - Ambiguous answer → LLM asks one follow-up (not multiple)
     - Candidate asks "¿qué significa X?" → LLM answers briefly + re-asks question
     - After 3 candidate turns, forced completion without extra LLM call
     - Correction request → dimension turns cleared, question re-asked
     - After all 8 dimensions locked → evaluation pipeline runs, scores + report generated

     ---
     Design Constraints Preserved

     - AI never makes hard decisions (KO + scoring = Python code)
     - Every LLM call logged in ai_call_logs (unchanged)
     - Redis NX lock still prevents concurrent messages
     - Interrupt flag still checked between AI calls in evaluation pipeline
     - Prompts versioned in DB (new prompt follows same pattern)
     - interview_response_evaluator prompt is unchanged — receives locked_answers same as before