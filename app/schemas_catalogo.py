"""Esquemas de salida (lo que la app Android recibe) para el catálogo."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    AmbitoCategoria,
    EstadoProyecto,
    ModalidadDonacion,
    TipoApoyo,
    TipoCentro,
    TipoIniciativa,
)

from app.almacen import url_publica

class _Salida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Catálogos ----------
class CiudadOut(_Salida):
    id: int
    nombre: str
    estado: str


class CategoriaOut(_Salida):
    id: int
    ambito: AmbitoCategoria
    nombre: str


class OrganizacionOut(_Salida):
    id: uuid.UUID
    nombre: str
    logo_url: str | None = None
    verificada: bool

    @field_validator("logo_url")
    @classmethod
    def _logo(cls, v):
        return url_publica(v)


# ---------- Base común de iniciativas ----------
class _IniciativaResumen(_Salida):
    id: uuid.UUID
    tipo: TipoIniciativa
    titulo: str
    descripcion_corta: str
    ubicacion: str | None = None
    ciudad: CiudadOut
    organizacion: OrganizacionOut | None = None
    imagenes: list[str] = []

    @field_validator("imagenes", mode="before")
    @classmethod
    def _solo_urls(cls, v):
        return [url_publica(i.url if hasattr(i, "url") else i) for i in v]


# ---------- Actividades ----------
class ActividadResumen(_IniciativaResumen):
    categoria: CategoriaOut
    inicia_en: datetime
    termina_en: datetime
    cupo_total: int
    plazas_disponibles: int


class ActividadDetalle(ActividadResumen):
    acerca_de: str | None = None


# ---------- Proyectos ----------
class OpcionApoyoOut(_Salida):
    tipo: TipoApoyo
    titulo: str
    descripcion: str


class ProyectoResumen(_IniciativaResumen):
    estado: EstadoProyecto
    beneficiarios: str
    logo_url: str | None = Field(default=None, validation_alias="logo")

    @field_validator("logo_url")
    @classmethod
    def _logo(cls, v):
        return url_publica(v)


class ProyectoDetalle(ProyectoResumen):
    acerca_de: str | None = None
    descripcion_larga: str | None = None
    whatsapp: str | None = None
    telefono: str | None = None
    opciones_apoyo: list[OpcionApoyoOut] = []
    como_ayudar: str | None = None
    instagram_url: str | None = None


# ---------- Donaciones ----------
class DonacionOpcionOut(_Salida):
    titulo: str
    monto: float


class DonacionResumen(_IniciativaResumen):
    modalidad: ModalidadDonacion
    categoria: CategoriaOut | None = None
    meta: float | None = None
    recaudado: float
    opciones_disponibles: int


class DonacionDetalle(DonacionResumen):
    descripcion_larga: str | None = None
    whatsapp: str | None = None
    condiciones_recepcion: str | None = None
    opciones: list[DonacionOpcionOut] = []
    # {"articulo": [...], "destinatario": [...], "condicion": [...], "metodo_entrega": [...]}
    etiquetas: dict[str, list[str]] = Field(default_factory=dict, validation_alias="etiquetas_agrupadas")


# ---------- Directorio de visiteo ----------
class CentroResumen(_Salida):
    id: uuid.UUID
    tipo: TipoCentro
    nombre: str
    descripcion_corta: str
    direccion: str
    ciudad: CiudadOut
    logo_url: str | None = None
    verificado: bool

    @field_validator("logo_url")
    @classmethod
    def _logo(cls, v):
        return url_publica(v)


class CentroDetalle(CentroResumen):
    informacion_general: str
    necesidades: list[str] = []
    como_ayudar: str | None = None
    recomendaciones: str | None = None
    telefono: str | None = None
    whatsapp: str | None = None

    @field_validator("necesidades", mode="before")
    @classmethod
    def _solo_texto(cls, v):
        return [n.descripcion if hasattr(n, "descripcion") else n for n in v]



# ---------- Entrada del admin ----------
class OpcionApoyoIn(BaseModel):
    tipo: TipoApoyo = TipoApoyo.TIEMPO_TALENTO  # la app ya no lo pide; se queda por compatibilidad
    titulo: str = Field(min_length=1, max_length=200)
    descripcion: str = Field(default="", max_length=2000)


class ProyectoGuardar(BaseModel):
    """Crear (POST) o reemplazar (PUT) un proyecto completo desde el formulario de admin.

    estado ACTIVO -> pestaña "Proyectos activos"; ANTERIOR -> "Proyectos anteriores".
    """

    titulo: str = Field(min_length=1, max_length=160)
    descripcion_corta: str = Field(min_length=1, max_length=300)
    beneficiarios: str = Field(min_length=1, max_length=120)
    estado: EstadoProyecto = EstadoProyecto.ACTIVO
    ubicacion: str | None = Field(default=None, max_length=200)
    ciudad_id: int | None = None  # None = Monterrey
    acerca_de: str | None = None
    descripcion_larga: str | None = None
    como_ayudar: str | None = None
    instagram_url: str | None = Field(default=None, max_length=300)
    whatsapp: str | None = Field(default=None, max_length=20)
    telefono: str | None = Field(default=None, max_length=20)
    logo_url: str | None = Field(default=None, max_length=500)
    imagenes: list[str] = Field(default_factory=list, max_length=10)
    opciones_apoyo: list[OpcionApoyoIn] = Field(default_factory=list, max_length=10)

    @field_validator(
        "ubicacion", "acerca_de", "descripcion_larga", "como_ayudar",
        "instagram_url", "whatsapp", "telefono", "logo_url", mode="before",
    )
    @classmethod
    def _vacio_es_null(cls, v):
        # "" o "   " desde la app = campo vacío
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v