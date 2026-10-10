import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Actividad
from app.routers._comun import Paginacion, obtener_o_404
from app.schemas_catalogo import ActividadDetalle, ActividadResumen

router = APIRouter(prefix="/actividades", tags=["actividades"])


@router.get("", response_model=list[ActividadResumen])
async def listar_actividades(
    ciudad_id: int | None = None,
    categoria_id: int | None = None,
    q: str | None = Query(None, min_length=2, max_length=60, description="Busca en título y descripción"),
    incluir_pasadas: bool = False,
    pag: Paginacion = Depends(),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Actividad).where(Actividad.activa.is_(True))
    if not incluir_pasadas:
        stmt = stmt.where(Actividad.termina_en >= datetime.now(timezone.utc))
    if ciudad_id:
        stmt = stmt.where(Actividad.ciudad_id == ciudad_id)
    if categoria_id:
        stmt = stmt.where(Actividad.categoria_id == categoria_id)
    if q:
        stmt = stmt.where(
            Actividad.titulo.icontains(q, autoescape=True)
            | Actividad.descripcion_corta.icontains(q, autoescape=True)
        )
    stmt = stmt.order_by(Actividad.inicia_en).limit(pag.limit).offset(pag.offset)
    return (await db.execute(stmt)).scalars().all()


@router.get("/{actividad_id}", response_model=ActividadDetalle)
async def detalle_actividad(actividad_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await obtener_o_404(db, Actividad, actividad_id, "Actividad")