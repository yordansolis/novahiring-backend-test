"""Interview state machine: question flow, AI evaluation, DB writes."""
import json
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from contracts import (
    DiscoveryJSON,
    DimensionScore,
    InterviewDimensionScore,
    InterviewEvaluationResult,
    MessageOut,
    QuestionInfo,
    SessionStarted,
)
from models.candidate import Candidate
from models.evaluation import DimensionScoreRecord, Evaluation
from models.job import JobOpening
from models.ops import ChatSession, Message
from services.ai_client import AIClient, ScoreRangeValidator
from services.scorer import Scorer
from services.session_manager import SessionManager

INTERVIEW_QUESTIONS: list[dict] = [
    {
        "dimension_id": "D1",
        "dimension_name": "Integraciones técnicas obligatorias",
        "question_text": (
            "Describe tu experiencia integrando WhatsApp Business API (Meta). "
            "¿Qué casos de uso implementaste y qué dificultades encontraste?"
        ),
    },
    {
        "dimension_id": "D2",
        "dimension_name": "Cumplimiento RGPD/LOPDGDD datos sanitarios",
        "question_text": (
            "¿Cómo has manejado la protección de datos sanitarios en proyectos anteriores? "
            "Menciona medidas técnicas concretas (cifrado, consentimiento, RAT) "
            "y si has trabajado con validación legal."
        ),
    },
    {
        "dimension_id": "D3",
        "dimension_name": "Autonomía y toma de decisiones técnicas",
        "question_text": (
            "Describe un proyecto donde tomaste decisiones de arquitectura en solitario, "
            "sin supervisión técnica externa. ¿Cuáles fueron las más importantes "
            "y cómo las justificaste ante el cliente?"
        ),
    },
    {
        "dimension_id": "D4",
        "dimension_name": "Pragmatismo — criterio construir vs usar",
        "question_text": (
            "¿Cómo decides qué construir desde cero vs usar una solución de terceros? "
            "Dame un ejemplo concreto en un proyecto reciente."
        ),
    },
    {
        "dimension_id": "D5",
        "dimension_name": "Entrega en plazos ajustados",
        "question_text": (
            "¿Has entregado un sistema funcional en producción en 3 meses o menos? "
            "Describe el proyecto, el plazo real y qué priorizaste para lograrlo."
        ),
    },
    {
        "dimension_id": "D6",
        "dimension_name": "Comunicación con no técnicos",
        "question_text": (
            "¿Cómo comunicas el avance técnico a clientes o directivos sin perfil tecnológico? "
            "Describe un ejemplo concreto de cómo adaptaste tu comunicación."
        ),
    },
    {
        "dimension_id": "D7",
        "dimension_name": "Experiencia en sector salud",
        "question_text": (
            "¿Tienes experiencia trabajando en proyectos del sector salud, clínicas "
            "o gestión de citas? Describe el proyecto y qué aprendiste del contexto."
        ),
    },
    {
        "dimension_id": "D8",
        "dimension_name": "Stack e infraestructura adecuada al presupuesto",
        "question_text": (
            "¿Qué stack tecnológico usarías para este proyecto (panel de recepción, "
            "reservas online, WhatsApp, Google Calendar) con un presupuesto de "
            "8.000–12.000€ y plazo de 3 meses? Justifica brevemente cada elección."
        ),
    },
]

TOTAL_QUESTIONS = len(INTERVIEW_QUESTIONS)

# Phrases that clearly signal intent to correct the previous answer
_CORRECTION_PHRASES = (
    "quiero corregir",
    "quiero modificar mi respuesta",
    "me equivoqué",
    "cometí un error en la respuesta",
    "quiero cambiar mi respuesta",
    "volver a la pregunta anterior",
    "rectificar mi respuesta",
    "la respuesta anterior no era correcta",
    "cambiar lo que dije antes",
    "eso no era lo que quería decir",
)

