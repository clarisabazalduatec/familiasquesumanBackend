from datetime import datetime
import uuid

from app.models.enums import RolUsuario
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.almacen import url_publica

from app.schemas_catalogo import CiudadOut

def _password_segura(v: str) -> str:
    # bcrypt solo usa los primeros 72 bytes; más que eso se rechaza en vez de truncarse en silencio
    if len(v.encode("utf-8")) > 72:
        raise ValueError("La contraseña no puede pasar de 72 bytes")
    if v.strip() != v or not v.strip():
        raise ValueError("La contraseña no puede empezar ni terminar con espacios")
    if v.isdigit() or v.isalpha():
        raise ValueError("La contraseña debe combinar letras y números o símbolos")
    return v


class UsuarioCrear(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    email: EmailStr = Field(max_length=255)
    # 8 = el mínimo que ya pide la app; el servidor ahora también lo exige
    password: str = Field(min_length=8, max_length=72)
    ciudad_id: int | None = None

    @field_validator("nombre")
    @classmethod
    def _nombre_limpio(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("El nombre es muy corto")
        return v

    @field_validator("email")
    @classmethod
    def _minusculas(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return _password_segura(v)


class UsuarioLogin(BaseModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=1, max_length=128)  # sin reglas: cuentas viejas pueden tener otras

    @field_validator("email")
    @classmethod
    def _minusculas(cls, v: str) -> str:
        return v.strip().lower()


class CambiarPassword(BaseModel):
    actual: str = Field(min_length=1, max_length=128)
    nueva: str = Field(min_length=8, max_length=72)

    @field_validator("nueva")
    @classmethod
    def _password(cls, v: str) -> str:
        return _password_segura(v)


class UsuarioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    email: EmailStr
    ciudad: CiudadOut | None = None
    rol: RolUsuario = RolUsuario.USUARIO
    foto_url: str | None = None
    correo_verificado: bool = False

    @field_validator("foto_url")
    @classmethod
    def _foto_publica(cls, v):
        return url_publica(v)


class TokenRespuesta(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioRespuesta


class ChatTurno(BaseModel):
    """Un mensaje anterior de la conversación que está en pantalla."""
    rol: Literal["usuario", "asistente"]
    contenido: str = Field(max_length=4000)
    # Los turnos "asistente" deben traer la firma que regresó el backend con esa respuesta;
    # así el cliente no puede inventar respuestas del asistente (prompt injection).
    firma: str | None = Field(default=None, max_length=128)


class ChatMensajeEntrada(BaseModel):
    mensaje: str = Field(max_length=1000)
    # La app manda los mensajes que hay en pantalla; el backend no guarda conversaciones.
    historial: list[ChatTurno] = Field(default_factory=list, max_length=40)

class ChatEnlace(BaseModel):
    """Botón que la app muestra bajo la respuesta para abrir el detalle de una iniciativa."""
    tipo: Literal["actividad", "proyecto", "donacion", "centro"]
    id: str
    titulo: str


class ChatMensajeRespuesta(BaseModel):
    respuesta: str
    enlaces: list[ChatEnlace] = []
    # La app la guarda junto a la respuesta y la regresa en el historial
    firma: str | None = None


class EncuestaActividadCreate(BaseModel):
    experiencia_general: int = Field(ge=1, le=5)
    utilidad_valor: int = Field(ge=1, le=5)
    facilidad_participacion: int = Field(ge=1, le=5)
    comentarios: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("comentarios", mode="before")
    @classmethod
    def _vacio_es_null(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v

class EncuestaActividadOut(EncuestaActividadCreate):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    usuario_id: uuid.UUID
    actividad_id: uuid.UUID
    creado_en: datetime