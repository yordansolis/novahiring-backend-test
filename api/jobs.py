import json
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from contracts import (
    CloseJobResponse,
    CreateJobRequest,
    DiscoveryJSON,
    JobAuditCandidate,
    JobAuditResponse,
    JobListItem,
    JobMetricsCandidate,
    JobMetricsFunnelStep,
    JobMetricsResponse,
    RecruiterClaims,
)
from config import get_settings
from database import get_db
from models.candidate import Candidate
from models.evaluation import Evaluation
from models.job import JobOpening
from models.ops import CandidateInvitation, ChatSession
from services.report_writer import ReportWriter

_INTERVIEW_WINDOW = timedelta(days=7)

router = APIRouter()

_GENERIC_RUBRICS = {
    "5": "Evidencia sólida y reciente, por encima de lo que pide el puesto",
    "4": "Cumple el requisito con ejemplos concretos",
    "3": "Cumple de forma parcial o con evidencia limitada",
    "2": "Menciona el tema sin demostrar experiencia aplicable",
    "1": "Sin evidencia relevante",
}

_STARTER_DIMENSIONS = [
    {"id": "D1", "nombre": "Experiencia en el rol", "peso": 3, "rubricas": _GENERIC_RUBRICS},
    {"id": "D2", "nombre": "Competencias técnicas", "peso": 3, "rubricas": _GENERIC_RUBRICS},
    {"id": "D3", "nombre": "Autonomía", "peso": 3, "rubricas": _GENERIC_RUBRICS},
    {"id": "D4", "nombre": "Comunicación", "peso": 2, "rubricas": _GENERIC_RUBRICS},
    {"id": "D5", "nombre": "Entrega y plazos", "peso": 2, "rubricas": _GENERIC_RUBRICS},
    {"id": "D6", "nombre": "Adaptación al sector", "peso": 2, "rubricas": _GENERIC_RUBRICS},
    {"id": "D7", "nombre": "Trabajo en equipo", "peso": 2, "rubricas": _GENERIC_RUBRICS},
    {"id": "D8", "nombre": "Criterio profesional", "peso": 2, "rubricas": _GENERIC_RUBRICS},
]


def _slug(value: str, *, sep: str, max_len: int) -> str:
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", sep, folded.lower()).strip(sep)
    return slug[:max_len] or "vacante"


def _starter_discovery(title: str, niche: str) -> dict:
    return {
        "cliente": {
            "nombre": "",
            "sector": niche,
        },
        "problema_negocio": {
            "descripcion": f"Cubrir la vacante {title}.",
        },
        "producto_a_construir": {
            "descripcion": title,
        },
        "contexto_equipo": {},
        "restricciones": {},
        "perfil_candidato": {
            "habilidades_tecnicas": {
                "obligatorias": [],
                "deseables": [],
            },
            "criterios_de_descarte": [],
        },
        "scorecard": {
            "descripcion": f"Scorecard inicial para {title}",
            "peso_total": sum(d["peso"] for d in _STARTER_DIMENSIONS),
            "dimensiones": _STARTER_DIMENSIONS,
        },
        "criterios_de_exito": [],
    }


@router.get("")
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(JobOpening).order_by(JobOpening.created_at.desc()))
    jobs = result.scalars().all()
    count_rows = await db.execute(
        select(Candidate.job_id, func.count()).group_by(Candidate.job_id)
    )
    counts = {row[0]: int(row[1]) for row in count_rows.all()}
    max_candidates = get_settings().MAX_CANDIDATES_PER_JOB
    items = [
        {
            "job_id": job.id,
            "title": job.title,
            "niche": job.niche,
            "status": job.status,
            "tenant_id": job.tenant_id,
            "candidate_count": counts.get(job.id, 0),
            "max_candidates": max_candidates,
        }
        for job in jobs
    ]
    return {"jobs": items, "total": len(items)}


@router.post("", status_code=201, response_model=JobListItem)
async def create_job(
    body: CreateJobRequest,
    db: AsyncSession = Depends(get_db),
    claims: RecruiterClaims | None = Depends(require_admin),
) -> JobListItem:
    title = body.title.strip()
    niche = _slug(body.niche, sep="_", max_len=100)
    tenant_id = (
        (body.tenant_id.strip() if body.tenant_id else None)
        or (claims.tenant_id if claims else None)
        or "clinica-salud-valencia"
    )
    offer_text = (body.offer_text or "").strip() or f"# {title}\n\nVacante en {niche}."
    # job_openings.id is VARCHAR(36): "job-" + slug + "-" + 6 hex ≤ 36
    job_id = f"job-{_slug(title, sep='-', max_len=25)}-{uuid.uuid4().hex[:6]}"

    job = JobOpening(
        id=job_id,
        tenant_id=tenant_id,
        niche=niche,
        title=title,
        offer_text=offer_text,
        discovery_json=_starter_discovery(title, niche),
        status="active",
    )
    db.add(job)
    await db.commit()
    return JobListItem(
        job_id=job.id,
        title=job.title,
        niche=job.niche,
        status=job.status,
        tenant_id=job.tenant_id,
        candidate_count=0,
        max_candidates=get_settings().MAX_CANDIDATES_PER_JOB,
    )


