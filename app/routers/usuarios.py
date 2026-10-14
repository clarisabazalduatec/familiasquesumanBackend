from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Usuario
from app.schemas_familia import PerfilActualizar, PerfilOut
from app.security import obtener_usuario_actual

router = APIRouter(prefix="/usuarios", tags=["perfil"])


@router.get("/me", response_model=PerfilOut)
async def mi_perfil(usuario: Usuario = Depends(obtener_usuario_actual)):
    return usuario


@router.patch("/me", response_model=PerfilOut)
async def actualizar_mi_perfil(
    datos: PerfilActualizar,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    # exclude_unset: solo cambia lo que la app mandó. Mandar "ubicacion": null sí la borra.
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        if campo == "nombre" and valor is None:
            continue  # el nombre es obligatorio, no se puede borrar
        setattr(usuario, campo, valor)
    await db.commit()
    await db.refresh(usuario)
    return usuario