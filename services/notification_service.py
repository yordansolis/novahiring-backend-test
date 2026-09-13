"""Interview invitations: credentials + optional real email."""
import asyncio
import hashlib
import logging
import re
import secrets
import string
import unicodedata

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis

from config import get_settings
from models.candidate import Candidate
from models.evaluation import Evaluation
from models.job import JobOpening
from models.ops import CandidateInvitation
from services.email_service import send_interview_invitation_email, smtp_configured
from services.token_manager import TokenManager

logger = logging.getLogger("nova.notifications")

_PASSWORD_ALPHABET = string.ascii_letters + string.digits


def _username_from_name(nombre: str) -> str:
    folded = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    parts = [p for p in re.split(r"[^a-z0-9]+", folded.lower()) if p]
    slug = ".".join(parts[:2]) if parts else "candidato"
    return f"{slug}.{secrets.token_hex(2)}"


def _password() -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(10))


class NotificationService:
    def __init__(self, db: AsyncSession, r: redis.Redis) -> None:
        self._db = db
        self._token_manager = TokenManager(r)

    async def send_interview_invitation(self, candidate: Candidate, job_id: str) -> str:
        job = await self._db.get(JobOpening, job_id)
        job_title = job.title if job is not None else job_id
        login_url = f"{get_settings().FRONTEND_URL.rstrip('/')}/login/candidate"

        token = await self._token_manager.create_candidate_token(candidate.id, job_id)
        username = _username_from_name(candidate.nombre)
        password = _password()
        await self._token_manager.store_credentials(
            candidate.id, job_id, username, password, token
        )
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        status = "not_configured"
        if not candidate.email:
            status = "failed"
            logger.warning("Invitation skipped — candidate %s has no email", candidate.id)
        elif smtp_configured():
            try:
                await asyncio.to_thread(
                    send_interview_invitation_email,
                    candidate.email,
                    candidate.nombre,
                    job_title,
                    username,
                    password,
                    login_url,
                )
                status = "sent"
            except Exception as exc:
                status = "failed"
                logger.exception("Invitation email failed for %s: %s", candidate.email, exc)
        else:
            logger.warning(
                "[EMAIL NOT SENT] SMTP no configurado | To: %s | Login: %s / %s",
                candidate.email,
                username,
                password,
            )

        existing = (
            await self._db.execute(
                select(CandidateInvitation)
                .where(
                    CandidateInvitation.candidate_id == candidate.id,
                    CandidateInvitation.job_id == job_id,
                )
                .order_by(CandidateInvitation.created_at.desc())
            )
        ).scalars().first()

        if existing is not None:
            existing.token_hash = token_hash
            existing.email = candidate.email
            existing.email_status = status
            invitation = existing
        else:
            invitation = CandidateInvitation(
                candidate_id=candidate.id,
                job_id=job_id,
                token_hash=token_hash,
                email=candidate.email,
                email_status=status,
            )
            self._db.add(invitation)

        await self._db.flush()
        return token

    async def invite_apto_candidates(self, job_id: str) -> dict:
        """Create/refresh invitations for APTO candidates that are not already sent."""
        evals = (
            await self._db.execute(select(Evaluation).where(Evaluation.job_id == job_id))
        ).scalars().all()
        latest: dict[str, Evaluation] = {}
        for ev in evals:
            prev = latest.get(ev.candidate_id)
            if prev is None or ev.created_at > prev.created_at:
                latest[ev.candidate_id] = ev

        invitations = (
            await self._db.execute(
                select(CandidateInvitation).where(CandidateInvitation.job_id == job_id)
            )
        ).scalars().all()
        invited_status = {row.candidate_id: row.email_status for row in invitations}

        candidates = (
            await self._db.execute(select(Candidate).where(Candidate.job_id == job_id))
        ).scalars().all()

        attempted = 0
        sent = 0
        failed = 0
        for candidate in candidates:
            ev = latest.get(candidate.id)
            if ev is None or ev.resultado != "APTO":
                continue
            if invited_status.get(candidate.id) == "sent":
                continue
            attempted += 1
            await self.send_interview_invitation(candidate, job_id)
            row = (
                await self._db.execute(
                    select(CandidateInvitation)
                    .where(CandidateInvitation.candidate_id == candidate.id)
                    .order_by(CandidateInvitation.created_at.desc())
                )
            ).scalars().first()
            if row is not None and row.email_status == "sent":
                sent += 1
            else:
                failed += 1

        await self._db.commit()
        configured = smtp_configured()
        error = None
        if not configured and attempted > 0:
            error = (
                "SMTP no configurado. Las credenciales están en Candidatos; "
                "el email no se envió."
            )
        return {
            "job_id": job_id,
            "attempted": attempted,
            "sent": sent,
            "failed": failed,
            "smtp_configured": configured,
            "error": error,
        }
