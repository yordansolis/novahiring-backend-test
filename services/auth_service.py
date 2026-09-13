"""Recruiter authentication: password hashing + Redis-backed session tokens.

Mirrors services/token_manager.py on purpose — tokens live in Redis with a TTL,
so logout and expiry are a single DEL/TTL rather than a JWT blacklist.
"""
import json
import uuid

import bcrypt
import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User

# bcrypt truncates silently past 72 bytes; reject instead of hashing a prefix.
MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    _reject_oversized(plain)
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, password_hash: str) -> bool:
    if len(plain.encode()) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(plain.encode(), password_hash.encode())
    except ValueError:
        # Malformed hash in the DB — treat as a failed login, never a 500.
        return False


def _reject_oversized(plain: str) -> None:
    if len(plain.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password exceeds {MAX_PASSWORD_BYTES} bytes")


class RecruiterTokenManager:
    TOKEN_TTL = 12 * 3600  # a working day

    def __init__(self, r: redis.Redis) -> None:
        self._r = r

    async def create(self, user: User) -> str:
        token = str(uuid.uuid4())
        await self._r.set(
            f"recruiter_token:{token}",
            json.dumps({
                "user_id": user.id,
                "email": user.email,
                "nombre": user.nombre,
                "rol": user.rol,
                "tenant_id": user.tenant_id,
            }),
            ex=self.TOKEN_TTL,
        )
        return token

    async def resolve(self, token: str) -> dict | None:
        val = await self._r.get(f"recruiter_token:{token}")
        return json.loads(val) if val else None

    async def revoke(self, token: str) -> bool:
        return bool(await self._r.delete(f"recruiter_token:{token}"))


class AuthService:
    def __init__(self, db: AsyncSession, tokens: RecruiterTokenManager) -> None:
        self._db = db
        self._tokens = tokens

    async def authenticate(self, email: str, password: str) -> tuple[User, str] | None:
        """Returns (user, token) on success, None on any failure.

        Deliberately does not distinguish unknown-email from wrong-password:
        that difference leaks which accounts exist.
        """
        result = await self._db.execute(
            select(User).where(User.email == email.strip().lower())
        )
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            # Spend the same work as a real check so timing does not reveal
            # whether the account exists.
            verify_password(password, _DUMMY_HASH)
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user, await self._tokens.create(user)


# Pre-computed hash of a value no one can log in with, used to equalise timing.
_DUMMY_HASH = "$2b$12$M6Y0M1ZTFyZGVjb3lkZWNveWRlY.0OqQ0pGZ3M2cXh3ZGVjb3lkZWNveWRl"