@router.get("/{job_id}/offer")
async def get_job_offer(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "title": job.title, "offer_text": job.offer_text}


@router.get("/{job_id}/profile")
async def get_candidate_profile(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    discovery = DiscoveryJSON(**job.discovery_json)
    return {
        "required_skills": discovery.perfil_candidato["habilidades_tecnicas"]["obligatorias"],
        "ko_criteria": [k.model_dump() for k in discovery.ko_criteria],
        "scorecard": [d.model_dump() for d in discovery.dimensions],
        "total_weight": discovery.total_weight,
    }


@router.get("/{job_id}/ranking")
async def get_ranking(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Evaluation)
        .where(Evaluation.job_id == job_id)
        .order_by(Evaluation.passed_ko.desc(), Evaluation.weighted_score.desc())
    )
    evaluations = result.scalars().all()
    return {"candidates": [e.to_summary() for e in evaluations]}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime | None) -> str | None:
    dt = _as_utc(value)
    return dt.isoformat() if dt else None


def _latest_by_candidate(rows: list, candidate_attr: str = "candidate_id") -> dict:
    latest: dict = {}
    for row in rows:
        cid = getattr(row, candidate_attr)
        if not cid:
            continue
        prev = latest.get(cid)
        if prev is None or getattr(row, "created_at") > getattr(prev, "created_at"):
            latest[cid] = row
    return latest


def _score_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _session_progress(session: ChatSession | None) -> tuple[int, list[str], str | None]:
    if session is None or not session.context_summary:
        return 0, [], None
    try:
        state = json.loads(session.context_summary)
    except json.JSONDecodeError:
        return 0, [], None
    locked = list((state.get("locked_answers") or {}).keys())
    index = int(state.get("current_dimension_index") or 0)
    current = f"D{index + 1}" if session.status == "active" and 0 <= index < 8 else None
    return len(locked), locked, current


async def _audit_payload(job: JobOpening, db: AsyncSession) -> JobAuditResponse:
    candidates = (
        await db.execute(select(Candidate).where(Candidate.job_id == job.id).order_by(Candidate.created_at))
    ).scalars().all()
    sessions = _latest_by_candidate(
        list((await db.execute(select(ChatSession).where(ChatSession.job_id == job.id))).scalars())
    )
    invitations = _latest_by_candidate(
        list((await db.execute(select(CandidateInvitation).where(CandidateInvitation.job_id == job.id))).scalars())
    )
    evaluations = _latest_by_candidate(
        list((await db.execute(select(Evaluation).where(Evaluation.job_id == job.id))).scalars())
    )

    created = _as_utc(job.created_at) or datetime.now(timezone.utc)
    deadline = created + _INTERVIEW_WINDOW
    now = datetime.now(timezone.utc)
    deadline_passed = now >= deadline
    status = job.status if job.status in {"active", "closed"} else "active"
    closed = status == "closed"

    completed_rows: list[tuple[Candidate, Evaluation | None]] = []
    items: list[JobAuditCandidate] = []
    for candidate in candidates:
        session = sessions.get(candidate.id)
        ev = evaluations.get(candidate.id)
        invitation = invitations.get(candidate.id)
        passed_ko = bool(candidate.passed_ko)
        interview_status = session.status if session else "pending"
        if interview_status not in {"pending", "active", "completed", "abandoned", "expired"}:
            interview_status = "pending"
        completed = interview_status == "completed"
        interview_score = _score_str(ev.weighted_score) if completed and ev else None
        notifications: list[str] = []
        email_status = invitation.email_status if invitation is not None else None
        if email_status == "sent":
            notifications.append("interview_invitation")
        items.append(
            JobAuditCandidate(
                candidate_id=candidate.id,
                nombre=candidate.nombre,
                email=candidate.email,
                passed_ko=passed_ko,
                interview_status=interview_status,
                interview_score=interview_score,
                rank=None,
                account_activated=session is not None,
                invitation_sent=invitation is not None,
                invitation_email_status=email_status,
                notifications_sent=notifications,
                is_winner=False,
                session_id=session.id if session else None,
            )
        )
        if completed and passed_ko:
            completed_rows.append((candidate, ev))

    completed_rows.sort(
        key=lambda pair: pair[1].weighted_score if pair[1] and pair[1].weighted_score is not None else Decimal("0"),
        reverse=True,
    )
    rank_by_id = {cand.id: i for i, (cand, _) in enumerate(completed_rows, start=1)}
    winner = completed_rows[0][0] if closed and completed_rows else None

    for item in items:
        item.rank = rank_by_id.get(item.candidate_id)
        if winner is not None and item.candidate_id == winner.id:
            item.is_winner = True
            if "winner" not in item.notifications_sent:
                item.notifications_sent.append("winner")
        elif closed and item.passed_ko and item.candidate_id != (winner.id if winner else None):
            if "rejection" not in item.notifications_sent:
                item.notifications_sent.append("rejection")

    total_apto = sum(1 for item in items if item.passed_ko)
    total_completed = sum(1 for item in items if item.interview_status == "completed")
    ready = closed or deadline_passed or (total_apto > 0 and total_completed == total_apto)

    return JobAuditResponse(
        job_id=job.id,
        title=job.title,
        status=status,
        interview_deadline=_iso(deadline),
        deadline_passed=deadline_passed,
        closed_at=_iso(job.updated_at) if closed else None,
        winner_candidate_id=winner.id if winner else None,
        winner_nombre=winner.nombre if winner else None,
        ready_to_close=ready,
        total_apto=total_apto,
        total_completed_interviews=total_completed,
        all_candidates=items,
    )


