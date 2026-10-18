"""Inscripciones de familias a actividades.

- Una familia tiene como máximo UNA inscripción CONFIRMADA por actividad.
- El cupo cuenta PERSONAS: cada participante (adulto o menor) ocupa un lugar.
- Cancelar no borra la fila: queda como historial con estado CANCELADA y deja de contar.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.database import Base
from app.models.enums import EstadoAsistencia, EstadoInscripcion, enum_col
from app.models.iniciativas import Actividad
from app.models.usuarios import Familia, FamiliaMenor, Usuario


class InscripcionActividad(Base):
    __tablename__ = "inscripciones_actividad"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actividad_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("actividades.iniciativa_id", ondelete="CASCADE")
    )
    familia_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("familias.id", ondelete="CASCADE"), index=True
    )
    inscrito_por_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    estado: Mapped[EstadoInscripcion] = mapped_column(
        enum_col(EstadoInscripcion, "estado_inscripcion"),
        default=EstadoInscripcion.CONFIRMADA,
        server_default=EstadoInscripcion.CONFIRMADA.value,
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cancelada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    actividad: Mapped[Actividad] = relationship(lazy="selectin")
    familia: Mapped[Familia] = relationship(lazy="selectin")
    inscrito_por: Mapped[Usuario | None] = relationship(lazy="selectin")
    participantes: Mapped[list["InscripcionParticipante"]] = relationship(
        back_populates="inscripcion",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="InscripcionParticipante.id",
    )
    
    en_espera_desde: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posicion_espera = None  # no se guarda; la llenan los endpoints antes de responder

    __table_args__ = (
        # Una sola inscripción activa (confirmada o en espera) por familia y actividad;
        # si canceló, puede volver a inscribirse. (Lo crea la migración de lista de espera.)
        Index("uq_inscripcion_activa", "actividad_id", "familia_id", unique=True, postgresql_where=text("estado IN ('CONFIRMADA', 'EN_ESPERA')")),
        Index("ix_inscripciones_actividad_confirmadas", "actividad_id", postgresql_where=text("estado = 'CONFIRMADA'")),
        Index("ix_inscripciones_actividad_espera", "actividad_id", "en_espera_desde", postgresql_where=text("estado = 'EN_ESPERA'")),
    )


class InscripcionParticipante(Base):
    """Una persona de la familia que asiste: un adulto (usuario) o un menor."""

    __tablename__ = "inscripcion_participantes"

    id: Mapped[int] = mapped_column(primary_key=True)
    inscripcion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inscripciones_actividad.id", ondelete="CASCADE"), index=True
    )
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE")
    )
    menor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("familia_menores.id", ondelete="CASCADE")
    )
    asistencia: Mapped[EstadoAsistencia] = mapped_column(
        enum_col(EstadoAsistencia, "estado_asistencia"),
        default=EstadoAsistencia.PENDIENTE,
        server_default=EstadoAsistencia.PENDIENTE.value,
    )

    inscripcion: Mapped[InscripcionActividad] = relationship(back_populates="participantes")
    usuario: Mapped[Usuario | None] = relationship(lazy="selectin")
    menor: Mapped[FamiliaMenor | None] = relationship(lazy="selectin")

    @property
    def tipo(self) -> str:
        return "ADULTO" if self.usuario_id is not None else "MENOR"

    @property
    def nombre(self) -> str:
        persona = self.usuario if self.usuario_id is not None else self.menor
        return persona.nombre if persona is not None else ""

    __table_args__ = (
        # Exactamente uno de los dos: o es adulto o es menor
        CheckConstraint(
            "(usuario_id IS NOT NULL) <> (menor_id IS NOT NULL)",
            name="ck_participante_adulto_o_menor",
        ),
        # La misma persona no puede ir dos veces en la misma inscripción
        UniqueConstraint("inscripcion_id", "usuario_id", name="uq_participante_usuario"),
        UniqueConstraint("inscripcion_id", "menor_id", name="uq_participante_menor"),
    )


# ---------------------------------------------------------------------------
# Actividad.lugares_ocupados: se calcula en cada SELECT de actividades (subconsulta
# correlacionada), así nunca se desfasa aunque se borren familias, menores o usuarios
# por CASCADE. Se define aquí (y no en iniciativas.py) para evitar el import circular.
# ---------------------------------------------------------------------------
Actividad.lugares_ocupados = column_property(
    select(func.count(InscripcionParticipante.id))
    .join(InscripcionActividad, InscripcionParticipante.inscripcion_id == InscripcionActividad.id)
    .where(
        InscripcionActividad.actividad_id == Actividad.id,
        InscripcionActividad.estado == EstadoInscripcion.CONFIRMADA,
    )
    .correlate_except(InscripcionParticipante, InscripcionActividad)
    .scalar_subquery()
)