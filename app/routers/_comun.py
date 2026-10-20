import uuid
from typing import TypeVar
from urllib.parse import urlsplit

from fastapi import HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app import almacen
from app.models import Ciudad

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

def _es_url_externa_valida(c: str) -> bool:
    """Solo https://host/... (antes bastaba con empezar con "http", y "httpxyz" pasaba sin validar)."""
    partes = urlsplit(c)
    return partes.scheme == "https" and bool(partes.netloc) and not any(ch.isspace() for ch in c)


async def _claves_validas(urls: list[str | None], permitir_externas: bool = True) -> list[str]:
    """Normaliza y valida imágenes. Las del almacén deben existir; las externas solo se aceptan
    con https (y solo donde permitir_externas=True, es decir, contenido que sube un admin)."""
    claves: list[str] = []
    for u in urls:
        c = almacen.clave_de(u)
        if not c:
            continue
        if c.startswith("/media/") and ".." not in c:
            pass  # imágenes anteriores al almacén
        elif almacen.CLAVE_RE.match(c):
            if not await almacen.existe(c):
                raise HTTPException(status_code=422, detail="Una de las imágenes no existe en el almacén")
        elif permitir_externas and _es_url_externa_valida(c):
            pass
        else:
            raise HTTPException(status_code=422, detail="Imagen no válida: sube la foto desde la app")
        claves.append(c)
    return claves


async def _borrar_objetos(claves: list[str]) -> None:
    for c in claves:
        if almacen.CLAVE_RE.match(c):
            try:
                await almacen.borrar(c)
            except Exception:
                pass


async def _ciudad_id(db: AsyncSession, ciudad_id: int | None) -> int:
    if ciudad_id is not None:
        if await db.get(Ciudad, ciudad_id) is None:
            raise HTTPException(status_code=400, detail="La ciudad no existe")
        return ciudad_id
    stmt = select(Ciudad.id).where(Ciudad.activa.is_(True)).order_by(
        (Ciudad.nombre != "Monterrey"), Ciudad.id
    ).limit(1)
    encontrada = await db.scalar(stmt)
    if encontrada is None:
        raise HTTPException(status_code=400, detail="No hay ciudades registradas; corre el seed")
    return encontrada