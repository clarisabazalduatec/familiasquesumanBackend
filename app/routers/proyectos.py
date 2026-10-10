import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EstadoProyecto, Proyecto
from app.routers._comun import Paginacion, obtener_o_404
from app.schemas_catalogo import ProyectoDetalle, ProyectoResumen

router = APIRouter(prefix="/proyectos", tags=["proyectos"])


@router.get("", response_model=list[ProyectoResumen])
async def listar_proyectos(
    estado: EstadoProyecto | None = None,
    ciudad_id: int | None = None,
    q: str | None = Query(None, min_length=2, max_length=60),
    pag: Paginacion = Depends(),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Proyecto).where(Proyecto.activa.is_(True))
    if estado:
        stmt = stmt.where(Proyecto.estado == estado)
    if ciudad_id:
        stmt = stmt.where(Proyecto.ciudad_id == ciudad_id)
    if q:
        stmt = stmt.where(
            Proyecto.titulo.icontains(q, autoescape=True)
            | Proyecto.descripcion_corta.icontains(q, autoescape=True)
        )
    stmt = stmt.order_by(Proyecto.creado_en.desc()).limit(pag.limit).offset(pag.offset)
    return (await db.execute(stmt)).scalars().all()


@router.get("/{proyecto_id}", response_model=ProyectoDetalle)
async def detalle_proyecto(proyecto_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await obtener_o_404(db, Proyecto, proyecto_id, "Proyecto")