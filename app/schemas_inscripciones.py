import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import EstadoAsistencia, EstadoInscripcion
from app.schemas_catalogo import ActividadResumen
from app.schemas_familia import UsuarioBreve


class _Salida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Entrada ----------
class InscripcionGuardar(BaseModel):
    """Quiénes de la familia van. Sirve para inscribirse (POST) y para cambiar participantes (PUT)."""

    usuario_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    menor_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    lista_espera: bool = False

    @model_validator(mode="after")
    def _validar(self):
        if not self.usuario_ids and not self.menor_ids:
            raise ValueError("Selecciona al menos a una persona")
        if len(set(self.usuario_ids)) != len(self.usuario_ids) or len(set(self.menor_ids)) != len(self.menor_ids):
            raise ValueError("Hay personas repetidas")
        return self

    @property
    def total(self) -> int:
        return len(self.usuario_ids) + len(self.menor_ids)


class AsistenciaItem(BaseModel):
    participante_id: int
    asistencia: EstadoAsistencia


class AsistenciaGuardar(BaseModel):
    items: list[AsistenciaItem] = Field(min_length=1, max_length=500)


# ---------- Salida ----------
class ParticipanteOut(_Salida):
    id: int
    tipo: Literal["ADULTO", "MENOR"]
    usuario_id: uuid.UUID | None = None
    menor_id: uuid.UUID | None = None
    nombre: str
    asistencia: EstadoAsistencia


class InscripcionOut(_Salida):
    id: uuid.UUID
    actividad_id: uuid.UUID
    familia_id: uuid.UUID
    estado: EstadoInscripcion
    creado_en: datetime
    cancelada_en: datetime | None = None
    participantes: list[ParticipanteOut]
    posicion_espera: int | None = None


class MiInscripcionOut(InscripcionOut):
    """Para "Mis actividades": la inscripción con los datos de la actividad."""
    actividad: ActividadResumen


class FamiliaBreve(_Salida):
    id: uuid.UUID
    nombre: str | None = None


class InscripcionAdminOut(InscripcionOut):
    familia: FamiliaBreve
    inscrito_por: UsuarioBreve | None = None