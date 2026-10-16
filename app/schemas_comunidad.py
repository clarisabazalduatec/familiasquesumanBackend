import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.models.enums import EstadoPublicacion, TipoPublicacion
from app.schemas_catalogo import CategoriaOut
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.almacen import url_publica

## base comun

class _Salida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class _Entrada(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

class AutorPublicacion(_Salida):
    id: uuid.UUID
    nombre: str
    foto_url: str | None = None

    @field_validator("foto_url")
    @classmethod
    def _foto_publica(cls, v):
        return url_publica(v)


class ImagenPublicacion(_Salida):
    id: uuid.UUID
    url: str
    orden: int

    @field_validator("url")
    @classmethod
    def _url_publica(cls, v):
        # En la base se guarda la clave del almacén ("abc.jpg"); la app necesita "/imagenes/abc.jpg"
        return url_publica(v)

## crear publicaciones

##usuarios
class PublicacionCrear(_Entrada):
    titulo: str = Field(min_length=1, max_length=200)
    contenido: str = Field(min_length=1, max_length=5000)
    categoria_id: int | None = None
    ubicacion: str | None = Field(default=None, max_length=250)
    imagenes: list[str] = Field(default_factory=list, max_length=10)

##administrador
class AvisoOficialCrear(_Entrada):
    contenido: str = Field(min_length=1, max_length=5000)
    titulo: str | None = Field(default=None, max_length=200)
    evento_inicia_en: datetime | None = None
    evento_termina_en: datetime | None = None
    publico_objetivo: str | None = Field(default=None, max_length=200)
    imagenes: list[str] = Field(default_factory=list, max_length=10)
    documento_url: str | None = Field(default=None, max_length=500)
    documento_nombre: str | None = Field(default=None, max_length=255)


## consultar publicaciones
class PublicacionResumen(_Salida):
    id: uuid.UUID
    tipo: TipoPublicacion
    titulo: str | None = None
    contenido: str
    ubicacion: str | None = None
    estado: EstadoPublicacion
    autor: AutorPublicacion
    categoria: CategoriaOut | None = None
    imagenes: list[ImagenPublicacion] = Field(default_factory=list)
    creado_en: datetime
    publicada_en: datetime | None = None
    evento_inicia_en: datetime | None = None
    evento_termina_en: datetime | None = None
    publico_objetivo: str | None = None
    documento_url: str | None = None
    documento_nombre: str | None = None
    total_likes: int = 0
    total_comentarios: int = 0
    me_gusta: bool = False

class PublicacionDetalle(PublicacionResumen):
    motivo_rechazo: str | None = None
    revisado_en: datetime | None = None
    total_likes: int = 0
    total_comentarios: int = 0
    me_gusta: bool = False


##moderacion 
class PublicacionRechazar(_Entrada):
    motivo_rechazo: str = Field(min_length=1, max_length=2000)

##comentarios
class ComentarioCrear(_Entrada):
    contenido: str = Field(min_length=1, max_length=2000)
class ComentarioRespuesta(_Salida):
    id: uuid.UUID
    publicacion_id: uuid.UUID
    contenido: str
    creado_en: datetime
    autor: AutorPublicacion
    total_likes: int = 0
    me_gusta: bool = False
