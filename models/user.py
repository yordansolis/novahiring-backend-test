from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, new_uuid


class User(Base, TimestampMixin):
    """A human operator of the platform — today only recruiters.

    Candidates are NOT users: they never register, they are invited with a
    per-candidate token once their CV passes evaluation (see TokenManager).
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    nombre: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(50), default="recruiter")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def to_public(self) -> dict:
        """Safe representation — never includes password_hash."""
        return {
            "id": self.id,
            "email": self.email,
            "nombre": self.nombre,
            "rol": self.rol,
            "tenant_id": self.tenant_id,
        }
