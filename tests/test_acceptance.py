"""
Acceptance test: must reproduce Clínica Salud Valencia ranking from seeded data.
Run after: docker compose up -d && uv run python seed.py case
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from config import get_settings
from main import app

JOB_ID = "job-clinica-salud-valencia-001"


def _admin_headers() -> dict[str, str]:
    """Admin key when one is configured; empty dict when auth is bypassed (dev)."""
    key = get_settings().API_KEY_ADMIN
    return {"X-API-Key": key} if key else {}

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=_admin_headers(),
    ) as c:
        yield c


async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_ranking_matches_reference(client):
    response = await client.get(f"/api/v1/jobs/{JOB_ID}/ranking")
    assert response.status_code == 200

    data = response.json()
    candidates = data["candidates"]

    apto = [c for c in candidates if c["passed_ko"]]
    descartado = [c for c in candidates if not c["passed_ko"]]

    assert len(apto) == 3
    assert len(descartado) == 3

    assert Decimal(str(apto[0]["weighted_score"])) == Decimal("4.84")
    assert Decimal(str(apto[1]["weighted_score"])) == Decimal("4.74")
    assert Decimal(str(apto[2]["weighted_score"])) == Decimal("4.58")

    for d in descartado:
        assert d["weighted_score"] is None
        assert d["resultado"] == "DESCARTADO"


async def test_job_offer_returns_markdown(client):
    response = await client.get(f"/api/v1/jobs/{JOB_ID}/offer")
    assert response.status_code == 200
    data = response.json()
    assert "offer_text" in data
    assert len(data["offer_text"]) > 0


async def test_job_profile_has_ko_criteria(client):
    response = await client.get(f"/api/v1/jobs/{JOB_ID}/profile")
    assert response.status_code == 200
    data = response.json()
    ko_ids = [k["id"] for k in data["ko_criteria"]]
    assert "KO1" in ko_ids
    assert "KO2" in ko_ids
    assert "KO3" in ko_ids
    assert data["total_weight"] == 19


async def test_missing_job_returns_404(client):
    response = await client.get("/api/v1/jobs/nonexistent/offer")
    assert response.status_code == 404


# ── Recruiter login ───────────────────────────────────────────────────────────

RECRUITER_EMAIL = "recruiter@clinicasaludvalencia.es"


async def test_login_rejects_bad_password(client):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": RECRUITER_EMAIL, "password": "definitely-wrong"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "invalid_credentials"


async def test_login_does_not_reveal_which_emails_exist(client):
    """Unknown email and wrong password must be indistinguishable."""
    unknown = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "definitely-wrong"},
    )
    known = await client.post(
        "/api/v1/auth/login",
        json={"email": RECRUITER_EMAIL, "password": "definitely-wrong"},
    )
    assert unknown.status_code == known.status_code == 401
    assert unknown.json() == known.json()


async def test_login_requires_a_plausible_password_length(client):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": RECRUITER_EMAIL, "password": "short"},
    )
    assert r.status_code == 422


async def test_recruiter_token_opens_admin_endpoints(client):
    """Full round trip: login -> use token -> /me -> logout -> token is dead."""
    password = _recruiter_password()
    if not password:
        pytest.skip("set SEED_RECRUITER_PASSWORD to run the recruiter login round trip")
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": RECRUITER_EMAIL, "password": password},
    )
    if login.status_code == 401:
        pytest.skip("recruiter password does not match; re-run seed.py recruiter")
    assert login.status_code == 200
    token = login.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=auth)
    assert me.status_code == 200
    assert me.json()["email"] == RECRUITER_EMAIL

    ranking = await client.get(f"/api/v1/jobs/{JOB_ID}/ranking", headers=auth)
    assert ranking.status_code == 200

    assert (await client.post("/api/v1/auth/logout", headers=auth)).status_code == 204
    after = await client.get(f"/api/v1/jobs/{JOB_ID}/ranking", headers=auth)
    assert after.status_code == 401


def _recruiter_password() -> str:
    import os
    return os.environ.get("SEED_RECRUITER_PASSWORD", "")
