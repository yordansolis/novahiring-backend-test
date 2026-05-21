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
from services.dialogue_manager import DialogueManager
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


def _empty_v2_state(job_id: str = "", candidate_id: str = "") -> dict:
    return {
        "version": "2",
        "session_type": "interview",
        "job_id": job_id,
        "candidate_id": candidate_id,
        "current_dimension_index": 0,
        "dimension_turns": {
            "D1": [{"role": "assistant", "content": INTERVIEW_QUESTIONS[0]["question_text"]}]
        },
        "locked_answers": {},
        "evaluation_id": None,
    }


def _migrate_v1_to_v2(v1: dict) -> dict:
    """Promote v1 answers → locked_answers; map current_question_index → current_dimension_index."""
    locked = {k: v for k, v in v1.get("answers", {}).items()}
    index = v1.get("current_question_index", 0)
    # Seed dimension_turns for current (in-progress) dimension if not yet locked
    dim_turns: dict = {}
    current_dim_id = INTERVIEW_QUESTIONS[index]["dimension_id"] if index < TOTAL_QUESTIONS else None
    if current_dim_id and current_dim_id not in locked:
        dim_turns[current_dim_id] = [
            {"role": "assistant", "content": INTERVIEW_QUESTIONS[index]["question_text"]}
        ]
    return {
        "version": "2",
        "session_type": "interview",
        "job_id": v1.get("job_id", ""),
        "candidate_id": v1.get("candidate_id", ""),
        "current_dimension_index": index,
        "dimension_turns": dim_turns,
        "locked_answers": locked,
        "evaluation_id": v1.get("evaluation_id"),
    }


def _load_state(session: ChatSession) -> dict:
    if not session.context_summary:
        return _empty_v2_state()
    raw = json.loads(session.context_summary)
    if raw.get("version") == "2":
        return raw
    return _migrate_v1_to_v2(raw)


def _save_state(session: ChatSession, state: dict) -> None:
    session.context_summary = json.dumps(state, ensure_ascii=False)


