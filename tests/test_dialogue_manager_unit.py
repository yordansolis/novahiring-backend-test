"""
Unit tests for DialogueManager.
No DB, no Redis, no real AI calls.
"""
import json

import pytest

from contracts import ScorecardDimension
from services.dialogue_manager import (
    MAX_TURNS_PER_DIMENSION,
    DialogueManager,
    DialogueResponseValidator,
    _build_history_text,
    _force_complete_summary,
    _parse_llm_response,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

SAMPLE_DIMENSION = ScorecardDimension(
    id="D1",
    nombre="Integraciones técnicas",
    peso=3,
    rubricas={
        "5": "Implementó WhatsApp Business API con casos de uso reales",
        "3": "Tiene experiencia básica con APIs de mensajería",
        "1": "Sin experiencia con WhatsApp Business API",
    },
)

SAMPLE_QUESTION = "Describe tu experiencia con WhatsApp Business API."


class FakeAIClient:
    """Minimal fake that stores what it was called with and returns canned responses."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def call(self, prompt_name, template_vars, conversation_history, **kwargs) -> str:
        self.calls.append({
            "prompt_name": prompt_name,
            "template_vars": template_vars,
        })
        if self._responses:
            return self._responses.pop(0)
        return json.dumps({
            "response": "Respuesta por defecto.",
            "is_complete": True,
            "answer_summary": "Resumen por defecto.",
            "intent": "answering",
        })


def make_manager(responses: list[str]) -> tuple[DialogueManager, FakeAIClient]:
    client = FakeAIClient(responses)
    return DialogueManager(client), client


# ── DialogueResponseValidator ─────────────────────────────────────────────────

def test_validator_accepts_valid_complete_response():
    v = DialogueResponseValidator()
    payload = json.dumps({
        "response": "Entendido.",
        "is_complete": True,
        "answer_summary": "El candidato tiene experiencia.",
        "intent": "answering",
    })
    assert v.validate(payload) is True


def test_validator_accepts_valid_incomplete_response():
    v = DialogueResponseValidator()
    payload = json.dumps({
        "response": "¿Puedes darme más detalles?",
        "is_complete": False,
        "answer_summary": None,
        "intent": "asking_clarification",
    })
    assert v.validate(payload) is True


def test_validator_rejects_missing_intent():
    v = DialogueResponseValidator()
    payload = json.dumps({"response": "ok", "is_complete": False})
    assert v.validate(payload) is False


def test_validator_rejects_bad_intent_value():
    v = DialogueResponseValidator()
    payload = json.dumps({"response": "ok", "is_complete": False, "intent": "unknown_intent"})
    assert v.validate(payload) is False


def test_validator_rejects_empty_response():
    v = DialogueResponseValidator()
    payload = json.dumps({"response": "", "is_complete": False, "intent": "answering"})
    assert v.validate(payload) is False


def test_validator_rejects_invalid_json():
    v = DialogueResponseValidator()
    assert v.validate("not json at all") is False


def test_validator_rejects_non_bool_is_complete():
    v = DialogueResponseValidator()
    payload = json.dumps({"response": "ok", "is_complete": "yes", "intent": "answering"})
    assert v.validate(payload) is False


# ── _build_history_text ───────────────────────────────────────────────────────

def test_build_history_text_empty_turns():
    text = _build_history_text([])
    assert "No hay turnos previos" in text


def test_build_history_text_with_turns():
    turns = [
        {"role": "assistant", "content": "¿Cuál es tu experiencia?"},
        {"role": "user", "content": "Tengo 2 años."},
    ]
    text = _build_history_text(turns)
    assert "Entrevistador:" in text
    assert "Candidato:" in text
    assert "¿Cuál es tu experiencia?" in text
    assert "Tengo 2 años." in text


# ── _force_complete_summary ───────────────────────────────────────────────────

def test_force_complete_summary_concatenates_all_user_turns():
    turns = [
        {"role": "assistant", "content": "Pregunta inicial"},
        {"role": "user", "content": "Primera parte."},
        {"role": "assistant", "content": "¿Más detalles?"},
    ]
    result = _force_complete_summary(turns, "Segunda parte.")
    assert result["is_complete"] is True
    assert result["intent"] == "answering"
    assert "Primera parte." in result["answer_summary"]
    assert "Segunda parte." in result["answer_summary"]
    # Assistant turn content should NOT appear in summary
    assert "Pregunta inicial" not in result["answer_summary"]
    assert "¿Más detalles?" not in result["answer_summary"]


def test_force_complete_summary_only_current_message():
    result = _force_complete_summary([], "Única respuesta.")
    assert result["is_complete"] is True
    assert result["answer_summary"] == "Única respuesta."


# ── _parse_llm_response ───────────────────────────────────────────────────────

def test_parse_llm_response_complete():
    raw = json.dumps({
        "response": "Gracias.",
        "is_complete": True,
        "answer_summary": "El candidato tiene experiencia con WhatsApp API.",
        "intent": "answering",
    })
    result = _parse_llm_response(raw, "fallback")
    assert result["is_complete"] is True
    assert result["answer_summary"] == "El candidato tiene experiencia con WhatsApp API."
    assert result["intent"] == "answering"


def test_parse_llm_response_incomplete_followup():
    raw = json.dumps({
        "response": "¿Qué casos de uso específicos implementaste?",
        "is_complete": False,
        "answer_summary": None,
        "intent": "answering",
    })
    result = _parse_llm_response(raw, "fallback")
    assert result["is_complete"] is False
    assert result["answer_summary"] is None


def test_parse_llm_response_fallback_on_bad_json():
    result = _parse_llm_response("not json {{{", "Respuesta candidato.")
    assert result["is_complete"] is True
    assert result["answer_summary"] == "Respuesta candidato."
    assert result["intent"] == "answering"


def test_parse_llm_response_normalizes_bad_intent():
    raw = json.dumps({"response": "ok", "is_complete": True, "answer_summary": "x", "intent": "invalid"})
    result = _parse_llm_response(raw, "fallback")
    assert result["intent"] == "answering"


# ── DialogueManager.process_turn ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complete_on_first_answer():
    response_json = json.dumps({
        "response": "Muy bien, gracias por tu respuesta.",
        "is_complete": True,
        "answer_summary": "El candidato implementó WhatsApp Business API en un proyecto médico.",
        "intent": "answering",
    })
    manager, client = make_manager([response_json])

    result = await manager.process_turn(
        dimension=SAMPLE_DIMENSION,
        question_text=SAMPLE_QUESTION,
        turns=[{"role": "assistant", "content": SAMPLE_QUESTION}],
        candidate_message="Implementé WhatsApp API para notificaciones de citas.",
        session_id="sess-1",
        request_id="req-1",
    )

    assert result["is_complete"] is True
    assert result["intent"] == "answering"
    assert len(client.calls) == 1
    assert client.calls[0]["prompt_name"] == "interview_dialogue_conductor"


@pytest.mark.asyncio
async def test_incomplete_triggers_followup():
    response_json = json.dumps({
        "response": "¿Qué casos de uso específicos implementaste con la API?",
        "is_complete": False,
        "answer_summary": None,
        "intent": "answering",
    })
    manager, client = make_manager([response_json])

    result = await manager.process_turn(
        dimension=SAMPLE_DIMENSION,
        question_text=SAMPLE_QUESTION,
        turns=[{"role": "assistant", "content": SAMPLE_QUESTION}],
        candidate_message="He trabajado con APIs de mensajería.",
        session_id="sess-1",
        request_id="req-1",
    )

    assert result["is_complete"] is False
    assert result["answer_summary"] is None
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_asking_clarification_intent():
    response_json = json.dumps({
        "response": "La WhatsApp Business API es la API oficial de Meta para mensajería empresarial. ¿Tienes experiencia con ella?",
        "is_complete": False,
        "answer_summary": None,
        "intent": "asking_clarification",
    })
    manager, client = make_manager([response_json])

    result = await manager.process_turn(
        dimension=SAMPLE_DIMENSION,
        question_text=SAMPLE_QUESTION,
        turns=[{"role": "assistant", "content": SAMPLE_QUESTION}],
        candidate_message="¿Qué es exactamente WhatsApp Business API?",
        session_id="sess-1",
        request_id="req-1",
    )

    assert result["intent"] == "asking_clarification"
    assert result["is_complete"] is False


@pytest.mark.asyncio
async def test_abandoning_intent():
    response_json = json.dumps({
        "response": "Entendido, cerramos la entrevista aquí. ¡Mucha suerte!",
        "is_complete": False,
        "answer_summary": None,
        "intent": "abandoning",
    })
    manager, client = make_manager([response_json])

    result = await manager.process_turn(
        dimension=SAMPLE_DIMENSION,
        question_text=SAMPLE_QUESTION,
        turns=[{"role": "assistant", "content": SAMPLE_QUESTION}],
        candidate_message="Quiero abandonar la entrevista.",
        session_id="sess-1",
        request_id="req-1",
    )

    assert result["intent"] == "abandoning"
    assert result["is_complete"] is False


@pytest.mark.asyncio
async def test_requesting_correction_intent():
    response_json = json.dumps({
        "response": "Claro, reformulamos tu respuesta. " + SAMPLE_QUESTION,
        "is_complete": False,
        "answer_summary": None,
        "intent": "requesting_correction",
    })
    manager, client = make_manager([response_json])

    result = await manager.process_turn(
        dimension=SAMPLE_DIMENSION,
        question_text=SAMPLE_QUESTION,
        turns=[
            {"role": "assistant", "content": SAMPLE_QUESTION},
            {"role": "user", "content": "Respuesta anterior incorrecta."},
            {"role": "assistant", "content": "¿Puedes dar más detalles?"},
        ],
        candidate_message="Quiero corregir mi respuesta.",
        session_id="sess-1",
        request_id="req-1",
    )

    assert result["intent"] == "requesting_correction"
    assert result["is_complete"] is False


@pytest.mark.asyncio
async def test_max_turns_forces_complete_without_llm_call():
    manager, client = make_manager([])  # no responses — LLM must NOT be called

    # Build turns with MAX_TURNS_PER_DIMENSION candidate turns already
    turns = []
    for i in range(MAX_TURNS_PER_DIMENSION):
        turns.append({"role": "user", "content": f"Respuesta {i + 1}"})
        if i < MAX_TURNS_PER_DIMENSION - 1:
            turns.append({"role": "assistant", "content": "¿Más detalles?"})

    result = await manager.process_turn(
        dimension=SAMPLE_DIMENSION,
        question_text=SAMPLE_QUESTION,
        turns=turns,
        candidate_message="Última respuesta.",
        session_id="sess-1",
        request_id="req-1",
    )

    assert result["is_complete"] is True
    assert result["intent"] == "answering"
    assert len(client.calls) == 0, "LLM must not be called when max turns reached"


@pytest.mark.asyncio
async def test_max_turns_summary_includes_all_candidate_messages():
    manager, _ = make_manager([])

    turns = [{"role": "user", "content": f"Parte {i + 1}."} for i in range(MAX_TURNS_PER_DIMENSION)]

    result = await manager.process_turn(
        dimension=SAMPLE_DIMENSION,
        question_text=SAMPLE_QUESTION,
        turns=turns,
        candidate_message="Parte final.",
        session_id="sess-1",
        request_id="req-1",
    )

    summary = result["answer_summary"]
    for i in range(MAX_TURNS_PER_DIMENSION):
        assert f"Parte {i + 1}." in summary
    assert "Parte final." in summary


@pytest.mark.asyncio
async def test_template_vars_sent_to_ai():
    response_json = json.dumps({
        "response": "Ok.",
        "is_complete": True,
        "answer_summary": "Resumen.",
        "intent": "answering",
    })
    manager, client = make_manager([response_json])

    await manager.process_turn(
        dimension=SAMPLE_DIMENSION,
        question_text=SAMPLE_QUESTION,
        turns=[],
        candidate_message="Mi respuesta.",
        session_id="sess-abc",
        request_id="req-abc",
    )

    tvars = client.calls[0]["template_vars"]
    assert tvars["dimension_id"] == "D1"
    assert tvars["dimension_name"] == "Integraciones técnicas"
    assert tvars["rubric_5"] == SAMPLE_DIMENSION.rubricas["5"]
    assert tvars["candidate_message"] == "Mi respuesta."
    assert SAMPLE_QUESTION in tvars["question_text"]
