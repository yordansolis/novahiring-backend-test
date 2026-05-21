"""Todos los contratos Pydantic del sistema en un solo lugar."""
from decimal import Decimal
from enum import Enum
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field


class DialogueTurn(TypedDict):
    role: str    # "assistant" | "user"
    content: str


# ── Sesiones ──────────────────────────────────────────────────────────────────

class SessionStatus(str, Enum):
    ACTIVE = "active"
    PROCESSING = "processing"
    PAUSED = "paused"
    COMPLETED = "completed"
    EXPIRED = "expired"


class SessionType(str, Enum):
    DISCOVERY = "discovery"
    INTERVIEW = "interview"
    REPORT = "report"


# ── Discovery (perfil del cliente) ────────────────────────────────────────────

class KOCriterion(BaseModel):
    id: str
    descripcion: str
    razon: str
    is_eliminatory: bool = True


class ScorecardDimension(BaseModel):
    id: str
    nombre: str
    peso: int
    rubricas: dict[str, str]


class DiscoveryJSON(BaseModel):
    cliente: dict
    problema_negocio: dict
    producto_a_construir: dict
    contexto_equipo: dict
    restricciones: dict
    perfil_candidato: dict
    scorecard: dict
    criterios_de_exito: list[str]

    @property
    def ko_criteria(self) -> list[KOCriterion]:
        return [KOCriterion(**k) for k in self.perfil_candidato["criterios_de_descarte"]]

    @property
    def dimensions(self) -> list[ScorecardDimension]:
        return [ScorecardDimension(**d) for d in self.scorecard["dimensiones"]]

    @property
    def total_weight(self) -> int:
        return self.scorecard["peso_total"]


# ── Perfil del candidato ──────────────────────────────────────────────────────

class KOScreenResult(BaseModel):
    ko_id: str
    resultado: str       # "PASA" | "FALLA"
    passed: bool         # siempre lo decide Python, nunca la IA
    evidencia: str


class CandidateProfile(BaseModel):
    candidate_id: str
    job_id: str
    ko_screen_results: list[KOScreenResult]
    passed_ko_screen: bool
    matched_required_skills: list[str]
    missing_required_skills: list[str]
    cv_sha256: str
    profile_algorithm_version: str


# ── Evaluación y scores ───────────────────────────────────────────────────────

Score = Annotated[Decimal, Field(ge=Decimal("1"), le=Decimal("5"))]


class DimensionScore(BaseModel):
    dimension_id: str
    peso: int
    score: Score
    justificacion: str
    evidencia: str


class EvaluationResult(BaseModel):
    ko_results: list[KOScreenResult]
    passed_ko: bool
    scores: list[DimensionScore]
    weighted_score: Decimal | None
    normalized_score: Decimal | None
    resultado: str                    # "APTO" | "DESCARTADO"
    narrative_report: str | None = None
    first_failing_ko: str | None = None


# ── Log de auditoría de IA ────────────────────────────────────────────────────

class AICallRecord(BaseModel):
    request_id: str
    session_id: str | None
    prompt_version_id: str
    prompt_name: str
    provider: str                    # "anthropic" | "openai"
    system_prompt: str
    user_messages: list[dict]
    response_text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str
    temperature: float
    retry_count: int
    validation_passed: bool
    error: str | None = None


# ── Entrevista — Request/Response ─────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    job_id: str | None = None
    candidate_id: str | None = None


class QuestionInfo(BaseModel):
    dimension_id: str
    dimension_name: str
    question_text: str
    question_number: int
    total_questions: int = 8


class MessageOut(BaseModel):
    role: str
    content: str
    sequence_number: int


class InterviewDimensionScore(BaseModel):
    dimension_id: str
    score: str
    peso: int
    justificacion: str
    evidencia: str


class InterviewEvaluationResult(BaseModel):
    session_id: str
    evaluation_id: str
    weighted_score: str
    normalized_score: str
    resultado: str
    dimension_scores: list[InterviewDimensionScore]


class SessionStarted(BaseModel):
    session_id: str
    status: str
    message: MessageOut
    next_question: QuestionInfo


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)


class MessageResponse(BaseModel):
    message_saved: bool
    next_question: QuestionInfo | None
    session_status: str
    evaluation_result: InterviewEvaluationResult | None


class SessionDetailResponse(BaseModel):
    session_id: str
    job_id: str | None
    candidate_id: str | None
    status: str
    current_question_index: int
    total_questions: int
    messages: list[MessageOut]


class InterruptResponse(BaseModel):
    status: str
    session_id: str


# ── Candidatos — CV upload / evaluación ──────────────────────────────────────

class CVUploadResponse(BaseModel):
    candidate_id: str
    status: str       # "received"
    passed_ko: bool


class EvaluationTriggerResponse(BaseModel):
    job_id: str
    queued_candidates: int
    status: str       # "evaluation_started"


class CandidateTokenClaims(BaseModel):
    candidate_id: str
    job_id: str


class CandidateListItem(BaseModel):
    candidate_id: str
    nombre: str
    email: str | None
    passed_ko: bool | None
    resultado: str | None       # "APTO" | "DESCARTADO" | None si no evaluado
    weighted_score: str | None
