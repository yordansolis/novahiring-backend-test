"""Per-candidate interview access tokens and login credentials backed by Redis."""
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

    async def store_credentials(
        self,
        candidate_id: str,
        job_id: str,
        username: str,
        password: str,
        token: str,
    ) -> None:
        payload = json.dumps({
            "username": username,
            "password": password,
            "token": token,
            "candidate_id": candidate_id,
            "job_id": job_id,
        })
        await self._r.set(f"candidate_creds:{candidate_id}", payload, ex=self.TOKEN_TTL)
        await self._r.set(f"candidate_login:{username.lower()}", payload, ex=self.TOKEN_TTL)

    async def get_credentials(self, candidate_id: str) -> dict | None:
        val = await self._r.get(f"candidate_creds:{candidate_id}")
        return json.loads(val) if val else None

    async def resolve_login(self, username: str, password: str) -> dict | None:
        val = await self._r.get(f"candidate_login:{username.lower()}")
        if not val:
            return None
        data = json.loads(val)
        if data.get("password") != password:
            return None
        return data
