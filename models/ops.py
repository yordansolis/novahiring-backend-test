"""Modelos operacionales: prompts, auditoría de IA, preguntas y sesiones de chat."""
from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, new_uuid


class PromptVersion(Base, TimestampMixin):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        Index("ix_prompt_versions_active_name", "name", unique=True, postgresql_where="is_active = true"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(50), default="anthropic")
    model: Mapped[str] = mapped_column(String(100))
    max_tokens: Mapped[int] = mapped_column(Integer)
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text)


class AICallLog(Base, TimestampMixin):
    """Append-only. Nunca se actualiza, solo se inserta."""
    __tablename__ = "ai_call_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    prompt_version_id: Mapped[str] = mapped_column(String(36))
    prompt_name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(50), default="anthropic")
    model: Mapped[str] = mapped_column(String(100))
    temperature: Mapped[float] = mapped_column(Float)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_passed: Mapped[bool] = mapped_column(Boolean)
    system_prompt: Mapped[str] = mapped_column(Text)
    user_messages: Mapped[dict] = mapped_column(JSONB)
    response_text: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Question(Base, TimestampMixin):
    __tablename__ = "question_bank"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    niche: Mapped[str] = mapped_column(String(100), index=True)
    bloque: Mapped[str] = mapped_column(String(100))
    orden: Mapped[int] = mapped_column(Integer)
    pregunta: Mapped[str] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(50))
    opciones: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    genera: Mapped[dict] = mapped_column(JSONB)
    peso: Mapped[int] = mapped_column(Integer)
    obligatoria: Mapped[bool] = mapped_column(Boolean, default=True)
    condicion: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    inferida_de: Mapped[str | None] = mapped_column(String(50), nullable=True)


class ChatSession(Base, TimestampMixin):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("job_openings.id"), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("candidates.id"), nullable=True, index=True)
    session_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    sequence_number: Mapped[int] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    is_summarized: Mapped[bool] = mapped_column(default=False)
