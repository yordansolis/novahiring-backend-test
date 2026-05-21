from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, new_uuid


class Candidate(Base, TimestampMixin):
    __tablename__ = "candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("job_openings.id"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nombre: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ubicacion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    años_experiencia: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cv_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cv_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    passed_ko: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    profile_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
