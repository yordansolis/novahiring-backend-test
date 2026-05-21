"""Interview session endpoints."""
import json
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_interview_access
from config import get_settings
from contracts import (
    CandidateTokenClaims,
    InterruptResponse,
    MessageOut,
    MessageResponse,
    SendMessageRequest,
    SessionDetailResponse,
    SessionStarted,
    StartSessionRequest,
)
from database import get_db, get_redis
from models.candidate import Candidate
from models.evaluation import Evaluation
from models.ops import ChatSession, Message
from services.ai_client import AIClient
from services.dialogue_manager import DialogueManager
from services.interview_conductor import InterviewConductor
from services.scorer import Scorer
from services.session_manager import SessionManager

router = APIRouter()


def _get_conductor(db: AsyncSession = Depends(get_db)) -> InterviewConductor:
    settings = get_settings()
    ai_client = AIClient(db, settings.ANTHROPIC_API_KEY, settings.OPENAI_API_KEY)
    scorer = Scorer()
    session_manager = SessionManager(get_redis(), settings)
    dialogue_manager = DialogueManager(ai_client)
    return InterviewConductor(db, ai_client, scorer, session_manager, dialogue_manager)


def _get_session_manager() -> SessionManager:
    return SessionManager(get_redis(), get_settings())


# ── POST /sessions ────────────────────────────────────────────────────────────

@router.post("/sessions", status_code=201, response_model=SessionStarted)
async def start_session(
    claims: CandidateTokenClaims | None = Depends(require_interview_access),
    body: StartSessionRequest | None = Body(default=None),
    conductor: InterviewConductor = Depends(_get_conductor),
    db: AsyncSession = Depends(get_db),
):
    # Resolve candidate_id and job_id from Bearer token claims or request body
    candidate_id = (claims.candidate_id if claims else None) or (body and body.candidate_id)
    job_id = (claims.job_id if claims else None) or (body and body.job_id)
    if not candidate_id or not job_id:
        raise HTTPException(
            status_code=422,
            detail={"error": "missing_fields", "message": "job_id and candidate_id are required."},
        )

    # Gate 1: candidate must have passed_ko=True
    candidate = await db.get(Candidate, candidate_id)
    if not candidate or not candidate.passed_ko:
        raise HTTPException(
            status_code=422,
            detail={"error": "candidate_not_eligible", "message": "Candidate did not pass KO screening."},
        )

    # Gate 2: no active/processing session already exists for this candidate+job
    existing = await db.execute(
        select(ChatSession).where(
            ChatSession.candidate_id == candidate_id,
            ChatSession.job_id == job_id,
            ChatSession.session_type == "interview",
            ChatSession.status.notin_(["completed", "expired", "abandoned"]),
        )
    )
    dupe = existing.scalar_one_or_none()
    if dupe:
        raise HTTPException(
            status_code=409,
            detail={"error": "session_already_exists", "session_id": dupe.id},
        )

    return await conductor.create_session(job_id, candidate_id)


# ── POST /sessions/{session_id}/message ──────────────────────────────────────

@router.post("/sessions/{session_id}/message", response_model=MessageResponse, dependencies=[Depends(require_interview_access)])
async def send_message(
    session_id: str,
    body: SendMessageRequest,
    request: Request,
    conductor: InterviewConductor = Depends(_get_conductor),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    if session.status in ("completed", "expired", "abandoned"):
        raise HTTPException(status_code=410, detail={"error": "session_closed", "status": session.status})

    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    sm = _get_session_manager()

    acquired = await sm.acquire_processing_lock(session_id, request_id)
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail={"error": "session_busy", "message": "Session is currently processing. Try again shortly."},
        )

    try:
        next_question, eval_result = await conductor.handle_answer(session, body.content, request_id)
    except InterruptedError:
        return MessageResponse(
            message_saved=True,
            next_question=None,
            session_status="active",
            evaluation_result=None,
        )
    finally:
        await sm.release_processing_lock(session_id, request_id)

    return MessageResponse(
        message_saved=True,
        next_question=next_question,
        session_status=session.status,
        evaluation_result=eval_result,
    )


# ── GET /sessions/{session_id} ────────────────────────────────────────────────

@router.get("/sessions/{session_id}", response_model=SessionDetailResponse, dependencies=[Depends(require_interview_access)])
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})

    state = json.loads(session.context_summary) if session.context_summary else {}
    if state.get("version") == "2":
        current_q_index = state.get("current_dimension_index", 0)
    else:
        current_q_index = state.get("current_question_index", 0)

    msgs_result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.sequence_number)
    )
    messages = [
        MessageOut(role=m.role, content=m.content, sequence_number=m.sequence_number)
        for m in msgs_result.scalars()
    ]

    return SessionDetailResponse(
        session_id=session.id,
        job_id=session.job_id,
        candidate_id=session.candidate_id,
        status=session.status,
        current_question_index=current_q_index,
        total_questions=8,
        messages=messages,
    )


# ── POST /sessions/{session_id}/interrupt ─────────────────────────────────────

@router.post("/sessions/{session_id}/interrupt", response_model=InterruptResponse, dependencies=[Depends(require_interview_access)])
async def interrupt_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})

    sm = _get_session_manager()
    await sm.set_interrupted(session_id)

    return InterruptResponse(status="interrupted", session_id=session_id)
