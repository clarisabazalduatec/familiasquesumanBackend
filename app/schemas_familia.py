"""Esquemas de perfil, familia e invitaciones."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.models.enums import EstadoInvitacion, Parentesco, RolUsuario


class _Salida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Perfil del usuario ----------
class PerfilOut(_Salida):
    id: uuid.UUID
    nombre: str
    email: EmailStr
    ubicacion: str | None = None
    rol: RolUsuario
    parentesco: Parentesco | None = None
    familia_id: uuid.UUID | None = None


class PerfilActualizar(BaseModel):
    """Todos opcionales: solo se cambian los campos que se manden."""

    nombre: str | None = Field(None, min_length=1, max_length=120)
    ubicacion: str | None = Field(None, max_length=120)
    parentesco: Parentesco | None = None


# ---------- Menores ----------
class MenorCrear(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    fecha_nacimiento: date  # "AAAA-MM-DD"


class MenorActualizar(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=120)
    fecha_nacimiento: date | None = None


class MenorOut(_Salida):
    id: uuid.UUID
    nombre: str
    fecha_nacimiento: date

    @computed_field
    @property
    def edad(self) -> int:
        hoy = date.today()
        cumplio = (hoy.month, hoy.day) >= (self.fecha_nacimiento.month, self.fecha_nacimiento.day)
        return hoy.year - self.fecha_nacimiento.year - (0 if cumplio else 1)


# ---------- Familia ----------
class FamiliaCrear(BaseModel):
    nombre: str | None = Field(None, max_length=120)
    parentesco: Parentesco | None = None  # el parentesco de quien la crea


class FamiliaActualizar(BaseModel):
    nombre: str | None = Field(None, max_length=120)


class MiembroOut(_Salida):
    id: uuid.UUID
    nombre: str
    email: EmailStr
    parentesco: Parentesco | None = None


class UsuarioBreve(_Salida):
    id: uuid.UUID
    nombre: str
    email: EmailStr


class InvitacionEnviadaOut(_Salida):
    id: uuid.UUID
    invitado: UsuarioBreve
    estado: EstadoInvitacion
    creado_en: datetime


class FamiliaOut(_Salida):
    id: uuid.UUID
    nombre: str | None = None
    creado_en: datetime
    adultos: list[MiembroOut]
    menores: list[MenorOut]
    invitaciones_pendientes: list[InvitacionEnviadaOut]


# ---------- Invitaciones ----------
class InvitacionCrear(BaseModel):
    email: EmailStr


class FamiliaBreve(_Salida):
    id: uuid.UUID
    nombre: str | None = None


class InvitacionRecibidaOut(_Salida):
    id: uuid.UUID
    familia: FamiliaBreve
    invitado_por: UsuarioBreve | None = None  # None si quien invitó ya borró su cuenta
    estado: EstadoInvitacion
    creado_en: datetime