# Phrases that clearly signal intent to abandon the interview
_ABANDONMENT_PHRASES = (
    "no quiero continuar",
    "quiero abandonar",
    "quiero terminar la entrevista",
    "no me interesa continuar",
    "cerrar la entrevista",
    "cancelar la entrevista",
    "me retiro de la entrevista",
    "salir de la entrevista",
)


def _detect_correction(text: str) -> bool:
    t = text.lower()
    return any(phrase in t for phrase in _CORRECTION_PHRASES)


def _detect_abandonment(text: str) -> bool:
    t = text.lower()
    return any(phrase in t for phrase in _ABANDONMENT_PHRASES)

_WELCOME_TEMPLATE = """\
Hola, bienvenido/a al proceso de entrevista para la posición de **Desarrollador Full-Stack** en **Clínica Salud Valencia S.L.** (Valencia, España).

El proyecto consiste en construir desde cero un sistema de gestión de citas médicas con panel de recepción centralizado, reserva online para pacientes y notificaciones automáticas por WhatsApp. El plazo es de 3 meses y el presupuesto es de 8.000–12.000 €.

La entrevista consta de {total} preguntas, una por cada área de evaluación. Responde con detalle y con ejemplos concretos de tu experiencia real.

**Pregunta 1 de {total} — {dimension_name}:**
{question_text}"""


def _make_question_info(index: int) -> QuestionInfo:
    q = INTERVIEW_QUESTIONS[index]
    return QuestionInfo(
        dimension_id=q["dimension_id"],
        dimension_name=q["dimension_name"],
        question_text=q["question_text"],
        question_number=index + 1,
        total_questions=TOTAL_QUESTIONS,
    )


def _question_text(index: int) -> str:
    q = INTERVIEW_QUESTIONS[index]
    return (
        f"**Pregunta {index + 1} de {TOTAL_QUESTIONS} — {q['dimension_name']}:**\n"
        f"{q['question_text']}"
    )


def _load_state(session: ChatSession) -> dict:
    if session.context_summary:
        return json.loads(session.context_summary)
    return {"current_question_index": 0, "answers": {}, "evaluation_id": None}


def _save_state(session: ChatSession, state: dict) -> None:
    session.context_summary = json.dumps(state, ensure_ascii=False)


