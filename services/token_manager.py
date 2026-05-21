"""Per-candidate interview access tokens backed by Redis."""
import json
import uuid

import redis.asyncio as redis


class TokenManager:
    TOKEN_TTL = 7 * 24 * 3600  # 7 days

    def __init__(self, r: redis.Redis) -> None:
        self._r = r

    async def create_candidate_token(self, candidate_id: str, job_id: str) -> str:
        token = str(uuid.uuid4())
        await self._r.set(
            f"candidate_token:{token}",
            json.dumps({"candidate_id": candidate_id, "job_id": job_id}),
            ex=self.TOKEN_TTL,
        )
        return token

    async def resolve_token(self, token: str) -> dict | None:
        val = await self._r.get(f"candidate_token:{token}")
        return json.loads(val) if val else None
