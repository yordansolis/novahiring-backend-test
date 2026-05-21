"""
Acceptance test: must reproduce Clínica Salud Valencia ranking from seeded data.
Run after: docker compose up -d && uv run python seed.py case
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from main import app

JOB_ID = "job-clinica-salud-valencia-001"

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
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
