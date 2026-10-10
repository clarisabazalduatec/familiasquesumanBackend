import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Donacion, ModalidadDonacion
from app.routers._comun import Paginacion, obtener_o_404
from app.schemas_catalogo import DonacionDetalle, DonacionResumen

router = APIRouter(prefix="/donaciones", tags=["donaciones"])


@router.get("", response_model=list[DonacionResumen])
async def listar_donaciones(
    modalidad: ModalidadDonacion | None = Query(None, description="CAMPANA o ESPECIE"),
    categoria_id: int | None = None,
    ciudad_id: int | None = None,
    pag: Paginacion = Depends(),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Donacion).where(Donacion.activa.is_(True))
    if modalidad:
        stmt = stmt.where(Donacion.modalidad == modalidad)
    if categoria_id:
        stmt = stmt.where(Donacion.categoria_id == categoria_id)
    if ciudad_id:
        stmt = stmt.where(Donacion.ciudad_id == ciudad_id)
    stmt = stmt.order_by(Donacion.creado_en.desc()).limit(pag.limit).offset(pag.offset)
    return (await db.execute(stmt)).scalars().all()


@router.get("/{donacion_id}", response_model=DonacionDetalle)
async def detalle_donacion(donacion_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await obtener_o_404(db, Donacion, donacion_id, "Donación")