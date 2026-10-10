import uuid
from typing import TypeVar

from fastapi import HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class Paginacion:
    """Dependencia reutilizable: ?limit=50&offset=0"""

    def __init__(
        self,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ):
        self.limit = limit
        self.offset = offset


async def obtener_o_404(db: AsyncSession, modelo: type[T], id: uuid.UUID, nombre: str) -> T:
    """Busca por id y exige que esté activo (los desactivados no se muestran a usuarios)."""
    stmt = select(modelo).where(modelo.id == id)
    if hasattr(modelo, "activa"):
        stmt = stmt.where(modelo.activa.is_(True))
    if hasattr(modelo, "activo"):
        stmt = stmt.where(modelo.activo.is_(True))
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{nombre} no encontrada")
    return obj