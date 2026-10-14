"""Invitaciones que el usuario RECIBIÓ (las enviadas viven en /familias/mia/invitaciones)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import EstadoInvitacion, Familia, InvitacionFamilia, Usuario
from app.routers.familias import _familia_completa
from app.schemas_familia import FamiliaOut, InvitacionRecibidaOut
from app.security import obtener_usuario_actual

router = APIRouter(prefix="/invitaciones", tags=["familia"])


async def _invitacion_pendiente_para_mi(
    db: AsyncSession, usuario: Usuario, invitacion_id: uuid.UUID
) -> InvitacionFamilia:
    invitacion = (
        await db.execute(
            select(InvitacionFamilia)
            .where(InvitacionFamilia.id == invitacion_id, InvitacionFamilia.invitado_id == usuario.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if invitacion is None:
        raise HTTPException(status_code=404, detail="Invitación no encontrada")
    if invitacion.estado != EstadoInvitacion.PENDIENTE:
        raise HTTPException(status_code=409, detail="Esa invitación ya no está pendiente")
    return invitacion


@router.get("", response_model=list[InvitacionRecibidaOut])
async def mis_invitaciones(
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    """Invitaciones pendientes que me han hecho."""
    stmt = (
        select(InvitacionFamilia)
        .where(
            InvitacionFamilia.invitado_id == usuario.id,
            InvitacionFamilia.estado == EstadoInvitacion.PENDIENTE,
        )
        .options(selectinload(InvitacionFamilia.familia), selectinload(InvitacionFamilia.invitado_por))
        .order_by(InvitacionFamilia.creado_en.desc())
    )
    return (await db.execute(stmt)).scalars().all()


@router.post("/{invitacion_id}/aceptar", response_model=FamiliaOut)
async def aceptar_invitacion(
    invitacion_id: uuid.UUID,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    invitacion = await _invitacion_pendiente_para_mi(db, usuario, invitacion_id)

    # Bloquea la familia: si en este momento su último adulto se está saliendo,
    # esperamos y luego comprobamos si la familia todavía existe.
    familia_id = await db.scalar(
        select(Familia.id).where(Familia.id == invitacion.familia_id).with_for_update()
    )
    if familia_id is None:
        raise HTTPException(status_code=409, detail="Esa familia ya no existe")

    # Releer al usuario bloqueado, por si aceptó otra invitación al mismo tiempo.
    yo = (
        await db.execute(
            select(Usuario).where(Usuario.id == usuario.id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one()
    if yo.familia_id is not None:
        raise HTTPException(status_code=409, detail="Ya perteneces a una familia; sal de ella para aceptar")

    yo.familia_id = familia_id
    invitacion.estado = EstadoInvitacion.ACEPTADA
    invitacion.respondida_en = func.now()
    await db.commit()
    return await _familia_completa(db, familia_id)


@router.post("/{invitacion_id}/rechazar", status_code=status.HTTP_204_NO_CONTENT)
async def rechazar_invitacion(
    invitacion_id: uuid.UUID,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    invitacion = await _invitacion_pendiente_para_mi(db, usuario, invitacion_id)
    invitacion.estado = EstadoInvitacion.RECHAZADA
    invitacion.respondida_en = func.now()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)