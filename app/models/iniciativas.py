import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.catalogo import Categoria, Ciudad, Organizacion
from app.models.enums import (
    EstadoProyecto,
    GrupoEtiqueta,
    ModalidadDonacion,
    TipoApoyo,
    TipoIniciativa,
    enum_col,
)


class Iniciativa(Base):
    """Supertipo: campos comunes a actividades, proyectos y donaciones."""

    __tablename__ = "iniciativas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tipo: Mapped[TipoIniciativa] = mapped_column(enum_col(TipoIniciativa, "tipo_iniciativa"))
    titulo: Mapped[str] = mapped_column(String(160))
    descripcion_corta: Mapped[str] = mapped_column(String(300))
    ubicacion: Mapped[str | None] = mapped_column(String(200))
    ciudad_id: Mapped[int] = mapped_column(ForeignKey("ciudades.id"))
    organizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizaciones.id", ondelete="SET NULL")
    )
    activa: Mapped[bool] = mapped_column(default=True, server_default=true())
    creado_por: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL")
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # lazy="selectin": necesario en SQLAlchemy async (no hay lazy loading implícito)
    ciudad: Mapped[Ciudad] = relationship(lazy="selectin")
    organizacion: Mapped[Organizacion | None] = relationship(lazy="selectin")
    imagenes: Mapped[list["IniciativaImagen"]] = relationship(
        back_populates="iniciativa",
        cascade="all, delete-orphan",
        order_by="IniciativaImagen.orden",
        lazy="selectin",
    )

    __table_args__ = (Index("ix_iniciativas_ciudad_tipo_activa", "ciudad_id", "tipo", "activa"),)
    # with_polymorphic="*": al consultar Iniciativa se traen también las columnas de los subtipos
    __mapper_args__ = {"polymorphic_on": "tipo", "with_polymorphic": "*"}


class Actividad(Iniciativa):
    __tablename__ = "actividades"

    id: Mapped[uuid.UUID] = mapped_column(
        "iniciativa_id", ForeignKey("iniciativas.id", ondelete="CASCADE"), primary_key=True
    )
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"))
    inicia_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    termina_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cupo_total: Mapped[int]
    acerca_de: Mapped[str | None] = mapped_column(Text)

    categoria: Mapped[Categoria] = relationship(lazy="selectin")

    __table_args__ = (
        CheckConstraint("cupo_total > 0", name="ck_actividades_cupo_positivo"),
        CheckConstraint("termina_en > inicia_en", name="ck_actividades_fechas"),
    )
    __mapper_args__ = {"polymorphic_identity": TipoIniciativa.ACTIVIDAD}


class Proyecto(Iniciativa):
    __tablename__ = "proyectos"

    id: Mapped[uuid.UUID] = mapped_column(
        "iniciativa_id", ForeignKey("iniciativas.id", ondelete="CASCADE"), primary_key=True
    )
    estado: Mapped[EstadoProyecto] = mapped_column(
        enum_col(EstadoProyecto, "estado_proyecto"), default=EstadoProyecto.ACTIVO
    )
    beneficiarios: Mapped[str] = mapped_column(String(120))  # "25 Mujeres", "200 adultos mayores"
    acerca_de: Mapped[str | None] = mapped_column(Text)
    descripcion_larga: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    whatsapp: Mapped[str | None] = mapped_column(String(20))
    telefono: Mapped[str | None] = mapped_column(String(20))

    opciones_apoyo: Mapped[list["ProyectoOpcionApoyo"]] = relationship(
        cascade="all, delete-orphan", order_by="ProyectoOpcionApoyo.id", lazy="selectin"
    )

    __mapper_args__ = {"polymorphic_identity": TipoIniciativa.PROYECTO}


class Donacion(Iniciativa):
    __tablename__ = "donaciones"

    id: Mapped[uuid.UUID] = mapped_column(
        "iniciativa_id", ForeignKey("iniciativas.id", ondelete="CASCADE"), primary_key=True
    )
    modalidad: Mapped[ModalidadDonacion] = mapped_column(
        enum_col(ModalidadDonacion, "modalidad_donacion")
    )
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id"))
    meta: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    descripcion_larga: Mapped[str | None] = mapped_column(Text)
    whatsapp: Mapped[str | None] = mapped_column(String(20))
    # Para ESPECIE la dirección del centro de acopio va en iniciativas.ubicacion
    condiciones_recepcion: Mapped[str | None] = mapped_column(Text)

    categoria: Mapped[Categoria | None] = relationship(lazy="selectin")
    opciones: Mapped[list["DonacionOpcion"]] = relationship(
        cascade="all, delete-orphan", order_by="DonacionOpcion.id", lazy="selectin"
    )
    etiquetas: Mapped[list["DonacionEtiqueta"]] = relationship(
        cascade="all, delete-orphan", order_by="DonacionEtiqueta.id", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("meta IS NULL OR meta >= 0", name="ck_donaciones_meta_no_negativa"),
    )
    __mapper_args__ = {"polymorphic_identity": TipoIniciativa.DONACION}


class ProyectoOpcionApoyo(Base):
    __tablename__ = "proyecto_opciones_apoyo"

    id: Mapped[int] = mapped_column(primary_key=True)
    proyecto_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("proyectos.iniciativa_id", ondelete="CASCADE"), index=True
    )
    tipo: Mapped[TipoApoyo] = mapped_column(enum_col(TipoApoyo, "tipo_apoyo"))
    titulo: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str] = mapped_column(Text)


class DonacionOpcion(Base):
    """Montos sugeridos de una campaña: 'Despensa básica — $350'."""

    __tablename__ = "donacion_opciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    donacion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("donaciones.iniciativa_id", ondelete="CASCADE"), index=True
    )
    titulo: Mapped[str] = mapped_column(String(160))
    monto: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class DonacionEtiqueta(Base):
    """Listas cortas de una donación en especie (artículos, destinatarios, condiciones, entrega)."""

    __tablename__ = "donacion_etiquetas"

    id: Mapped[int] = mapped_column(primary_key=True)
    donacion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("donaciones.iniciativa_id", ondelete="CASCADE"), index=True
    )
    grupo: Mapped[GrupoEtiqueta] = mapped_column(enum_col(GrupoEtiqueta, "grupo_etiqueta"))
    valor: Mapped[str] = mapped_column(String(80))

    __table_args__ = (UniqueConstraint("donacion_id", "grupo", "valor", name="uq_donacion_etiqueta"),)


class IniciativaImagen(Base):
    __tablename__ = "iniciativa_imagenes"

    id: Mapped[int] = mapped_column(primary_key=True)
    iniciativa_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("iniciativas.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(500))
    orden: Mapped[int] = mapped_column(default=0, server_default="0")

    iniciativa: Mapped[Iniciativa] = relationship(back_populates="imagenes")