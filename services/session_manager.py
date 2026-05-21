"""Redis session state: NX processing lock, interrupt flag, and meta hash."""
import redis.asyncio as redis

from config import Settings

_LOCK_TTL = 30   # seconds; overridable via Settings.PROCESSING_LOCK_TTL
_META_TTL = 604800  # 7 days; overridable via Settings.SESSION_TTL_SECONDS

# Lua script: atomically releases lock only if we still own it
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class SessionManager:
    def __init__(self, r: redis.Redis, settings: Settings) -> None:
        self._r = r
        self._lock_ttl = settings.PROCESSING_LOCK_TTL
        self._meta_ttl = settings.SESSION_TTL_SECONDS

    # ── Processing lock ───────────────────────────────────────────────────────

    async def acquire_processing_lock(self, session_id: str, request_id: str) -> bool:
        result = await self._r.set(
            f"session:{session_id}:processing",
            request_id,
            nx=True,
            ex=self._lock_ttl,
        )
        return result is not None

    async def release_processing_lock(self, session_id: str, request_id: str) -> None:
        await self._r.eval(_RELEASE_LUA, 1, f"session:{session_id}:processing", request_id)

    # ── Interrupt flag ────────────────────────────────────────────────────────

    async def set_interrupted(self, session_id: str) -> None:
        await self._r.set(f"session:{session_id}:interrupted", "1", ex=10)

    async def check_and_clear_interrupted(self, session_id: str) -> bool:
        key = f"session:{session_id}:interrupted"
        val = await self._r.get(key)
        if val:
            await self._r.delete(key)
            return True
        return False

    # ── Meta hash (mirrors DB state for fast reads) ───────────────────────────

    async def set_session_meta(self, session_id: str, **fields: str) -> None:
        key = f"session:{session_id}:meta"
        await self._r.hset(key, mapping=fields)
        await self._r.expire(key, self._meta_ttl)

    async def get_session_meta(self, session_id: str) -> dict:
        return await self._r.hgetall(f"session:{session_id}:meta")
