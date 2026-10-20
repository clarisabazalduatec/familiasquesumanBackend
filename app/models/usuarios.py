import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import EstadoInvitacion, Parentesco, RolUsuario, enum_col
from app.models.catalogo import Ciudad 

class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    
    ciudad_id: Mapped[int | None] = mapped_column(ForeignKey("ciudades.id"), index=True)
    ciudad: Mapped[Ciudad | None] = relationship(lazy="selectin")
    
    # Clave del almacén ("abc.jpg"); la API la devuelve como "/imagenes/abc.jpg". None = sin foto.
    foto_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # USUARIO o ADMIN. Los admins se asignan a mano por SQL.
    rol: Mapped[RolUsuario] = mapped_column(
        enum_col(RolUsuario, "rol_usuario"),
        default=RolUsuario.USUARIO,
        server_default=RolUsuario.USUARIO.value,
    )

    # Un usuario pertenece a una sola familia (o a ninguna todavía).
    familia_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("familias.id", ondelete="SET NULL"), index=True
    )
    parentesco: Mapped[Parentesco | None] = mapped_column(enum_col(Parentesco, "parentesco"))

    familia: Mapped["Familia | None"] = relationship(back_populates="adultos")
    mensajes: Mapped[list["MensajeChat"]] = relationship(back_populates="usuario")


class Familia(Base):
    """Agrupa adultos (usuarios con cuenta) y menores (sin cuenta).

    Regla de negocio (se aplica en el router, no en la base de datos): nunca queda
    una familia sin adultos. Cuando sale el último adulto se borra la familia, y por
    CASCADE se van sus menores e invitaciones.
    """

    __tablename__ = "familias"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str | None] = mapped_column(String(120))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    adultos: Mapped[list["Usuario"]] = relationship(back_populates="familia")
    menores: Mapped[list["FamiliaMenor"]] = relationship(
        back_populates="familia", cascade="all, delete-orphan", passive_deletes=True
    )
    invitaciones: Mapped[list["InvitacionFamilia"]] = relationship(
        back_populates="familia", cascade="all, delete-orphan", passive_deletes=True
    )


class FamiliaMenor(Base):
    """Niños de la familia. No son usuarios: no tienen cuenta ni inician sesión."""

    __tablename__ = "familia_menores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    familia_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("familias.id", ondelete="CASCADE"), index=True
    )
    nombre: Mapped[str] = mapped_column(String(120))
    fecha_nacimiento: Mapped[date] = mapped_column(Date)
    registrado_por_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    familia: Mapped["Familia"] = relationship(back_populates="menores")


class InvitacionFamilia(Base):
    """Invitación de un adulto de la familia a otro usuario (que ya tiene cuenta)."""

    __tablename__ = "invitaciones_familia"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    familia_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("familias.id", ondelete="CASCADE"), index=True
    )
    invitado_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), index=True
    )
    invitado_por_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    estado: Mapped[EstadoInvitacion] = mapped_column(
        enum_col(EstadoInvitacion, "estado_invitacion"),
        default=EstadoInvitacion.PENDIENTE,
        server_default=EstadoInvitacion.PENDIENTE.value,
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    respondida_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    familia: Mapped["Familia"] = relationship(back_populates="invitaciones")
    invitado: Mapped["Usuario"] = relationship(foreign_keys=[invitado_id])
    invitado_por: Mapped["Usuario | None"] = relationship(foreign_keys=[invitado_por_id])

    __table_args__ = (
        # Solo una invitación PENDIENTE a la misma persona para la misma familia.
        # Las ya respondidas no cuentan, así se puede volver a invitar a alguien que rechazó.
        Index(
            "uq_invitacion_pendiente",
            "familia_id",
            "invitado_id",
            unique=True,
            postgresql_where=text("estado = 'PENDIENTE'"),
        ),
    )


class MensajeChat(Base):
    __tablename__ = "mensajes_chat"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    rol: Mapped[str] = mapped_column(String(20), nullable=False)  # "usuario" o "asistente"
    contenido: Mapped[str] = mapped_column(Text, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    usuario: Mapped["Usuario"] = relationship(back_populates="mensajes")

    __table_args__ = (Index("ix_mensajes_chat_usuario_creado", "usuario_id", "creado_en"),)