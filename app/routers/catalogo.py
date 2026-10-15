from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.models import Usuario
from app.schemas_catalogo import CategoriaCrear
from app.security import requiere_admin

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

@router.post("/categorias", response_model=CategoriaOut)
async def buscar_o_crear_categoria(
    datos: CategoriaCrear,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    """Si ya existe (mismo ámbito, sin distinguir mayúsculas) la regresa; si no, la crea."""
    consulta = select(Categoria).where(
        Categoria.ambito == datos.ambito, func.lower(Categoria.nombre) == datos.nombre.lower()
    )
    existente = await db.scalar(consulta)
    if existente:
        return existente
    categoria = Categoria(ambito=datos.ambito, nombre=datos.nombre)
    db.add(categoria)
    try:
        await db.commit()
    except IntegrityError:  # dos admins la crearon a la vez: gana la primera
        await db.rollback()
        return await db.scalar(consulta)
    await db.refresh(categoria)
    return categoria