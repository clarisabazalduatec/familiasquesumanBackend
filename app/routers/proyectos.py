import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    proyecto.whatsapp = datos.whatsapp
    proyecto.telefono = datos.telefono
    proyecto.logo_url = datos.logo_url
    # Listas: se reemplazan completas (delete-orphan borra las anteriores)
    proyecto.imagenes = [IniciativaImagen(url=u, orden=i) for i, u in enumerate(datos.imagenes)]
    proyecto.opciones_apoyo = [
        ProyectoOpcionApoyo(tipo=o.tipo, titulo=o.titulo.strip(), descripcion=o.descripcion.strip())
        for o in datos.opciones_apoyo
    ]


async def _detalle(db: AsyncSession, proyecto_id: uuid.UUID) -> Proyecto:
    stmt = select(Proyecto).where(Proyecto.id == proyecto_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


@router.post("", response_model=ProyectoDetalle, status_code=status.HTTP_201_CREATED)
async def crear_proyecto(
    datos: ProyectoGuardar,
    admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    proyecto = Proyecto(tipo=TipoIniciativa.PROYECTO, creado_por=admin.id, imagenes=[], opciones_apoyo=[])
    await _aplicar(db, proyecto, datos)
    db.add(proyecto)
    await db.commit()
    return await _detalle(db, proyecto.id)


@router.put("/{proyecto_id}", response_model=ProyectoDetalle)
async def editar_proyecto(
    proyecto_id: uuid.UUID,
    datos: ProyectoGuardar,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    proyecto = await db.get(Proyecto, proyecto_id)
    if proyecto is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    await _aplicar(db, proyecto, datos)
    await db.commit()
    return await _detalle(db, proyecto.id)


@router.delete("/{proyecto_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar_proyecto(
    proyecto_id: uuid.UUID,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    proyecto = await db.get(Proyecto, proyecto_id)
    if proyecto is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    await db.delete(proyecto)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)