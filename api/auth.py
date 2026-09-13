"""Authentication: dependencies (admin / candidate) + recruiter login endpoints."""
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from contracts import (
    CandidateLoginRequest,
    CandidateLoginResponse,
    CandidateTokenClaims,
    LoginRequest,
    LoginResponse,
    RecruiterClaims,
    UserPublic,
)
from database import get_db, get_redis
from services.auth_service import AuthService, RecruiterTokenManager
from services.token_manager import TokenManager

logger = logging.getLogger("nova.auth")

_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer_scheme = HTTPBearer(auto_error=False)

router = APIRouter()


def _check(provided: str | None, *valid_keys: str) -> bool:
    """Timing-safe check: provided key matches any of the valid keys."""
    if not provided:
        return False
    return any(secrets.compare_digest(provided, k) for k in valid_keys if k)


def _get_recruiter_tokens() -> RecruiterTokenManager:
    return RecruiterTokenManager(get_redis())


# ── Dependencies ──────────────────────────────────────────────────────────────

async def require_admin(
    api_key: str | None = Security(_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> RecruiterClaims | None:
    """Recruiter Bearer token OR admin X-API-Key.

    Returns the recruiter's claims when a Bearer token is used, so endpoints can
    attribute actions; returns None on the shared-key path, which carries no
    identity. Bypassed entirely when API_KEY_ADMIN is unset (dev/test).
    """
    if bearer:
        claims = await _get_recruiter_tokens().resolve(bearer.credentials)
        if claims:
            return RecruiterClaims(**claims)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": "Invalid or expired session."},
        )

    settings = get_settings()
    if not settings.API_KEY_ADMIN:
        return None
    if not _check(api_key, settings.API_KEY_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return None


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
        recruiter = await _get_recruiter_tokens().resolve(bearer.credentials)
        if recruiter:
            return None
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    settings = get_settings()
    if not settings.API_KEY_CANDIDATES and not settings.API_KEY_ADMIN:
        return None   # dev bypass
    if not _check(api_key, settings.API_KEY_CANDIDATES, settings.API_KEY_ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return None   # X-API-Key path — no candidate claims


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    tokens = _get_recruiter_tokens()
    result = await AuthService(db, tokens).authenticate(body.email, body.password)
    if result is None:
        logger.info("Failed login attempt for %s", body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "message": "Email or password is incorrect."},
        )
    user, token = result
    logger.info("Recruiter %s logged in", user.email)
    return LoginResponse(
        access_token=token,
        expires_in=RecruiterTokenManager.TOKEN_TTL,
        user=UserPublic(**user.to_public()),
    )


@router.get("/me", response_model=UserPublic)
async def me(claims: RecruiterClaims | None = Depends(require_admin)) -> UserPublic:
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "no_identity",
                "message": "This endpoint requires a recruiter session, not the shared admin key.",
            },
        )
    return UserPublic(
        id=claims.user_id,
        email=claims.email,
        nombre=claims.nombre,
        rol=claims.rol,
        tenant_id=claims.tenant_id,
    )


@router.post("/logout", status_code=204)
async def logout(bearer: HTTPAuthorizationCredentials | None = Security(_bearer_scheme)) -> None:
    if bearer:
        await _get_recruiter_tokens().revoke(bearer.credentials)


@router.post("/candidate/login", response_model=CandidateLoginResponse)
async def candidate_login(body: CandidateLoginRequest) -> CandidateLoginResponse:
    data = await TokenManager(get_redis()).resolve_login(body.username, body.password)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_credentials", "message": "Credenciales incorrectas o expiradas."},
        )
    return CandidateLoginResponse(
        token=data["token"],
        candidate_id=data["candidate_id"],
        job_id=data["job_id"],
    )
