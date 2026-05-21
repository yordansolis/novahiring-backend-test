from decimal import Decimal

import pytest

from contracts import CandidateProfile, DimensionScore, KOScreenResult
from services.ko_checker import KOChecker
from services.scorer import Scorer

# ── Scorer ────────────────────────────────────────────────────────────────────

PESOS = {"D1": 3, "D2": 3, "D3": 3, "D4": 3, "D5": 2, "D6": 2, "D7": 2, "D8": 1}


def make_scores(values: dict[str, int], pesos: dict[str, int]) -> list[DimensionScore]:
    return [
        DimensionScore(
            dimension_id=dim_id,
            peso=pesos[dim_id],
            score=Decimal(str(score)),
            justificacion="",
            evidencia="",
        )
        for dim_id, score in values.items()
    ]


def test_scorer_sofia(discovery_fixture):
    # (5×3 + 5×3 + 5×3 + 4×3 + 5×2 + 5×2 + 5×2 + 5×1) / 19 = 92/19 = 4.84
    scores = make_scores({"D1": 5, "D2": 5, "D3": 5, "D4": 4, "D5": 5, "D6": 5, "D7": 5, "D8": 5}, PESOS)
    weighted, normalized = Scorer().calculate(scores, discovery_fixture)
    assert weighted == Decimal("4.84")
    assert normalized == Decimal("0.9680")


def test_scorer_carlos(discovery_fixture):
    # D1=5,D2=4,D3=5,D4=5,D5=5,D6=5,D7=4,D8=5 → 90/19 = 4.74
    scores = make_scores({"D1": 5, "D2": 4, "D3": 5, "D4": 5, "D5": 5, "D6": 5, "D7": 4, "D8": 5}, PESOS)
    weighted, _ = Scorer().calculate(scores, discovery_fixture)
    assert weighted == Decimal("4.74")


def test_scorer_elena(discovery_fixture):
    # D1=5,D2=5,D3=5,D4=4,D5=3,D6=5,D7=5,D8=4 → 87/19 = 4.58
    scores = make_scores({"D1": 5, "D2": 5, "D3": 5, "D4": 4, "D5": 3, "D6": 5, "D7": 5, "D8": 4}, PESOS)
    weighted, _ = Scorer().calculate(scores, discovery_fixture)
    assert weighted == Decimal("4.58")


def test_scorer_all_five(discovery_fixture):
    scores = make_scores({d: 5 for d in PESOS}, PESOS)
    weighted, normalized = Scorer().calculate(scores, discovery_fixture)
    assert weighted == Decimal("5.00")
    assert normalized == Decimal("1.0000")


def test_scorer_all_one(discovery_fixture):
    scores = make_scores({d: 1 for d in PESOS}, PESOS)
    weighted, normalized = Scorer().calculate(scores, discovery_fixture)
    assert weighted == Decimal("1.00")
    assert normalized == Decimal("0.2000")


# ── KO Checker ────────────────────────────────────────────────────────────────

def make_profile(ko_results: list[tuple[str, bool]]) -> CandidateProfile:
    results = [
        KOScreenResult(ko_id=ko_id, resultado="PASA" if passed else "FALLA", passed=passed, evidencia="")
        for ko_id, passed in ko_results
    ]
    return CandidateProfile(
        candidate_id="test",
        job_id="job-1",
        ko_screen_results=results,
        passed_ko_screen=all(r.passed for r in results),
        matched_required_skills=[],
        missing_required_skills=[],
        cv_sha256="abc",
        profile_algorithm_version="1.0.0",
    )


def test_all_pass():
    profile = make_profile([("KO1", True), ("KO2", True), ("KO3", True)])
    passed, failing = KOChecker().apply(profile)
    assert passed is True
    assert failing is None


def test_ko2_fails():
    profile = make_profile([("KO1", True), ("KO2", False), ("KO3", True)])
    passed, failing = KOChecker().apply(profile)
    assert passed is False
    assert failing == "KO2"


def test_first_ko_short_circuits():
    profile = make_profile([("KO1", False), ("KO2", False), ("KO3", False)])
    passed, failing = KOChecker().apply(profile)
    assert passed is False
    assert failing == "KO1"


def test_sofia_passes_all():
    profile = make_profile([("KO1", True), ("KO2", True), ("KO3", True)])
    passed, failing = KOChecker().apply(profile)
    assert passed is True
    assert failing is None


def test_jhordan_fails_ko2():
    profile = make_profile([("KO1", True), ("KO2", False)])
    passed, failing = KOChecker().apply(profile)
    assert passed is False
    assert failing == "KO2"
