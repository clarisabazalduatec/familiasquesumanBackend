import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import CentroNecesidad, CentroVisiteo, TipoCentro, Usuario
from app.routers._comun import Paginacion, obtener_o_404
# Mismas reglas de imágenes y ciudad por default que en proyectos
from app.routers.proyectos import _borrar_objetos, _ciudad_id, _claves_validas
from app.schemas_catalogo import CentroAdmin, CentroDetalle, CentroGuardar, CentroResumen
from app.security import requiere_admin

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


# =====================================================================
# ADMIN
# Van antes de "/{centro_id}" para que "admin" no se tome como un id.
# =====================================================================

@router.get("/admin", response_model=list[CentroAdmin])
async def listar_centros_admin(
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    """Todos los centros, incluidos los desactivados, con su detalle completo."""
    stmt = select(CentroVisiteo).order_by(CentroVisiteo.activo.desc(), CentroVisiteo.nombre)
    return (await db.execute(stmt)).scalars().all()


@router.get("/admin/{centro_id}", response_model=CentroAdmin)
async def detalle_centro_admin(
    centro_id: uuid.UUID,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    centro = await db.get(CentroVisiteo, centro_id)
    if centro is None:
        raise HTTPException(status_code=404, detail="Centro no encontrado")
    return centro


async def _aplicar(db: AsyncSession, centro: CentroVisiteo, datos: CentroGuardar) -> None:
    # Validar el logo ANTES de tocar el centro: si no existe en el almacén, 422 y no cambia nada
    logo = await _claves_validas([datos.logo_url])

    centro.tipo = datos.tipo
    centro.nombre = datos.nombre.strip()
    centro.descripcion_corta = datos.descripcion_corta.strip()
    centro.informacion_general = datos.informacion_general.strip()
    centro.direccion = datos.direccion.strip()
    centro.mapa_url = datos.mapa_url
    centro.ciudad_id = await _ciudad_id(db, datos.ciudad_id)
    centro.logo_url = logo[0] if logo else None
    centro.como_ayudar = datos.como_ayudar
    centro.recomendaciones = datos.recomendaciones
    centro.telefono = datos.telefono
    centro.whatsapp = datos.whatsapp
    centro.verificado = datos.verificado
    centro.activo = datos.activo
    # Se reemplazan completas (delete-orphan borra las anteriores)
    centro.necesidades = [
        CentroNecesidad(descripcion=texto, orden=i) for i, texto in enumerate(datos.necesidades)
    ]


async def _recargar(db: AsyncSession, centro_id: uuid.UUID) -> CentroVisiteo:
    stmt = (
        select(CentroVisiteo)
        .where(CentroVisiteo.id == centro_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


@router.post("", response_model=CentroAdmin, status_code=status.HTTP_201_CREATED)
async def crear_centro(
    datos: CentroGuardar,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    centro = CentroVisiteo(necesidades=[])
    await _aplicar(db, centro, datos)
    db.add(centro)
    await db.commit()
    return await _recargar(db, centro.id)


@router.put("/{centro_id}", response_model=CentroAdmin)
async def editar_centro(
    centro_id: uuid.UUID,
    datos: CentroGuardar,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    centro = await db.get(CentroVisiteo, centro_id)
    if centro is None:
        raise HTTPException(status_code=404, detail="Centro no encontrado")
    logo_anterior = centro.logo_url
    await _aplicar(db, centro, datos)
    logo_nuevo = centro.logo_url
    await db.commit()
    # Solo después del commit: si cambió el logo, el anterior se borra del almacén
    if logo_anterior and logo_anterior != logo_nuevo:
        await _borrar_objetos([logo_anterior])
    return await _recargar(db, centro.id)


@router.delete("/{centro_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar_centro(
    centro_id: uuid.UUID,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    centro = await db.get(CentroVisiteo, centro_id)
    if centro is None:
        raise HTTPException(status_code=404, detail="Centro no encontrado")
    logo = centro.logo_url
    await db.delete(centro)
    await db.commit()
    if logo:
        await _borrar_objetos([logo])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Público: va al final para no tapar "/admin"
@router.get("/{centro_id}", response_model=CentroDetalle)
async def detalle_centro(centro_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await obtener_o_404(db, CentroVisiteo, centro_id, "Centro")