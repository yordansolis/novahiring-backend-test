"""Mock notification service — simulates email without sending."""
import hashlib
import logging

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from models.candidate import Candidate
from models.ops import CandidateInvitation
from services.token_manager import TokenManager

logger = logging.getLogger("nova.notifications")


class NotificationService:
    def __init__(self, db: AsyncSession, r: redis.Redis) -> None:
        self._db = db
        self._token_manager = TokenManager(r)

    async def send_interview_invitation(self, candidate: Candidate, job_id: str) -> str:
        token = await self._token_manager.create_candidate_token(candidate.id, job_id)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        invitation = CandidateInvitation(
            candidate_id=candidate.id,
            job_id=job_id,
            token_hash=token_hash,
            email=candidate.email,
            email_status="simulated_sent",
        )
        self._db.add(invitation)
        await self._db.flush()

        logger.info(
            "[SIMULATED EMAIL] To: %s | Candidate: %s | Token: %s | InvitationID: %s",
            candidate.email,
            candidate.nombre,
            token,
            invitation.id,
        )
        return token
