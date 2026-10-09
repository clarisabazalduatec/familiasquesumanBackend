import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.catalogo import Ciudad
from app.models.enums import TipoCentro, enum_col


class CentroVisiteo(Base):
    __tablename__ = "centros_visiteo"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo: Mapped[TipoCentro] = mapped_column(enum_col(TipoCentro, "tipo_centro"))
    nombre: Mapped[str] = mapped_column(String(200))
    descripcion_corta: Mapped[str] = mapped_column(String(300))
    informacion_general: Mapped[str] = mapped_column(Text)
    direccion: Mapped[str] = mapped_column(String(250))
    ciudad_id: Mapped[int] = mapped_column(ForeignKey("ciudades.id"), index=True)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    como_ayudar: Mapped[str | None] = mapped_column(Text)
    recomendaciones: Mapped[str | None] = mapped_column(Text)
    telefono: Mapped[str | None] = mapped_column(String(20))
    whatsapp: Mapped[str | None] = mapped_column(String(20))
    verificado: Mapped[bool] = mapped_column(default=True, server_default="true")
    activo: Mapped[bool] = mapped_column(default=True, server_default="true")

    ciudad: Mapped[Ciudad] = relationship(lazy="selectin")
    necesidades: Mapped[list["CentroNecesidad"]] = relationship(
        cascade="all, delete-orphan", order_by="CentroNecesidad.orden", lazy="selectin"
    )


class CentroNecesidad(Base):
    __tablename__ = "centro_necesidades"

    id: Mapped[int] = mapped_column(primary_key=True)
    centro_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("centros_visiteo.id", ondelete="CASCADE"), index=True
    )
    descripcion: Mapped[str] = mapped_column(Text)
    orden: Mapped[int] = mapped_column(default=0, server_default="0")