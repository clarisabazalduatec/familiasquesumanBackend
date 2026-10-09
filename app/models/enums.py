import enum

from sqlalchemy import Enum


class TipoIniciativa(str, enum.Enum):
    ACTIVIDAD = "ACTIVIDAD"
    PROYECTO = "PROYECTO"
    DONACION = "DONACION"


class EstadoProyecto(str, enum.Enum):
    ACTIVO = "ACTIVO"
    ANTERIOR = "ANTERIOR"


class ModalidadDonacion(str, enum.Enum):
    CAMPANA = "CAMPANA"
    ESPECIE = "ESPECIE"


class TipoApoyo(str, enum.Enum):
    TIEMPO_TALENTO = "TIEMPO_TALENTO"
    APORTACION_ECONOMICA = "APORTACION_ECONOMICA"
    MATERIAL = "MATERIAL"


class TipoCentro(str, enum.Enum):
    ASILO = "ASILO"
    CASA_HOGAR = "CASA_HOGAR"
    COMEDOR = "COMEDOR"


class AmbitoCategoria(str, enum.Enum):
    ACTIVIDAD = "ACTIVIDAD"
    DONACION = "DONACION"
    PUBLICACION = "PUBLICACION"


class GrupoEtiqueta(str, enum.Enum):
    ARTICULO = "ARTICULO"
    DESTINATARIO = "DESTINATARIO"
    CONDICION = "CONDICION"
    METODO_ENTREGA = "METODO_ENTREGA"


def enum_col(enum_cls: type[enum.Enum], nombre: str) -> Enum:
    """Enum guardado como VARCHAR + CHECK (no como tipo nativo de Postgres).

    Ventaja: agregar un valor nuevo es un cambio simple de migración,
    sin ALTER TYPE ni DROP TYPE manuales en el downgrade.
    """
    return Enum(
        enum_cls,
        name=nombre,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=30,
    )