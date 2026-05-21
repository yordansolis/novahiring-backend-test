"""
Tests unitarios del flujo de entrevista.
No requieren base de datos, Redis ni llamadas a IA.
Los scores simulados vienen del dataset de conversaciones en docs/data/conversations/.
"""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from contracts import DiscoveryJSON, DimensionScore
from services.interview_conductor import (
    INTERVIEW_QUESTIONS,
    TOTAL_QUESTIONS,
    _load_state,
    _make_question_info,
    _question_text,
    _save_state,
)
from services.scorer import Scorer

CONVERSATIONS_DIR = Path(__file__).parent.parent / "docs" / "data" / "conversations"
PESOS = {"D1": 3, "D2": 3, "D3": 3, "D4": 3, "D5": 2, "D6": 2, "D7": 2, "D8": 1}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_scenario(name: str) -> dict:
    return json.loads((CONVERSATIONS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def scores_from_scenario(scenario: dict) -> list[DimensionScore]:
    return [
        DimensionScore(
            dimension_id=a["dimension_id"],
            peso=PESOS[a["dimension_id"]],
            score=Decimal(str(a["simulated_ai_score"])),
            justificacion=a["simulated_ai_justificacion"],
            evidencia=a["simulated_ai_evidencia"],
        )
        for a in scenario["answers"]
    ]


class FakeChatSession:
    """Simula ChatSession sin necesitar base de datos."""
    def __init__(self):
        self.context_summary = None
        self.status = "active"
        self.id = "test-session-id"
        self.job_id = "job-clinica-salud-valencia-001"
        self.candidate_id = "cand-13-sofia-delgado"


# ── 1. Estructura de preguntas ────────────────────────────────────────────────

def test_questions_list_has_eight_entries():
    assert TOTAL_QUESTIONS == 8
    assert len(INTERVIEW_QUESTIONS) == 8


def test_questions_dimension_ids_are_sequential():
    for i, q in enumerate(INTERVIEW_QUESTIONS):
        assert q["dimension_id"] == f"D{i + 1}", f"Posición {i} debería ser D{i+1}"


def test_questions_all_have_required_fields():
    for q in INTERVIEW_QUESTIONS:
        assert "dimension_id" in q
        assert "dimension_name" in q
        assert "question_text" in q
        assert len(q["question_text"]) > 20, "La pregunta es demasiado corta"


def test_questions_cover_all_dimensions():
    ids = {q["dimension_id"] for q in INTERVIEW_QUESTIONS}
    assert ids == {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"}


# ── 2. Generación de QuestionInfo ─────────────────────────────────────────────

def test_make_question_info_first():
    info = _make_question_info(0)
    assert info.dimension_id == "D1"
    assert info.question_number == 1
    assert info.total_questions == 8


def test_make_question_info_last():
    info = _make_question_info(7)
    assert info.dimension_id == "D8"
    assert info.question_number == 8
    assert info.total_questions == 8


def test_make_question_info_middle():
    info = _make_question_info(3)
    assert info.dimension_id == "D4"
    assert info.question_number == 4


def test_question_text_includes_number_and_name():
    text = _question_text(0)
    assert "1 de 8" in text
    assert "D1" in text or "Integraciones" in text


# ── 3. Estado de sesión (context_summary JSON) ────────────────────────────────

def test_initial_state_load_returns_defaults():
    session = FakeChatSession()
    state = _load_state(session)
    assert state["current_question_index"] == 0
    assert state["answers"] == {}
    assert state["evaluation_id"] is None


def test_save_and_load_state_roundtrip():
    session = FakeChatSession()
    original = {
        "current_question_index": 4,
        "answers": {"D1": "respuesta uno", "D2": "respuesta dos"},
        "evaluation_id": None,
    }
    _save_state(session, original)
    loaded = _load_state(session)
    assert loaded == original


def test_state_persists_evaluation_id():
    session = FakeChatSession()
    state = {"current_question_index": 8, "answers": {}, "evaluation_id": "eval-abc-123"}
    _save_state(session, state)
    assert _load_state(session)["evaluation_id"] == "eval-abc-123"


def test_state_answers_accumulate():
    session = FakeChatSession()
    state = _load_state(session)
    for i, q in enumerate(INTERVIEW_QUESTIONS):
        state["answers"][q["dimension_id"]] = f"respuesta {i + 1}"
        state["current_question_index"] = i + 1
        _save_state(session, state)

    final = _load_state(session)
    assert final["current_question_index"] == 8
    assert len(final["answers"]) == 8
    assert final["answers"]["D1"] == "respuesta 1"
    assert final["answers"]["D8"] == "respuesta 8"


# ── 4. Scorer con scores simulados del dataset ────────────────────────────────

@pytest.fixture
def discovery_fixture():
    return DiscoveryJSON(
        cliente={},
        problema_negocio={},
        producto_a_construir={},
        contexto_equipo={},
        restricciones={},
        perfil_candidato={
            "habilidades_tecnicas": {"obligatorias": [], "deseables": []},
            "habilidades_blandas": {},
            "senales_de_seniority": {},
            "criterios_de_descarte": [
                {"id": "KO1", "descripcion": "WhatsApp", "razon": "x"},
                {"id": "KO2", "descripcion": "RGPD", "razon": "x"},
                {"id": "KO3", "descripcion": "Autonomy", "razon": "x"},
            ],
        },
        scorecard={
            "peso_total": 19,
            "dimensiones": [
                {"id": "D1", "nombre": "Integraciones", "peso": 3, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D2", "nombre": "RGPD", "peso": 3, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D3", "nombre": "Autonomía", "peso": 3, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D4", "nombre": "Pragmatismo", "peso": 3, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D5", "nombre": "Entrega", "peso": 2, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D6", "nombre": "Comunicación", "peso": 2, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D7", "nombre": "Salud", "peso": 2, "rubricas": {"5": "a", "3": "b", "1": "c"}},
                {"id": "D8", "nombre": "Stack", "peso": 1, "rubricas": {"5": "a", "3": "b", "1": "c"}},
            ],
        },
        criterios_de_exito=[],
    )


def test_scenario_ganador_claro_score(discovery_fixture):
    scenario = load_scenario("ganador_claro")
    scores = scores_from_scenario(scenario)
    weighted, normalized = Scorer().calculate(scores, discovery_fixture)
    expected = Decimal(scenario["expected_result"]["weighted_score"])
    assert weighted == expected, f"Esperado {expected}, obtenido {weighted}"


def test_scenario_buen_candidato_score(discovery_fixture):
    scenario = load_scenario("buen_candidato")
    scores = scores_from_scenario(scenario)
    weighted, _ = Scorer().calculate(scores, discovery_fixture)
    expected = Decimal(scenario["expected_result"]["weighted_score"])
    assert weighted == expected


def test_scenario_candidato_promedio_score(discovery_fixture):
    scenario = load_scenario("candidato_promedio")
    scores = scores_from_scenario(scenario)
    weighted, _ = Scorer().calculate(scores, discovery_fixture)
    expected = Decimal(scenario["expected_result"]["weighted_score"])
    assert weighted == expected


def test_scenario_respuestas_debiles_score(discovery_fixture):
    scenario = load_scenario("respuestas_debiles")
    scores = scores_from_scenario(scenario)
    weighted, _ = Scorer().calculate(scores, discovery_fixture)
    expected = Decimal(scenario["expected_result"]["weighted_score"])
    assert weighted == expected


# ── 5. Ranking y ganador ──────────────────────────────────────────────────────

def test_ganador_claro_is_first(discovery_fixture):
    scenarios = ["ganador_claro", "buen_candidato", "candidato_promedio", "respuestas_debiles"]
    results = []
    for name in scenarios:
        s = load_scenario(name)
        weighted, _ = Scorer().calculate(scores_from_scenario(s), discovery_fixture)
        results.append((weighted, s["scenario"]))

    results.sort(reverse=True)
    assert results[0][1] == "ganador_claro"


def test_ranking_order_matches_expected(discovery_fixture):
    scenarios = ["ganador_claro", "buen_candidato", "candidato_promedio", "respuestas_debiles"]
    results = []
    for name in scenarios:
        s = load_scenario(name)
        weighted, _ = Scorer().calculate(scores_from_scenario(s), discovery_fixture)
        results.append((weighted, s["scenario"], s["expected_result"]["ranking_position"]))

    results.sort(reverse=True)
    for position, (_, scenario_name, expected_pos) in enumerate(results, start=1):
        assert position == expected_pos, f"{scenario_name}: esperado pos {expected_pos}, obtenido {position}"


def test_all_scenarios_are_apto():
    # Todos pasaron el KO — el sistema no debe producir DESCARTADO
    for name in ["ganador_claro", "buen_candidato", "candidato_promedio", "respuestas_debiles"]:
        s = load_scenario(name)
        assert s["expected_result"]["resultado"] == "APTO"


def test_ganador_score_above_threshold(discovery_fixture):
    s = load_scenario("ganador_claro")
    weighted, _ = Scorer().calculate(scores_from_scenario(s), discovery_fixture)
    assert weighted >= Decimal("4.50"), "El ganador debería superar 4.50"


def test_debil_score_below_threshold(discovery_fixture):
    s = load_scenario("respuestas_debiles")
    weighted, _ = Scorer().calculate(scores_from_scenario(s), discovery_fixture)
    assert weighted < Decimal("2.50"), "El candidato débil debería estar por debajo de 2.50"


def test_score_gap_between_winner_and_weak(discovery_fixture):
    ganador = load_scenario("ganador_claro")
    debil = load_scenario("respuestas_debiles")
    w_ganador, _ = Scorer().calculate(scores_from_scenario(ganador), discovery_fixture)
    w_debil, _ = Scorer().calculate(scores_from_scenario(debil), discovery_fixture)
    gap = w_ganador - w_debil
    assert gap >= Decimal("2.50"), f"El gap debería ser >= 2.50, es {gap}"


# ── 6. Cobertura de preguntas en el dataset ───────────────────────────────────

@pytest.mark.parametrize("scenario_name", [
    "ganador_claro", "buen_candidato", "candidato_promedio", "respuestas_debiles"
])
def test_dataset_has_all_eight_answers(scenario_name):
    s = load_scenario(scenario_name)
    assert len(s["answers"]) == 8, f"{scenario_name} debe tener 8 respuestas"
    dim_ids = {a["dimension_id"] for a in s["answers"]}
    assert dim_ids == {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"}


@pytest.mark.parametrize("scenario_name", [
    "ganador_claro", "buen_candidato", "candidato_promedio", "respuestas_debiles"
])
def test_dataset_scores_in_valid_range(scenario_name):
    s = load_scenario(scenario_name)
    for answer in s["answers"]:
        score = answer["simulated_ai_score"]
        assert 1 <= score <= 5, f"{scenario_name}/{answer['dimension_id']}: score {score} fuera de rango"


@pytest.mark.parametrize("scenario_name", [
    "ganador_claro", "buen_candidato", "candidato_promedio", "respuestas_debiles"
])
def test_dataset_answers_are_not_empty(scenario_name):
    s = load_scenario(scenario_name)
    for answer in s["answers"]:
        assert len(answer["answer"]) >= 10, (
            f"{scenario_name}/{answer['dimension_id']}: respuesta demasiado corta"
        )
