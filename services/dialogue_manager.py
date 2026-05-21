"""Per-dimension dialogue manager for hybrid interview system."""
import json

from contracts import DialogueTurn, ScorecardDimension
from services.ai_client import AIClient

MAX_TURNS_PER_DIMENSION = 3  # max candidate turns per dimension before forced completion

VALID_INTENTS = frozenset(
    {"answering", "asking_clarification", "requesting_correction", "abandoning"}
)


class DialogueResponseValidator:
    def validate(self, response_text: str) -> bool:
        try:
            data = json.loads(response_text)
            return (
                isinstance(data.get("response"), str)
                and len(data.get("response", "")) > 0
                and isinstance(data.get("is_complete"), bool)
                and data.get("intent") in VALID_INTENTS
            )
        except (json.JSONDecodeError, TypeError):
            return False


class DialogueManager:
    def __init__(self, ai_client: AIClient) -> None:
        self._ai = ai_client
        self._validator = DialogueResponseValidator()

    async def process_turn(
        self,
        dimension: ScorecardDimension,
        question_text: str,
        turns: list[DialogueTurn],
        candidate_message: str,
        session_id: str,
        request_id: str,
    ) -> dict:
        """Process one candidate turn for the current dimension.

        Returns dict with keys: response, is_complete, answer_summary, intent.
        Never raises — falls back to safe defaults on LLM failure.
        """
        candidate_turn_count = sum(1 for t in turns if t["role"] == "user")
        if candidate_turn_count >= MAX_TURNS_PER_DIMENSION:
            return _force_complete_summary(turns, candidate_message)

        history_text = _build_history_text(turns)

        raw = await self._ai.call(
            prompt_name="interview_dialogue_conductor",
            template_vars={
                "dimension_id": dimension.id,
                "dimension_name": dimension.nombre,
                "rubric_5": dimension.rubricas.get("5", ""),
                "rubric_3": dimension.rubricas.get("3", ""),
                "rubric_1": dimension.rubricas.get("1", ""),
                "question_text": question_text,
                "conversation_history": history_text,
                "candidate_message": candidate_message,
            },
            conversation_history=[],
            session_id=session_id,
            request_id=request_id,
            validator=self._validator,
        )

        return _parse_llm_response(raw, candidate_message)


def _build_history_text(turns: list[DialogueTurn]) -> str:
    if not turns:
        return "(No hay turnos previos — esta es la primera respuesta del candidato a esta pregunta.)"
    lines = []
    for t in turns:
        label = "Entrevistador" if t["role"] == "assistant" else "Candidato"
        lines.append(f"{label}: {t['content']}")
    return "\n\n".join(lines)


def _force_complete_summary(
    turns: list[DialogueTurn],
    candidate_message: str,
) -> dict:
    """Called when MAX_TURNS_PER_DIMENSION is reached — no extra LLM call."""
    prior_user = [t["content"] for t in turns if t["role"] == "user"]
    summary = "\n\n".join(prior_user + [candidate_message])
    return {
        "response": "Gracias por tu respuesta. Continuemos con la siguiente área.",
        "is_complete": True,
        "answer_summary": summary,
        "intent": "answering",
    }


def _parse_llm_response(raw: str, fallback_text: str) -> dict:
    """Parse LLM JSON. Returns safe defaults on any parse error."""
    try:
        data = json.loads(raw)
        intent = data.get("intent", "answering")
        if intent not in VALID_INTENTS:
            intent = "answering"
        is_complete = bool(data.get("is_complete", True))
        answer_summary = data.get("answer_summary")
        if answer_summary is not None:
            answer_summary = str(answer_summary)
        response = str(data.get("response") or "Entendido, continuamos.")
        return {
            "response": response,
            "is_complete": is_complete,
            "answer_summary": answer_summary,
            "intent": intent,
        }
    except (json.JSONDecodeError, TypeError, KeyError):
        return {
            "response": "Entendido, continuamos con la siguiente pregunta.",
            "is_complete": True,
            "answer_summary": fallback_text,
            "intent": "answering",
        }
