from datetime import datetime
import uuid

from app.models.enums import RolUsuario
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.almacen import url_publica

class UsuarioCrear(BaseModel):
    nombre: str
    email: EmailStr
    password: str
    ubicacion: str | None = None


class UsuarioLogin(BaseModel):
    email: EmailStr
    password: str


class UsuarioRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    email: EmailStr
    ubicacion: str | None = None
    rol: RolUsuario = RolUsuario.USUARIO
    foto_url: str | None = None

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


class ChatMensajeEntrada(BaseModel):
    mensaje: str
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


class EncuestaActividadCreate(BaseModel):
    experiencia_general: int
    utilidad_valor: int
    facilidad_participacion: int
    comentarios: Optional[str] = None

class EncuestaActividadOut(EncuestaActividadCreate):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    usuario_id: uuid.UUID
    actividad_id: uuid.UUID
    creado_en: datetime