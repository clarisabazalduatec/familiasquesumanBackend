import uuid

from app.models.enums import RolUsuario
from typing import Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field

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