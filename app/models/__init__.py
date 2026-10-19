# Importar todo aquí registra las tablas en Base.metadata (lo que necesita alembic/env.py)
# y mantiene vigentes imports como `from app.models import Usuario`.
from app.models.catalogo import Categoria, Ciudad, Organizacion
from app.models.notificaciones import DestinoNotificacion, Notificacion, TipoNotificacion
from app.models.enums import (
    AmbitoCategoria,
    EstadoInvitacion,
    EstadoProyecto,
    GrupoEtiqueta,
    ModalidadDonacion,
    Parentesco,
    RolUsuario,
    TipoApoyo,
    TipoCentro,
    TipoIniciativa,
)
from app.models.iniciativas import (
    Actividad,
    Donacion,
    DonacionEtiqueta,
    DonacionOpcion,
    EncuestaActividad,
    Iniciativa,
    IniciativaImagen,
    Proyecto,
    ProyectoOpcionApoyo,
)
from app.models.usuarios import Familia, FamiliaMenor, InvitacionFamilia, MensajeChat, Usuario
from app.models.visiteo import CentroNecesidad, CentroVisiteo



##comunidad
from app.models.comunidad import (
    Publicacion,
    PublicacionImagen,
    PublicacionLike,
    Comentario,
    ComentarioLike,
)
from app.models.enums import TipoPublicacion, EstadoPublicacion, EstadoAsistencia, EstadoInscripcion
from app.models.inscripciones import InscripcionActividad, InscripcionParticipante


__all__ = [
    "Actividad", "AmbitoCategoria", "Categoria", "CentroNecesidad", "CentroVisiteo",
    "Ciudad", "Donacion", "DonacionEtiqueta", "DonacionOpcion", "EncuestaActividad", "EstadoInvitacion",
    "EstadoProyecto", "Familia", "FamiliaMenor", "GrupoEtiqueta", "Iniciativa",
    "IniciativaImagen", "InvitacionFamilia", "MensajeChat", "ModalidadDonacion",
    "Organizacion", "Parentesco", "Proyecto", "ProyectoOpcionApoyo", "RolUsuario",
    "TipoApoyo", "TipoCentro", "TipoIniciativa", "Usuario","Publicacion",
    "PublicacionImagen","PublicacionLike","Comentario","ComentarioLike",
    "TipoPublicacion","EstadoPublicacion",
    "InscripcionActividad", "InscripcionParticipante", "EstadoAsistencia", "EstadoInscripcion", 
    "Notificacion", "TipoNotificacion", "DestinoNotificacion",
]