class InterviewConductor:
    def __init__(
        self,
        db: AsyncSession,
        ai_client: AIClient,
        scorer: Scorer,
        session_manager: SessionManager,
        dialogue_manager: DialogueManager,
    ) -> None:
        self._db = db
        self._ai = ai_client
        self._scorer = scorer
        self._sm = session_manager
        self._dm = dialogue_manager

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

        state = _empty_v2_state(job_id=job_id, candidate_id=candidate_id)

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
            current_dimension_index="0",
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
        index = state["current_dimension_index"]

        # Count existing messages for sequence numbering
        result = await self._db.execute(
            select(func.count()).select_from(Message).where(Message.session_id == session.id)
        )
        msg_count = result.scalar_one()

        # Save user message immediately (before LLM call)
        self._db.add(Message(
            session_id=session.id,
            role="user",
            content=answer_text,
            sequence_number=msg_count + 1,
        ))
        await self._db.flush()

        # Load job rubrics for dialogue manager
        job = await self._db.get(JobOpening, session.job_id)
        if job is None:
            raise ValueError(f"Job {session.job_id} not found")
        discovery = DiscoveryJSON(**job.discovery_json)
        dim_map = {d.id: d for d in discovery.dimensions}

        q_entry = INTERVIEW_QUESTIONS[index]
        dim_id = q_entry["dimension_id"]
        dimension = dim_map[dim_id]

        # Prior turns for this dimension (before this candidate message)
        prior_turns = list(state["dimension_turns"].get(dim_id, []))

        # LLM-driven dialogue turn
        dialogue_result = await self._dm.process_turn(
            dimension=dimension,
            question_text=q_entry["question_text"],
            turns=prior_turns,
            candidate_message=answer_text,
            session_id=session.id,
            request_id=request_id,
        )

        intent = dialogue_result["intent"]

        # ── Abandonment ───────────────────────────────────────────────────────
        if intent == "abandoning":
            return await self._handle_abandonment(
                session, dialogue_result["response"], msg_count
            )

        # ── Correction (restart current dimension) ────────────────────────────
        if intent == "requesting_correction":
            return await self._handle_correction(
                session, state, dim_id, index, dialogue_result["response"], msg_count
            )

        # ── Normal flow (answering / asking_clarification) ────────────────────

        # Update dimension turns
        turns = state["dimension_turns"].setdefault(dim_id, [])
        turns.append({"role": "user", "content": answer_text})

        # Save LLM response
        self._db.add(Message(
            session_id=session.id,
            role="assistant",
            content=dialogue_result["response"],
            sequence_number=msg_count + 2,
        ))
        turns.append({"role": "assistant", "content": dialogue_result["response"]})

        if dialogue_result["is_complete"]:
            state["locked_answers"][dim_id] = dialogue_result["answer_summary"] or answer_text
            next_index = index + 1
            state["current_dimension_index"] = next_index

            if next_index < TOTAL_QUESTIONS:
                next_q_text = _question_text(next_index)
                next_dim_id = INTERVIEW_QUESTIONS[next_index]["dimension_id"]
                self._db.add(Message(
                    session_id=session.id,
                    role="assistant",
                    content=next_q_text,
                    sequence_number=msg_count + 3,
                ))
                state["dimension_turns"][next_dim_id] = [
                    {"role": "assistant", "content": INTERVIEW_QUESTIONS[next_index]["question_text"]}
                ]
                _save_state(session, state)
                await self._db.commit()
                await self._sm.set_session_meta(
                    session.id,
                    status="active",
                    current_dimension_index=str(next_index),
                )
                return _make_question_info(next_index), None

            # All 8 dimensions locked — run evaluation
            _save_state(session, state)
            await self._db.flush()

            eval_result = await self._run_evaluation_pipeline(
                session=session,
                answers=state["locked_answers"],
                request_id=request_id,
            )

            state["evaluation_id"] = eval_result.evaluation_id
            _save_state(session, state)
            session.status = "completed"
            await self._db.commit()
            await self._sm.set_session_meta(
                session.id,
                status="completed",
                current_dimension_index=str(next_index),
            )
            return None, eval_result

        # Not complete — follow-up in progress for same dimension
        _save_state(session, state)
        await self._db.commit()
        await self._sm.set_session_meta(
            session.id,
            status="active",
            current_dimension_index=str(index),
        )
        return _make_question_info(index), None

    # ── Special intent handlers ───────────────────────────────────────────────

    async def _handle_abandonment(
        self,
        session: ChatSession,
        farewell_response: str,
        msg_count: int,
    ) -> tuple[None, None]:
        # User message was already saved before the LLM call
        self._db.add(Message(
            session_id=session.id,
            role="assistant",
            content=farewell_response,
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
        dim_id: str,
        index: int,
        correction_response: str,
        msg_count: int,
    ) -> tuple[QuestionInfo, None]:
        # User message was already saved before the LLM call
        self._db.add(Message(
            session_id=session.id,
            role="assistant",
            content=correction_response,
            sequence_number=msg_count + 2,
        ))
        # Reset current dimension: clear turns, un-lock answer if it was locked
        state["dimension_turns"][dim_id] = [
            {"role": "assistant", "content": correction_response}
        ]
        state["locked_answers"].pop(dim_id, None)
        _save_state(session, state)
        await self._db.commit()
        await self._sm.set_session_meta(
            session.id,
            status="active",
            current_dimension_index=str(index),
        )
        return _make_question_info(index), None

    # ── Evaluation pipeline ───────────────────────────────────────────────────

    async def _run_evaluation_pipeline(
        self,
        session: ChatSession,
        answers: dict[str, str],
        request_id: str,
    ) -> InterviewEvaluationResult:
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

        dimension_scores: list[DimensionScore] = []
        interview_scores: list[InterviewDimensionScore] = []

        for q in INTERVIEW_QUESTIONS:
            dim_id = q["dimension_id"]
            dim_name = q["dimension_name"]
            answer = answers.get(dim_id, "")
            rubrics = rubric_map.get(dim_id, {})
            peso = peso_map.get(dim_id, 1)

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
