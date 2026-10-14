import uuid
from pydantic import BaseModel, EmailStr, ConfigDict

from app.models.enums import RolUsuario


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


class ChatMensajeEntrada(BaseModel):
    mensaje: str


class ChatMensajeRespuesta(BaseModel):
    respuesta: str