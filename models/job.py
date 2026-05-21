from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, new_uuid


class JobOpening(Base, TimestampMixin):
    __tablename__ = "job_openings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    niche: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(255))
    offer_text: Mapped[str | None] = mapped_column(Text)
    discovery_json: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(50), default="active")
