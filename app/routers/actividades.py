import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Actividad, AmbitoCategoria, Categoria, IniciativaImagen, Organizacion, TipoIniciativa, Usuario, EstadoInscripcion, InscripcionActividad
)
from app.routers._comun import (
    Paginacion, _borrar_objetos, _ciudad_id, _claves_validas, obtener_o_404,
)
from app.schemas_catalogo import ActividadAdmin, ActividadDetalle, ActividadGuardar, ActividadResumen
from app.security import requiere_admin

from app.inscripciones_servicio import bloquear_actividad, contar_ocupados, promover_lista_espera

router = APIRouter(prefix="/actividades", tags=["actividades"])


@router.get("", response_model=list[ActividadResumen])
async def listar_actividades(
    ciudad_id: int | None = None,
    categoria_id: int | None = None,
    q: str | None = Query(None, min_length=2, max_length=60, description="Busca en título y descripción"),
    incluir_pasadas: bool = False,
    pag: Paginacion = Depends(),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Actividad).where(Actividad.activa.is_(True))
    if not incluir_pasadas:
        stmt = stmt.where(Actividad.termina_en >= datetime.now(timezone.utc))
    if ciudad_id:
        stmt = stmt.where(Actividad.ciudad_id == ciudad_id)
    if categoria_id:
        stmt = stmt.where(Actividad.categoria_id == categoria_id)
    if q:
        stmt = stmt.where(
            Actividad.titulo.icontains(q, autoescape=True)
            | Actividad.descripcion_corta.icontains(q, autoescape=True)
        )
    stmt = stmt.order_by(Actividad.inicia_en).limit(pag.limit).offset(pag.offset)
    return (await db.execute(stmt)).scalars().all()


# =====================================================================
# ADMIN — van ANTES de "/{actividad_id}" para que "admin" no se lea como UUID
# =====================================================================

@router.get("/admin", response_model=list[ActividadAdmin])
async def listar_actividades_admin(
    pag: Paginacion = Depends(),
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    """Todas: activas, desactivadas y pasadas. Las más recientes primero."""
    stmt = select(Actividad).order_by(Actividad.inicia_en.desc()).limit(pag.limit).offset(pag.offset)
    return (await db.execute(stmt)).scalars().all()


@router.get("/admin/{actividad_id}", response_model=ActividadAdmin)
async def detalle_actividad_admin(
    actividad_id: uuid.UUID,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    actividad = await db.get(Actividad, actividad_id)
    if actividad is None:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    return actividad


def _claves_de(actividad: Actividad) -> list[str]:
    return list({i.url for i in actividad.imagenes})


async def _organizacion(db: AsyncSession, nombre: str | None) -> Organizacion | None:
    """Busca por nombre (sin distinguir mayúsculas) o la crea."""
    if not nombre:
        return None
    org = await db.scalar(select(Organizacion).where(func.lower(Organizacion.nombre) == nombre.lower()))
    if org is None:
        org = Organizacion(nombre=nombre)
        db.add(org)
        await db.flush()
    return org


async def _aplicar(db: AsyncSession, actividad: Actividad, datos: ActividadGuardar) -> None:
    # Todo lo que puede fallar con 4xx va ANTES de tocar la actividad.
    claves = await _claves_validas(datos.imagenes)

    categoria = await db.get(Categoria, datos.categoria_id)
    if categoria is None or categoria.ambito != AmbitoCategoria.ACTIVIDAD:
        raise HTTPException(status_code=422, detail="La categoría no existe o no es de actividades")

    ciudad_id = await _ciudad_id(db, datos.ciudad_id)
    org = await _organizacion(db, datos.organizacion_nombre)

    actividad.titulo = datos.titulo.strip()
    actividad.descripcion_corta = datos.descripcion_corta.strip()
    actividad.ubicacion = datos.ubicacion
    actividad.ciudad_id = ciudad_id
    actividad.organizacion_id = org.id if org else None
    actividad.categoria_id = categoria.id
    actividad.inicia_en = datos.inicia_en
    actividad.termina_en = datos.termina_en
    actividad.cupo_total = datos.cupo_total
    actividad.acerca_de = datos.acerca_de
    actividad.activa = datos.activa
    actividad.imagenes = [IniciativaImagen(url=c, orden=i) for i, c in enumerate(claves)]


async def _recargar(db: AsyncSession, actividad_id: uuid.UUID) -> Actividad:
    stmt = select(Actividad).where(Actividad.id == actividad_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


@router.post("", response_model=ActividadAdmin, status_code=status.HTTP_201_CREATED)
async def crear_actividad(
    datos: ActividadGuardar,
    admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    actividad = Actividad(tipo=TipoIniciativa.ACTIVIDAD, creado_por=admin.id, imagenes=[])
    await _aplicar(db, actividad, datos)
    db.add(actividad)
    await db.commit()
    return await _recargar(db, actividad.id)


@router.put("/{actividad_id}", response_model=ActividadAdmin)
async def editar_actividad(
    actividad_id: uuid.UUID,
    datos: ActividadGuardar,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    actividad = await db.get(Actividad, actividad_id)
    # Candado: que nadie se inscriba mientras se valida el cupo nuevo
    if not await bloquear_actividad(db, actividad_id):
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    actividad = await db.get(Actividad, actividad_id)
    ocupados = await contar_ocupados(db, actividad_id)
    if datos.cupo_total < ocupados:
        raise HTTPException(
            status_code=409,
            detail=f"Ya hay {ocupados} personas inscritas; el cupo no puede ser menor a eso",
        )
    antes = _claves_de(actividad)
    await _aplicar(db, actividad, datos)
    despues = set(_claves_de(actividad))
    await promover_lista_espera(db, actividad_id)   # el cupo pudo subir (hace flush adentro)
    await db.commit()
    await _borrar_objetos([c for c in antes if c not in despues])
    return await _recargar(db, actividad.id)


@router.delete("/{actividad_id}", status_code=status.HTTP_204_NO_CONTENT)
async def borrar_actividad(
    actividad_id: uuid.UUID,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    actividad = await db.get(Actividad, actividad_id)
    if actividad is None:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    
    inscritas = await db.scalar(
        select(func.count()).select_from(InscripcionActividad).where(
            InscripcionActividad.actividad_id == actividad_id,
            InscripcionActividad.estado == EstadoInscripcion.CONFIRMADA,
        )
    )
    if inscritas:
        raise HTTPException(
            status_code=409,
            detail=f"Hay {inscritas} familia(s) inscrita(s); desactívala en lugar de borrarla",
        )
    
    claves = _claves_de(actividad)
    await db.delete(actividad)
    await db.commit()
    await _borrar_objetos(claves)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Público: al final para no tapar "/admin"
@router.get("/{actividad_id}", response_model=ActividadDetalle)
async def detalle_actividad(actividad_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await obtener_o_404(db, Actividad, actividad_id, "Actividad")