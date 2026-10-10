import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CentroVisiteo, TipoCentro
from app.routers._comun import Paginacion, obtener_o_404
from app.schemas_catalogo import CentroDetalle, CentroResumen

router = APIRouter(prefix="/centros", tags=["directorio de visiteo"])


@router.get("", response_model=list[CentroResumen])
async def listar_centros(
    tipo: TipoCentro | None = None,
    ciudad_id: int | None = None,
    q: str | None = Query(None, min_length=2, max_length=60),
    pag: Paginacion = Depends(),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CentroVisiteo).where(CentroVisiteo.activo.is_(True))
    if tipo:
        stmt = stmt.where(CentroVisiteo.tipo == tipo)
    if ciudad_id:
        stmt = stmt.where(CentroVisiteo.ciudad_id == ciudad_id)
    if q:
        stmt = stmt.where(
            CentroVisiteo.nombre.icontains(q, autoescape=True)
            | CentroVisiteo.descripcion_corta.icontains(q, autoescape=True)
        )
    stmt = stmt.order_by(CentroVisiteo.nombre).limit(pag.limit).offset(pag.offset)
    return (await db.execute(stmt)).scalars().all()


@router.get("/{centro_id}", response_model=CentroDetalle)
async def detalle_centro(centro_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await obtener_o_404(db, CentroVisiteo, centro_id, "Centro")