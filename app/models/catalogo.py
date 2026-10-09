import uuid

from sqlalchemy import Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import AmbitoCategoria, enum_col


class Ciudad(Base):
    __tablename__ = "ciudades"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)
    estado: Mapped[str] = mapped_column(String(80))
    activa: Mapped[bool] = mapped_column(default=True, server_default="true")


class Organizacion(Base):
    """Organizador de actividades / fundación de donaciones."""

    __tablename__ = "organizaciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(160), unique=True)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    verificada: Mapped[bool] = mapped_column(default=False, server_default="false")
    whatsapp: Mapped[str | None] = mapped_column(String(20))
    telefono: Mapped[str | None] = mapped_column(String(20))


class Categoria(Base):
    __tablename__ = "categorias"

    id: Mapped[int] = mapped_column(primary_key=True)
    ambito: Mapped[AmbitoCategoria] = mapped_column(enum_col(AmbitoCategoria, "ambito_categoria"))
    nombre: Mapped[str] = mapped_column(String(80))

    # "Educación" y "educación" no pueden coexistir dentro del mismo ámbito
    __table_args__ = (
        Index("uq_categorias_ambito_nombre", "ambito", func.lower(nombre), unique=True),
    )