from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AmbitoCategoria, Categoria, Ciudad
from app.schemas_catalogo import CategoriaOut, CiudadOut

router = APIRouter(tags=["catálogos"])


@router.get("/ciudades", response_model=list[CiudadOut])
async def listar_ciudades(db: AsyncSession = Depends(get_db)):
    stmt = select(Ciudad).where(Ciudad.activa.is_(True)).order_by(Ciudad.nombre)
    return (await db.execute(stmt)).scalars().all()


@router.get("/categorias", response_model=list[CategoriaOut])
async def listar_categorias(ambito: AmbitoCategoria | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Categoria).order_by(Categoria.nombre)
    if ambito:
        stmt = stmt.where(Categoria.ambito == ambito)
    return (await db.execute(stmt)).scalars().all()