"""API key authentication dependencies."""
import secrets

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from config import get_settings
from contracts import CandidateTokenClaims
from database import get_redis

_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer_scheme = HTTPBearer(auto_error=False)


def _check(provided: str | None, *valid_keys: str) -> bool:
    """Timing-safe check: provided key matches any of the valid keys."""
    if not provided:
        return False
    return any(secrets.compare_digest(provided, k) for k in valid_keys if k)


async def require_admin(api_key: str | None = Security(_key_header)) -> None:
    """Admin key required. Bypassed if API_KEY_ADMIN is not configured (dev/test)."""
    settings = get_settings()
    if not settings.API_KEY_ADMIN:
        return
    if not _check(api_key, settings.API_KEY_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")


async def require_candidate(api_key: str | None = Security(_key_header)) -> None:
    """Candidate or admin key required. Bypassed if neither key is configured (dev/test)."""
    settings = get_settings()
    if not settings.API_KEY_CANDIDATES and not settings.API_KEY_ADMIN:
        return
    if not _check(api_key, settings.API_KEY_CANDIDATES, settings.API_KEY_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")


async def require_interview_access(
    api_key: str | None = Security(_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> CandidateTokenClaims | None:
    """Bearer token (per-candidate) OR X-API-Key. Returns claims when Bearer is used, else None."""
    if bearer:
        from services.token_manager import TokenManager
        claims = await TokenManager(get_redis()).resolve_token(bearer.credentials)
        if claims:
            return CandidateTokenClaims(**claims)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    settings = get_settings()
    if not settings.API_KEY_CANDIDATES and not settings.API_KEY_ADMIN:
        return None   # dev bypass
    if not _check(api_key, settings.API_KEY_CANDIDATES, settings.API_KEY_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return None   # X-API-Key path — no candidate claims
