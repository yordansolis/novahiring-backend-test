from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, new_uuid


class Evaluation(Base, TimestampMixin):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("job_openings.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), ForeignKey("candidates.id"), index=True)
    passed_ko: Mapped[bool] = mapped_column(Boolean, default=False)
    first_failing_ko: Mapped[str | None] = mapped_column(String(20), nullable=True)
    weighted_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    normalized_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    resultado: Mapped[str] = mapped_column(String(20))
    ko_results: Mapped[dict] = mapped_column(JSONB)
    narrative_report: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_summary(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "passed_ko": self.passed_ko,
            "weighted_score": str(self.weighted_score) if self.weighted_score else None,
            "normalized_score": str(self.normalized_score) if self.normalized_score else None,
            "resultado": self.resultado,
            "first_failing_ko": self.first_failing_ko,
        }


class DimensionScoreRecord(Base):
    __tablename__ = "dimension_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    evaluation_id: Mapped[str] = mapped_column(String(36), ForeignKey("evaluations.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), ForeignKey("candidates.id"), index=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("job_openings.id"), index=True)
    dimension_id: Mapped[str] = mapped_column(String(10))
    raw_score: Mapped[Decimal] = mapped_column(Numeric(3, 1))
    peso: Mapped[int] = mapped_column(Integer)
    justificacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidencia: Mapped[str | None] = mapped_column(Text, nullable=True)