class InterviewConductor:
    def __init__(
        self,
        db: AsyncSession,
        ai_client: AIClient,
        scorer: Scorer,
        session_manager: SessionManager,
    ) -> None:
        self._db = db
        self._ai = ai_client
        self._scorer = scorer
        self._sm = session_manager

    # ── Public interface ──────────────────────────────────────────────────────

    async def create_session(
        self,
        job_id: str,
        candidate_id: str,
    ) -> SessionStarted:
        welcome_text = _WELCOME_TEMPLATE.format(
            total=TOTAL_QUESTIONS,
            dimension_name=INTERVIEW_QUESTIONS[0]["dimension_name"],
            question_text=INTERVIEW_QUESTIONS[0]["question_text"],
        )

        state = {
            "version": "1",
            "session_type": "interview",
            "job_id": job_id,
            "candidate_id": candidate_id,
            "current_question_index": 0,
            "answers": {},
            "evaluation_id": None,
        }

        chat_session = ChatSession(
            job_id=job_id,
            candidate_id=candidate_id,
            session_type="interview",
            status="active",
            context_summary=json.dumps(state, ensure_ascii=False),
        )
        self._db.add(chat_session)
        await self._db.flush()

        welcome_msg = Message(
            session_id=chat_session.id,
            role="assistant",
            content=welcome_text,
            sequence_number=1,
        )
        self._db.add(welcome_msg)
        await self._db.commit()

        await self._sm.set_session_meta(
            chat_session.id,
            status="active",
            current_question_index="0",
        )

        return SessionStarted(
            session_id=chat_session.id,
            status="active",
            message=MessageOut(
                role="assistant",
                content=welcome_text,
                sequence_number=1,
            ),
            next_question=_make_question_info(0),
        )

    async def handle_answer(
        self,
        session: ChatSession,
        answer_text: str,
        request_id: str,
    ) -> tuple[QuestionInfo | None, InterviewEvaluationResult | None]:
        state = _load_state(session)
        index = state["current_question_index"]

        # Count existing messages to set correct sequence_number
        result = await self._db.execute(
            select(func.count()).select_from(Message).where(Message.session_id == session.id)
        )
        msg_count = result.scalar_one()

        # ── Special intents ────────────────────────────────────────────────
        if _detect_abandonment(answer_text):
            return await self._handle_abandonment(session, answer_text, msg_count)

        if index > 0 and _detect_correction(answer_text):
            return await self._handle_correction(session, state, answer_text, msg_count)

        # ── Normal answer ─────────────────────────────────────────────────
        dim_id = INTERVIEW_QUESTIONS[index]["dimension_id"]
        state["answers"][dim_id] = answer_text

        user_msg = Message(
            session_id=session.id,
            role="user",
            content=answer_text,
            sequence_number=msg_count + 1,
        )
        self._db.add(user_msg)
        await self._db.flush()

        next_index = index + 1
        state["current_question_index"] = next_index

        if next_index < TOTAL_QUESTIONS:
            # Save next question as assistant message
            q_text = _question_text(next_index)
            asst_msg = Message(
                session_id=session.id,
                role="assistant",
                content=q_text,
                sequence_number=msg_count + 2,
            )
            self._db.add(asst_msg)
            _save_state(session, state)
            await self._db.commit()

            await self._sm.set_session_meta(
                session.id,
                status="active",
                current_question_index=str(next_index),
            )

            return _make_question_info(next_index), None

        # All answers collected — run evaluation pipeline
        _save_state(session, state)
        await self._db.flush()

        eval_result = await self._run_evaluation_pipeline(
            session=session,
            answers=state["answers"],
            request_id=request_id,
        )

        state["evaluation_id"] = eval_result.evaluation_id
        _save_state(session, state)
        session.status = "completed"
        await self._db.commit()

        await self._sm.set_session_meta(
            session.id,
            status="completed",
            current_question_index=str(next_index),
        )

        return None, eval_result

    # ── Special intent handlers ───────────────────────────────────────────────

    async def _handle_abandonment(
        self,
        session: ChatSession,
        answer_text: str,
        msg_count: int,
    ) -> tuple[None, None]:
        self._db.add(Message(
            session_id=session.id,
            role="user",
            content=answer_text,
            sequence_number=msg_count + 1,
        ))
        farewell = (
            "Entendido, cerramos aquí la entrevista. "
            "Si cambias de opinión o tienes cualquier pregunta, no dudes en contactarnos. "
            "¡Mucha suerte en tu búsqueda!"
        )
        self._db.add(Message(
            session_id=session.id,
            role="assistant",
            content=farewell,
            sequence_number=msg_count + 2,
        ))
        session.status = "abandoned"
        await self._db.commit()
        await self._sm.set_session_meta(session.id, status="abandoned")
        return None, None

    async def _handle_correction(
        self,
        session: ChatSession,
        state: dict,
        answer_text: str,
        msg_count: int,
    ) -> tuple[QuestionInfo, None]:
        corrected_index = state["current_question_index"] - 1
        corrected_q = INTERVIEW_QUESTIONS[corrected_index]

        self._db.add(Message(
            session_id=session.id,
            role="user",
            content=answer_text,
            sequence_number=msg_count + 1,
        ))
        note = (
            f"Claro, vamos a corregir tu respuesta anterior.\n\n"
            f"**Pregunta {corrected_index + 1} de {TOTAL_QUESTIONS} "
            f"— {corrected_q['dimension_name']}:**\n"
            f"{corrected_q['question_text']}"
        )
        self._db.add(Message(
            session_id=session.id,
            role="assistant",
            content=note,
            sequence_number=msg_count + 2,
        ))

        # Remove the stale answer and go back one question
        state["answers"].pop(corrected_q["dimension_id"], None)
        state["current_question_index"] = corrected_index
        _save_state(session, state)
        await self._db.commit()

        await self._sm.set_session_meta(
            session.id,
            status="active",
            current_question_index=str(corrected_index),
        )
        return _make_question_info(corrected_index), None

    # ── Evaluation pipeline ───────────────────────────────────────────────────

    async def _run_evaluation_pipeline(
        self,
        session: ChatSession,
        answers: dict[str, str],
        request_id: str,
    ) -> InterviewEvaluationResult:
        # Load job and discovery JSON
        job = await self._db.get(JobOpening, session.job_id)
        if job is None:
            raise ValueError(f"Job {session.job_id} not found")
        discovery = DiscoveryJSON(**job.discovery_json)
        rubric_map = {d.id: d.rubricas for d in discovery.dimensions}
        peso_map = {d.id: d.peso for d in discovery.dimensions}

        # Load existing KO results from the CV evaluation
        ko_result = await self._db.execute(
            select(Evaluation).where(
                Evaluation.candidate_id == session.candidate_id,
                Evaluation.job_id == session.job_id,
                Evaluation.passed_ko.is_(True),
            )
        )
        existing_eval = ko_result.scalar_one_or_none()
        ko_results_raw = existing_eval.ko_results if existing_eval else []

        # Score each dimension via AI
        dimension_scores: list[DimensionScore] = []
        interview_scores: list[InterviewDimensionScore] = []

        for q in INTERVIEW_QUESTIONS:
            dim_id = q["dimension_id"]
            dim_name = q["dimension_name"]
            answer = answers.get(dim_id, "")
            rubrics = rubric_map.get(dim_id, {})
            peso = peso_map.get(dim_id, 1)

            # Check interrupt between AI calls
            if await self._sm.check_and_clear_interrupted(session.id):
                raise InterruptedError("Session interrupted by user")

            raw = await self._ai.call(
                prompt_name="interview_response_evaluator",
                template_vars={
                    "dimension_id": dim_id,
                    "dimension_name": dim_name,
                    "rubric_5": rubrics.get("5", ""),
                    "rubric_3": rubrics.get("3", ""),
                    "rubric_1": rubrics.get("1", ""),
                    "candidate_answer": answer,
                },
                conversation_history=[],
                session_id=session.id,
                request_id=request_id,
                validator=ScoreRangeValidator(),
            )

            parsed = json.loads(raw)
            score_val = Decimal(str(parsed["score"]))
            justificacion = parsed.get("justificacion", "")
            evidencia = parsed.get("evidencia", "")

            dimension_scores.append(DimensionScore(
                dimension_id=dim_id,
                peso=peso,
                score=score_val,
                justificacion=justificacion,
                evidencia=evidencia,
            ))
            interview_scores.append(InterviewDimensionScore(
                dimension_id=dim_id,
                score=str(score_val),
                peso=peso,
                justificacion=justificacion,
                evidencia=evidencia,
            ))

        weighted_score, normalized_score = self._scorer.calculate(dimension_scores, discovery)

        # Write new evaluation row
        eval_id = str(uuid.uuid4())
        new_eval = Evaluation(
            id=eval_id,
            job_id=session.job_id,
            candidate_id=session.candidate_id,
            passed_ko=True,
            first_failing_ko=None,
            weighted_score=weighted_score,
            normalized_score=normalized_score,
            resultado="APTO",
            ko_results=ko_results_raw,
        )
        self._db.add(new_eval)
        await self._db.flush()

        for ds in dimension_scores:
            self._db.add(DimensionScoreRecord(
                evaluation_id=eval_id,
                candidate_id=session.candidate_id,
                job_id=session.job_id,
                dimension_id=ds.dimension_id,
                raw_score=ds.score,
                peso=ds.peso,
                justificacion=ds.justificacion,
                evidencia=ds.evidencia,
            ))
        await self._db.flush()

        return InterviewEvaluationResult(
            session_id=session.id,
            evaluation_id=eval_id,
            weighted_score=str(weighted_score),
            normalized_score=str(normalized_score),
            resultado="APTO",
            dimension_scores=interview_scores,
        )
