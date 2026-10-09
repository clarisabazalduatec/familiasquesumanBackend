# Importar todo aquí registra las tablas en Base.metadata (lo que necesita alembic/env.py)
# y mantiene vigentes imports como `from app.models import Usuario`.
from app.models.catalogo import Categoria, Ciudad, Organizacion
from app.models.enums import (
    AmbitoCategoria,
    EstadoProyecto,
    GrupoEtiqueta,
    ModalidadDonacion,
    TipoApoyo,
    TipoCentro,
    TipoIniciativa,
)
from app.models.iniciativas import (
    Actividad,
    Donacion,
    DonacionEtiqueta,
    DonacionOpcion,
    Iniciativa,
    IniciativaImagen,
    Proyecto,
    ProyectoOpcionApoyo,
)
from app.models.usuarios import MensajeChat, Usuario
from app.models.visiteo import CentroNecesidad, CentroVisiteo

__all__ = [
    "Actividad", "AmbitoCategoria", "Categoria", "CentroNecesidad", "CentroVisiteo",
    "Ciudad", "Donacion", "DonacionEtiqueta", "DonacionOpcion", "EstadoProyecto",
    "GrupoEtiqueta", "Iniciativa", "IniciativaImagen", "MensajeChat", "ModalidadDonacion",
    "Organizacion", "Proyecto", "ProyectoOpcionApoyo", "TipoApoyo", "TipoCentro",
    "TipoIniciativa", "Usuario",
]