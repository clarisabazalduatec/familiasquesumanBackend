"""Notificaciones de cada usuario (la campana de la app y los avisos en el celular)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, UniqueConstraint, false, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TipoNotificacion(str, enum.Enum):
    # Usuarios
    PUBLICACION_APROBADA = "PUBLICACION_APROBADA"
    PUBLICACION_RECHAZADA = "PUBLICACION_RECHAZADA"
    NUEVO_COMENTARIO = "NUEVO_COMENTARIO"
    NUEVOS_LIKES = "NUEVOS_LIKES"
    INVITACION_FAMILIA = "INVITACION_FAMILIA"
    AVISO_OFICIAL = "AVISO_OFICIAL"
    RECORDATORIO_ACTIVIDAD = "RECORDATORIO_ACTIVIDAD"
    # Admin
    PUBLICACION_POR_REVISAR = "PUBLICACION_POR_REVISAR"
    ACTIVIDAD_LLENA = "ACTIVIDAD_LLENA"


class DestinoNotificacion(str, enum.Enum):
    """A qué pantalla lleva la notificación al tocarla (la app lo traduce a su ruta)."""
    PUBLICACION = "PUBLICACION"              # detalle de publicación de comunidad (destino_id)
    AVISO = "AVISO"                          # detalle de aviso oficial (destino_id)
    MIS_PUBLICACIONES = "MIS_PUBLICACIONES"  # lista "Mis publicaciones" (ve el motivo de rechazo)
    INVITACIONES = "INVITACIONES"            # invitaciones recibidas
    ACTIVIDAD = "ACTIVIDAD"                  # detalle de actividad (destino_id)
    MODERACION = "MODERACION"                # admin: publicaciones pendientes


class Notificacion(Base):
    __tablename__ = "notificaciones"
    __table_args__ = (
        # "clave" evita duplicados: un solo recordatorio por actividad, un solo aviso de cupo lleno, etc.
        # (las que no llevan clave, NULL, nunca chocan entre sí)
        UniqueConstraint("usuario_id", "clave", name="uq_notificacion_clave"),
        Index("ix_notificaciones_usuario_id_id", "usuario_id", "id"),
    )

    # Id numérico creciente: la app guarda el último que vio y pide "las nuevas" con ?despues_de=
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False
    )
    tipo: Mapped[str] = mapped_column(String(40))
    titulo: Mapped[str] = mapped_column(String(150))
    cuerpo: Mapped[str] = mapped_column(String(500))
    destino_tipo: Mapped[str | None] = mapped_column(String(30))
    destino_id: Mapped[str | None] = mapped_column(String(64))
    clave: Mapped[str | None] = mapped_column(String(120))
    leida: Mapped[bool] = mapped_column(default=False, server_default=false())
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())