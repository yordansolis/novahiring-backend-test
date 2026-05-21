# What We Built — Simple Summary

## The Problem: A Robot That Didn't Listen

Before this change, NovaHiring's interview chatbot worked like a vending machine.

You press a button → it gives you a snack. No conversation. No "wait, what did you mean?" Just: next question, next question, next question.

If a candidate said *"I don't understand the question"*, the system would treat that sentence as their actual answer and move on. If they wanted to give more detail, too bad — it had already moved to question #2.

---

## The Solution: A Real Interviewer (Sort Of)

We turned the robot into something that behaves more like a human interviewer. It can now:

| What the candidate does | What the system does now |
|---|---|
| Gives a vague answer | Asks one follow-up question |
| Asks "what do you mean by X?" | Answers briefly, then re-asks the original question |
| Says "I want to correct that" | Clears the answer and lets them try again |
| Says "I want to quit" | Says goodbye nicely and closes the session |

---

## How It Works — The Kitchen Analogy

Think of the system like a restaurant kitchen with two separate roles:

### 🧠 The Head Chef (Python Code — unchanged)
The head chef decides the **menu** (which 8 questions to ask), the **recipe** (how to score answers 1–5), and the **rules** (if a candidate fails a knock-out criterion, they're out). The head chef never improvises. Every decision is written in stone.

### 🗣️ The Waiter (The LLM — new)
The waiter talks to the customer (candidate). When the customer is vague, the waiter asks "could you be more specific?" When the customer is confused, the waiter explains and asks again. When the customer is ready to leave, the waiter says goodbye.

But the **waiter never decides the score**. That's always the head chef's job.

---

## What We Actually Built

### New file: `services/dialogue_manager.py`
This is the "waiter." For every message a candidate sends, this file:
1. Reads what the candidate wrote
2. Sends it to the AI (Claude) with the current question and scoring rubric
3. Gets back a decision: *"Is this answer good enough? Do I need a follow-up? Did they ask a question? Do they want to leave?"*
4. Returns that decision to the rest of the system

**Safety net:** If the AI gives a broken response, the system doesn't crash — it just treats whatever the candidate said as their final answer and moves on.

**Turn limit:** Each question allows up to **3 candidate messages**. After that, the system automatically collects everything the candidate said and moves to the next question. No infinite loops.

### Updated: `services/interview_conductor.py`
This is the "kitchen manager" — it coordinates everything. We rewrote the main message-handling function to:
1. Save the candidate's message to the database immediately
2. Ask the dialogue manager what to do
3. Based on the answer: follow up, close the session, restart the question, or move to the next one
4. When all 8 questions are answered, send everything to the AI evaluator (unchanged from before)

### New prompt in the database: `interview_dialogue_conductor`
This is the "instruction card" the AI reads before deciding what to do. It tells the AI:
- What question was asked
- What the scoring rubric looks like (secretly — the candidate never sees this)
- What the conversation so far looks like
- How to classify what the candidate just said
- How to respond (always in Spanish, always professionally)
- What format to return (a small JSON with 4 fields)

### New session state (version 2)
We changed how the interview's progress is saved. Before, it looked like this:

```
Current question: 3
Answers: { D1: "...", D2: "...", D3: "..." }
```

Now it looks like this:

```
Current question: 3
Per-question conversation history: { D1: [question, answer, follow-up, answer], D2: [...] }
Locked answers (used for scoring): { D1: "summary of what they said", D2: "..." }
```

**Old sessions still work** — the system automatically converts the old format to the new one the first time it reads it.

---

## What Did NOT Change

These things are exactly the same as before — we didn't touch them:

- ✅ The 8 interview questions (same questions, same order)
- ✅ The 3 knock-out criteria (KO1, KO2, KO3)
- ✅ The scoring formula: `Σ(score × weight) / Σ(weights)`
- ✅ The AI evaluator (`interview_response_evaluator` prompt)
- ✅ The Redis lock that prevents two messages being processed at the same time
- ✅ The interrupt flag that can stop the evaluation mid-way
- ✅ The audit log (every AI call is still recorded in `ai_call_logs`)
- ✅ The final ranking report

---

## Files Created or Changed

| File | What happened |
|---|---|
| `services/dialogue_manager.py` | **New.** The "waiter" — handles per-question conversation |
| `services/interview_conductor.py` | **Rewritten.** Now uses DialogueManager; v2 state schema |
| `api/interviews.py` | **Small update.** Injects DialogueManager into the conductor |
| `contracts.py` | **Small update.** Added `DialogueTurn` type |
| `seed.py` | **Updated.** Added the new `interview_dialogue_conductor` prompt |
| `tests/test_dialogue_manager_unit.py` | **New.** 23 tests for the dialogue manager (no database needed) |
| `tests/test_interview_unit.py` | **Updated.** Old state tests became migration tests; new v2 tests added |
| `CLAUDE.md` | **Updated.** Documents the new architecture and phase |

---

## Test Results

```
70 tests — 70 passed — 0 failed
```

All tests run without a database, without Redis, and without real AI calls. Fast and reliable.

---

## How to Use It (After Seeding)

```bash
# Add the new prompt to the database
uv run python seed.py prompts

# Start the server
make start-dev
```

Then when a candidate sends a message, instead of always moving to the next question, the system might respond:

> *"Tu respuesta menciona experiencia con APIs de mensajería, pero necesito entender mejor el caso de uso específico. ¿Integraste WhatsApp Business API directamente con la plataforma Meta, o usaste un intermediario como Twilio?"*

And if the candidate asks a question back:

> *"La WhatsApp Business API es la interfaz oficial de Meta que permite a las empresas enviar mensajes automatizados. ¿Tienes experiencia trabajando con ella directamente?"*

The AI handles the conversation. Python handles the decisions that matter.
