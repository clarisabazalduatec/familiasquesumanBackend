import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import almacen
from app.database import get_db
from app.models import (
    Ciudad,
    EstadoProyecto,
    IniciativaImagen,
    Proyecto,
    ProyectoOpcionApoyo,
    TipoIniciativa,
    Usuario,
)
from app.routers._comun import Paginacion, obtener_o_404
from app.schemas_catalogo import ProyectoDetalle, ProyectoGuardar, ProyectoResumen
from app.security import requiere_admin

router = APIRouter(prefix="/proyectos", tags=["proyectos"])

async def _claves_validas(urls: list[str | None]) -> list[str]:
    """Normaliza lo que manda la app ('/imagenes/abc.jpg' -> 'abc.jpg') y valida que
    cada clave exista en el almacén. Las URLs http(s) externas se respetan tal cual."""
    claves: list[str] = []
    for u in urls:
        c = almacen.clave_de(u)
        if not c:
            continue
        if not c.startswith("http"):
            if not almacen.CLAVE_RE.match(c) or not await almacen.existe(c):
                raise HTTPException(status_code=422, detail=f"La imagen {c} no existe en el almacén")
        claves.append(c)
    return claves


async def _borrar_objetos(claves: list[str]) -> None:
    """Borra del almacén solo las claves propias (no las http externas).
    Si falla, queda un archivo huérfano, nunca una referencia rota."""
    for c in claves:
        if almacen.CLAVE_RE.match(c):
            try:
                await almacen.borrar(c)
            except Exception:
                pass


def _claves_de(proyecto: Proyecto) -> list[str]:
    claves = {i.url for i in proyecto.imagenes}
    if proyecto.logo_url:
        claves.add(proyecto.logo_url)
    return list(claves)

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


# =====================================================================
# ADMIN: crear, editar y borrar
# Para "desactivar" un proyecto se manda estado=ANTERIOR (sigue visible en la pestaña
# "Proyectos anteriores"). Borrar lo elimina definitivamente.
# =====================================================================

async def _ciudad_id(db: AsyncSession, ciudad_id: int | None) -> int:
    if ciudad_id is not None:
        if await db.get(Ciudad, ciudad_id) is None:
            raise HTTPException(status_code=400, detail="La ciudad no existe")
        return ciudad_id
    # Por default Monterrey (o la primera ciudad activa si no existiera)
    stmt = select(Ciudad.id).where(Ciudad.activa.is_(True)).order_by(
        (Ciudad.nombre != "Monterrey"), Ciudad.id
    ).limit(1)
    encontrada = await db.scalar(stmt)
    if encontrada is None:
        raise HTTPException(status_code=400, detail="No hay ciudades registradas; corre el seed")
    return encontrada


async def _aplicar(db: AsyncSession, proyecto: Proyecto, datos: ProyectoGuardar) -> None:
    # Validar imágenes ANTES de tocar el proyecto: si alguna no existe, responde 422 y no cambia nada
    logo = await _claves_validas([datos.logo_url])
    claves = await _claves_validas(datos.imagenes)

    proyecto.titulo = datos.titulo.strip()
    proyecto.descripcion_corta = datos.descripcion_corta.strip()
    proyecto.beneficiarios = datos.beneficiarios.strip()
    proyecto.estado = datos.estado
    proyecto.ubicacion = datos.ubicacion
    proyecto.ciudad_id = await _ciudad_id(db, datos.ciudad_id)
    proyecto.acerca_de = datos.acerca_de
    proyecto.descripcion_larga = datos.descripcion_larga
    proyecto.como_ayudar = datos.como_ayudar
    proyecto.instagram_url = datos.instagram_url