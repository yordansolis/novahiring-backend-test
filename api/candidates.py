"""Candidate self-registration, CV upload, and admin evaluation endpoints."""
import hashlib
import io
import logging

import pypdf
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from config import get_settings
from contracts import CandidateListItem, CVUploadResponse, DiscoveryJSON, EvaluationTriggerResponse
from database import async_session_factory, get_db, get_redis
from models.base import new_uuid
from models.candidate import Candidate
from models.evaluation import Evaluation
from models.job import JobOpening
from services.ai_client import AIClient
from services.cv_evaluator import CVEvaluator
from services.ko_checker import KOChecker
from services.notification_service import NotificationService
from services.profile import ProfileBuilder
from services.scorer import Scorer

logger = logging.getLogger("nova.candidates")

router = APIRouter()

_ALLOWED_EXTENSIONS = {".pdf", ".md"}
_MIN_CV_TEXT_LENGTH = 50


def _extract_cv_text(filename: str, content: bytes) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == ".pdf":
        reader = pypdf.PdfReader(io.BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif ext == ".md":
        text = content.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    return text


def _make_cv_evaluator(db: AsyncSession) -> CVEvaluator:
    settings = get_settings()
    ai = AIClient(db, settings.ANTHROPIC_API_KEY, settings.OPENAI_API_KEY)
    notifier = NotificationService(db, get_redis())
    return CVEvaluator(db=db, ai_client=ai, scorer=Scorer(), notification_service=notifier)


async def _run_evaluation_batch_task(job_id: str) -> None:
    """Background task — creates its own DB session."""
    async with async_session_factory() as db:
        evaluator = _make_cv_evaluator(db)
        try:
            apto_ids = await evaluator.evaluate_job_candidates(job_id)
            logger.info("Batch evaluation for job %s: %d APTO", job_id, len(apto_ids))
        except Exception:
            logger.exception("Batch evaluation failed for job %s", job_id)


# ── POST /upload ──────────────────────────────────────────────────────────────

@router.post("/upload", status_code=201, response_model=CVUploadResponse)
async def upload_cv(
    background_tasks: BackgroundTasks,
    job_id: str = Form(...),
    nombre: str = Form(...),
    email: str = Form(...),
    cv_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    # Validate file type
    filename = cv_file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={"error": "unsupported_file_type", "message": "Only .pdf and .md files are accepted."},
        )

    # Load job
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"})

    # Reject once the 5-candidate cap is reached
    count_result = await db.execute(
        select(func.count()).select_from(Candidate).where(Candidate.job_id == job_id)
    )
    current_count = count_result.scalar_one()
    if current_count >= 5:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "applications_closed",
                "message": "This position is no longer accepting applications.",
            },
        )

    # Extract CV text
    content = await cv_file.read()
    try:
        cv_text = _extract_cv_text(filename, content)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "unsupported_file_type", "message": str(exc)},
        )

    if len(cv_text.strip()) < _MIN_CV_TEXT_LENGTH:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "cv_unreadable",
                "message": "Could not extract text from the file. Use a text-based PDF or a .md file.",
            },
        )

    # Duplicate guard by SHA256
    cv_sha256 = hashlib.sha256(cv_text.encode()).hexdigest()
    existing = await db.execute(
        select(Candidate).where(
            Candidate.job_id == job_id,
            Candidate.cv_sha256 == cv_sha256,
        )
    )
    dup = existing.scalar_one_or_none()
    if dup:
        raise HTTPException(
            status_code=409,
            detail={"error": "duplicate_cv", "candidate_id": dup.id},
        )

    # KO screening (pure Python, no AI)
    discovery = DiscoveryJSON(**job.discovery_json)
    candidate_id = new_uuid()
    profile = ProfileBuilder().build(candidate_id, job_id, cv_text, discovery)
    passed_ko, _ = KOChecker().apply(profile)

    # Persist candidate
    candidate = Candidate(
        id=candidate_id,
        job_id=job_id,
        nombre=nombre,
        email=email,
        cv_text=cv_text,
        cv_sha256=cv_sha256,
        passed_ko=passed_ko,
        profile_json=profile.model_dump(),
    )
    db.add(candidate)
    await db.commit()

    # current_count was captured before insert; if it was 4, this is the 5th candidate.
    if current_count == 4:
        background_tasks.add_task(_run_evaluation_batch_task, job_id)
        logger.info("5th CV received for job %s — batch evaluation queued", job_id)

    return CVUploadResponse(candidate_id=candidate_id, status="received", passed_ko=passed_ko)


# ── GET /{job_id} — list candidates ──────────────────────────────────────────

@router.get("/{job_id}", response_model=list[CandidateListItem], dependencies=[Depends(require_admin)])
async def list_candidates(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"})

    candidates_result = await db.execute(
        select(Candidate).where(Candidate.job_id == job_id).order_by(Candidate.created_at)
    )
    candidates = candidates_result.scalars().all()

    # Latest evaluation per candidate
    eval_result = await db.execute(
        select(Evaluation).where(Evaluation.job_id == job_id)
    )
    evals_by_candidate: dict[str, Evaluation] = {}
    for ev in eval_result.scalars():
        prev = evals_by_candidate.get(ev.candidate_id)
        if prev is None or ev.created_at > prev.created_at:
            evals_by_candidate[ev.candidate_id] = ev

    items = []
    for c in candidates:
        ev = evals_by_candidate.get(c.id)
        items.append(CandidateListItem(
            candidate_id=c.id,
            nombre=c.nombre,
            email=c.email,
            passed_ko=c.passed_ko,
            resultado=ev.resultado if ev else None,
            weighted_score=str(ev.weighted_score) if ev and ev.weighted_score else None,
        ))
    return items


# ── POST /{job_id}/evaluate — admin manual trigger ────────────────────────────

@router.post("/{job_id}/evaluate", response_model=EvaluationTriggerResponse, dependencies=[Depends(require_admin)])
async def trigger_evaluation(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"})

    # Count candidates without existing evaluation
    evaluated_sub = select(Evaluation.candidate_id).where(Evaluation.job_id == job_id)
    count_result = await db.execute(
        select(func.count()).select_from(Candidate).where(
            Candidate.job_id == job_id,
            Candidate.id.notin_(evaluated_sub),
            Candidate.cv_text.isnot(None),
        )
    )
    queued = count_result.scalar_one()

    evaluator = _make_cv_evaluator(db)
    apto_ids = await evaluator.evaluate_job_candidates(job_id)

    return EvaluationTriggerResponse(
        job_id=job_id,
        queued_candidates=queued,
        status="evaluation_started",
    )
