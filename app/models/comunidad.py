
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import EstadoPublicacion, TipoPublicacion, enum_col


class Publicacion(Base):
    """Publicaciones de Comunidad y Avisos Oficiales."""

    __tablename__ = "publicaciones"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    tipo: Mapped[TipoPublicacion] = mapped_column(
        enum_col(TipoPublicacion, "tipo_publicacion"),
        nullable=False
    )

    autor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("usuarios.id"), nullable=False, index=True
    )

    titulo: Mapped[str | None] = mapped_column(String(200))
    contenido: Mapped[str] = mapped_column(Text, nullable=False)

    categoria_id: Mapped[int | None] = mapped_column(
        ForeignKey("categorias.id", ondelete="SET NULL")
    )

    ubicacion: Mapped[str | None] = mapped_column(String(250))

    estado: Mapped[EstadoPublicacion] = mapped_column(
        enum_col(EstadoPublicacion, "estado_publicacion"),
        default=EstadoPublicacion.PENDIENTE,
        server_default=EstadoPublicacion.PENDIENTE.value,
        nullable=False
    )

    motivo_rechazo: Mapped[str | None] = mapped_column(Text)

    revisado_por: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL")
    )

    revisado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    publicada_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    # Información opcional de Avisos Oficiales

    evento_inicia_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    evento_termina_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    publico_objetivo: Mapped[str | None] = mapped_column(String(200))

    documento_url: Mapped[str | None] = mapped_column(String(500))
    documento_nombre: Mapped[str | None] = mapped_column(String(255))

    # Relaciones

    autor = relationship(
        "Usuario",
        foreign_keys=[autor_id],
        lazy="selectin"
    )

    revisor = relationship(
        "Usuario",
        foreign_keys=[revisado_por],
        lazy="selectin"
    )

    categoria = relationship("Categoria", lazy="selectin")

    imagenes: Mapped[list["PublicacionImagen"]] = relationship(
        back_populates="publicacion",
        cascade="all, delete-orphan",
        order_by="PublicacionImagen.orden",
        lazy="selectin"
    )

    comentarios: Mapped[list["Comentario"]] = relationship(
        back_populates="publicacion",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    likes: Mapped[list["PublicacionLike"]] = relationship(
        back_populates="publicacion",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(contenido)) > 0",
            name="ck_publicaciones_contenido"
        ),
        Index(
            "ix_publicaciones_tipo_estado",
            "tipo", "estado"
        ),
    )


class PublicacionImagen(Base):
    """Imágenes adjuntas a una publicación."""

    __tablename__ = "publicacion_imagenes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    publicacion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publicaciones.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    url: Mapped[str] = mapped_column(String(500), nullable=False)
    orden: Mapped[int] = mapped_column(Integer, default=0)

    publicacion: Mapped["Publicacion"] = relationship(
        back_populates="imagenes"
    )


class PublicacionLike(Base):
    """Registra qué usuario dio like a cada publicación."""

    __tablename__ = "publicacion_likes"

    publicacion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publicaciones.id", ondelete="CASCADE"),
        primary_key=True
    )

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        primary_key=True
    )

    publicacion: Mapped["Publicacion"] = relationship(
        back_populates="likes"
    )


class Comentario(Base):
    """Comentarios asociados a publicaciones de Comunidad."""

    __tablename__ = "comentarios"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    publicacion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publicaciones.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    autor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("usuarios.id"),
        nullable=False
    )

    contenido: Mapped[str] = mapped_column(Text, nullable=False)

    visible: Mapped[bool] = mapped_column(
        default=True,
        server_default=true()
    )

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    publicacion: Mapped["Publicacion"] = relationship(
        back_populates="comentarios"
    )

    autor = relationship("Usuario", lazy="selectin")

    likes: Mapped[list["ComentarioLike"]] = relationship(
        back_populates="comentario",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(contenido)) > 0",
            name="ck_comentarios_contenido"
        ),
    )


class ComentarioLike(Base):
    """Registra qué usuario dio like a cada comentario."""

    __tablename__ = "comentario_likes"

    comentario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comentarios.id", ondelete="CASCADE"),
        primary_key=True
    )

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        primary_key=True
    )

    comentario: Mapped["Comentario"] = relationship(
        back_populates="likes"
    )
