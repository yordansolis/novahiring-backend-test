"""Email health, invitation log, and manual send."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from contracts import (
    EmailHealthResponse,
    EmailNotificationItem,
    JobNotificationsResponse,
    SendInvitationsResponse,
)
from database import get_db, get_redis
from models.candidate import Candidate
from models.job import JobOpening
from models.ops import CandidateInvitation
from services.email_service import check_smtp_health
from services.notification_service import NotificationService

router = APIRouter()

_STATUS_MAP = {
    "sent": ("sent", None),
    "failed": ("failed", "El servidor de email rechazó el envío."),
    "not_configured": (
        "failed",
        "SMTP no configurado. Añade SMTP_USERNAME, SMTP_PASSWORD y SMTP_FROM_EMAIL en el .env del backend.",
    ),
    "simulated_sent": (
        "failed",
        "Invitación solo simulada: el email no se envió. Pulsa Enviar invitaciones o configura SMTP.",
    ),
}


@router.get("/health/email", response_model=EmailHealthResponse, dependencies=[Depends(require_admin)])
async def email_health() -> EmailHealthResponse:
    return EmailHealthResponse(**check_smtp_health())


@router.get("/{job_id}", response_model=JobNotificationsResponse, dependencies=[Depends(require_admin)])
async def list_notifications(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> JobNotificationsResponse:
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"})

    invitations = (
        await db.execute(
            select(CandidateInvitation)
            .where(CandidateInvitation.job_id == job_id)
            .order_by(CandidateInvitation.created_at.desc())
        )
    ).scalars().all()
    names = {
        c.id: c
        for c in (
            await db.execute(select(Candidate).where(Candidate.job_id == job_id))
        ).scalars().all()
    }

    items: list[EmailNotificationItem] = []
    sent = queued = failed = 0
    for inv in invitations:
        delivery, error = _STATUS_MAP.get(inv.email_status, ("failed", inv.email_status))
        if delivery == "sent":
            sent += 1
        elif delivery == "queued":
            queued += 1
        else:
            failed += 1
        candidate = names.get(inv.candidate_id)
        sent_at = inv.simulated_at or inv.created_at
        items.append(
            EmailNotificationItem(
                notification_id=inv.id,
                candidate_name=candidate.nombre if candidate is not None else inv.candidate_id,
                candidate_email=inv.email or (candidate.email if candidate is not None else None),
                notification_type="interview_invitation",
                delivery_status=delivery,
                delivery_error=error,
                sent_at=sent_at.isoformat() if sent_at is not None else "",
                delivered_at=sent_at.isoformat() if delivery == "sent" and sent_at is not None else None,
            )
        )

    return JobNotificationsResponse(
        job_id=job_id,
        total=len(items),
        sent=sent,
        queued=queued,
        failed=failed,
        notifications=items,
    )


@router.post(
    "/{job_id}/invitations",
    response_model=SendInvitationsResponse,
    dependencies=[Depends(require_admin)],
)
async def send_invitations(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> SendInvitationsResponse:
    job = await db.get(JobOpening, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": "job_not_found"})
    result = await NotificationService(db, get_redis()).invite_apto_candidates(job_id)
    return SendInvitationsResponse(**result)