@router.get("/{job_id}/audit", response_model=JobAuditResponse)
async def get_job_audit(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return await _audit_payload(job, db)


@router.get("/{job_id}/metrics", response_model=JobMetricsResponse)
async def get_job_metrics(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    candidates = (
        await db.execute(select(Candidate).where(Candidate.job_id == job_id))
    ).scalars().all()
    sessions = _latest_by_candidate(
        list((await db.execute(select(ChatSession).where(ChatSession.job_id == job_id))).scalars())
    )
    evaluations = _latest_by_candidate(
        list((await db.execute(select(Evaluation).where(Evaluation.job_id == job_id))).scalars())
    )

    metrics: list[JobMetricsCandidate] = []
    reached = {f"D{i}": 0 for i in range(1, 9)}
    completed = {f"D{i}": 0 for i in range(1, 9)}
    finished = 0
    for candidate in candidates:
        session = sessions.get(candidate.id)
        ev = evaluations.get(candidate.id)
        status = session.status if session else "pending"
        answered, locked, current = _session_progress(session)
        if status == "completed":
            finished += 1
            locked = [f"D{i}" for i in range(1, 9)] if not locked else locked
            answered = max(answered, 8)
        for dim in locked:
            completed[dim] = completed.get(dim, 0) + 1
        if session is not None:
            for i in range(1, 9):
                dim = f"D{i}"
                if dim in locked or (current is not None and int(dim[1]) <= int(current[1])):
                    reached[dim] += 1
        metrics.append(
            JobMetricsCandidate(
                nombre=candidate.nombre,
                interview_status=status,
                dimensions_answered=answered,
                dimensions_locked=locked,
                current_dimension=current,
                final_score=_score_str(ev.weighted_score) if status == "completed" and ev else None,
            )
        )

    total = len(candidates) or 1
    funnel = [
        JobMetricsFunnelStep(
            dimension_id=f"D{i}",
            reached_count=reached[f"D{i}"],
            completed_count=completed[f"D{i}"],
        )
        for i in range(1, 9)
    ]
    return JobMetricsResponse(
        candidates=metrics,
        funnel=funnel,
        completion_rate=f"{finished / total:.2f}",
    )


@router.post("/{job_id}/close", response_model=CloseJobResponse)
async def close_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "closed":
        raise HTTPException(status_code=409, detail={"error": "already_closed"})

    sessions = (
        await db.execute(select(ChatSession).where(ChatSession.job_id == job_id))
    ).scalars().all()
    expired = 0
    for session in sessions:
        if session.status == "active":
            session.status = "expired"
            expired += 1

    job.status = "closed"
    await db.commit()
    await db.refresh(job)

    audit = await _audit_payload(job, db)
    winner_score = None
    if audit.winner_candidate_id:
        winner_row = next(
            (c for c in audit.all_candidates if c.candidate_id == audit.winner_candidate_id),
            None,
        )
        winner_score = winner_row.interview_score if winner_row else None

    notified = sum(1 for c in audit.all_candidates if c.passed_ko)
    return CloseJobResponse(
        job_id=job.id,
        status="closed",
        winner_candidate_id=audit.winner_candidate_id,
        winner_nombre=audit.winner_nombre,
        winner_score=winner_score,
        sessions_expired=expired,
        notifications_sent=notified,
    )


@router.get("/{job_id}/report", response_class=PlainTextResponse)
async def get_report(job_id: str, db: AsyncSession = Depends(get_db)):
    """Returns the final selection report in Markdown format."""
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    report = await ReportWriter().generate(job_id, db)
    return PlainTextResponse(content=report, media_type="text/markdown; charset=utf-8")
