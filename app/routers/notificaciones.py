"""Notificaciones del usuario con sesión.

La app las consulta:
  - al abrirse / al volver a primer plano (campana y número de no leídas),
  - desde WorkManager cada ~15 min con ?despues_de=<último id visto> para mostrar
    notificaciones locales en el celular aunque la app esté cerrada.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Notificacion, Usuario
from app.notificaciones_servicio import generar_recordatorios
from app.security import obtener_usuario_actual

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


class NotificacionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    titulo: str
    cuerpo: str
    destino_tipo: str | None = None
    destino_id: str | None = None
    leida: bool
    creado_en: datetime


class ResumenNotificaciones(BaseModel):
    no_leidas: int
    ultimo_id: int | None = None  # el id más reciente (la app lo compara con su cursor)


@router.get("", response_model=list[NotificacionOut])
async def mis_notificaciones(
    despues_de: int | None = Query(None, ge=0, description="Solo las más nuevas que este id (orden ascendente)"),
    limit: int = Query(50, ge=1, le=100),
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    await generar_recordatorios(db, usuario)
    stmt = select(Notificacion).where(Notificacion.usuario_id == usuario.id)
    if despues_de is not None:
        # Para WorkManager: de la más vieja a la más nueva, así el cursor avanza en orden
        stmt = stmt.where(Notificacion.id > despues_de).order_by(Notificacion.id)
    else:
        # Para la pantalla de la campana: las más recientes primero
        stmt = stmt.order_by(Notificacion.id.desc())
    return (await db.execute(stmt.limit(limit))).scalars().all()


@router.get("/resumen", response_model=ResumenNotificaciones)
async def resumen_notificaciones(
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    """Barato: para el puntito con número en la campana."""
    await generar_recordatorios(db, usuario)
    no_leidas, ultimo = (
        await db.execute(
            select(
                func.count().filter(Notificacion.leida.is_(False)),
                func.max(Notificacion.id),
            ).where(Notificacion.usuario_id == usuario.id)
        )
    ).one()
    return ResumenNotificaciones(no_leidas=no_leidas or 0, ultimo_id=ultimo)


@router.post("/leidas", status_code=status.HTTP_204_NO_CONTENT)
async def marcar_todas_leidas(
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notificacion)
        .where(Notificacion.usuario_id == usuario.id, Notificacion.leida.is_(False))
        .values(leida=True)
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{notificacion_id}/leida", status_code=status.HTTP_204_NO_CONTENT)
async def marcar_leida(
    notificacion_id: int,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    resultado = await db.execute(
        update(Notificacion)
        .where(Notificacion.id == notificacion_id, Notificacion.usuario_id == usuario.id)
        .values(leida=True)
    )
    if resultado.rowcount == 0:
        # No existe o es de otra persona: misma respuesta para no revelar nada
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)