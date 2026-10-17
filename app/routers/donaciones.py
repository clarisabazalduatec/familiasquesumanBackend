import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import (
    AmbitoCategoria, Categoria, Ciudad, Donacion, DonacionOpcion,
    IniciativaImagen, ModalidadDonacion, TipoIniciativa, Usuario
)
from app.routers._comun import Paginacion, _claves_validas, obtener_o_404
from app.schemas_catalogo import DonacionDetalle, DonacionGuardar, DonacionResumen
from app.security import requiere_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/donaciones", tags=["donaciones"])

async def _obtener_o_crear_categoria(db: AsyncSession, categoria_id_o_nombre: int | str | None) -> int:
    if isinstance(categoria_id_o_nombre, int):
        cat = await db.get(Categoria, categoria_id_o_nombre)
        if cat and cat.ambito == AmbitoCategoria.DONACION: return cat.id
    nombre_categoria = str(categoria_id_o_nombre).strip() if categoria_id_o_nombre else "General"
    stmt = select(Categoria).where(func.lower(Categoria.nombre) == nombre_categoria.lower(), Categoria.ambito == AmbitoCategoria.DONACION)
    cat_existente = await db.scalar(stmt)
    if cat_existente: return cat_existente.id
    nueva_cat = Categoria(nombre=nombre_categoria, ambito=AmbitoCategoria.DONACION)
    db.add(nueva_cat)
    await db.flush()
    return nueva_cat.id

async def _obtener_o_crear_ciudad(db: AsyncSession, ciudad_id_o_nombre: int | str | None) -> int:
    if isinstance(ciudad_id_o_nombre, int) or (isinstance(ciudad_id_o_nombre, str) and ciudad_id_o_nombre.isdigit()):
        cid = int(ciudad_id_o_nombre)
        ciudad = await db.get(Ciudad, cid)
        if ciudad: return ciudad.id
    nombre_ciudad = str(ciudad_id_o_nombre).strip() if ciudad_id_o_nombre and not str(ciudad_id_o_nombre).isdigit() else "Monterrey"
    stmt = select(Ciudad).where(func.lower(Ciudad.nombre) == nombre_ciudad.lower())
    ciudad_existente = await db.scalar(stmt)
    if ciudad_existente: return ciudad_existente.id
    nueva_ciudad = Ciudad(nombre=nombre_ciudad, estado="Nuevo León")
    db.add(nueva_ciudad)
    await db.flush()
    return nueva_ciudad.id

def _limpiar_urls_imagenes(imagenes: list[str]) -> list[str]:
    limpias = []
    for img in imagenes:
        if not img: continue
        if "http://" in img or "https://" in img:
            pos = img.find("/imagenes/")
            if pos != -1: limpias.append(img[pos:])
            else: limpias.append(img)
        else: limpias.append(img)
    return limpias

@router.get("", response_model=list[DonacionResumen])
async def listar_donaciones(
    modalidad: ModalidadDonacion | None = Query(None),
    categoria_id: int | None = None,
    ciudad_id: int | None = None,
    incluir_desactivadas: bool = Query(False),
    pag: Paginacion = Depends(),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Donacion).options(
        selectinload(Donacion.ciudad), selectinload(Donacion.categoria),
        selectinload(Donacion.imagenes), selectinload(Donacion.opciones),
    )
    if not incluir_desactivadas: stmt = stmt.where(Donacion.activa.is_(True))
    if modalidad: stmt = stmt.where(Donacion.modalidad == modalidad)
    if categoria_id: stmt = stmt.where(Donacion.categoria_id == categoria_id)
    if ciudad_id: stmt = stmt.where(Donacion.ciudad_id == ciudad_id)
    stmt = stmt.order_by(Donacion.creado_en.desc()).limit(pag.limit).offset(pag.offset)
    return (await db.execute(stmt)).scalars().all()

@router.get("/admin", response_model=list[DonacionDetalle])
async def listar_donaciones_admin(pag: Paginacion = Depends(), _admin: Usuario = Depends(requiere_admin), db: AsyncSession = Depends(get_db)):
    stmt = select(Donacion).options(selectinload(Donacion.ciudad), selectinload(Donacion.categoria), selectinload(Donacion.imagenes), selectinload(Donacion.opciones)).order_by(Donacion.creado_en.desc()).limit(pag.limit).offset(pag.offset)
    return (await db.execute(stmt)).scalars().all()

@router.get("/admin/{donacion_id}", response_model=DonacionDetalle)
async def detalle_donacion_admin(donacion_id: uuid.UUID, _admin: Usuario = Depends(requiere_admin), db: AsyncSession = Depends(get_db)):
    return await obtener_o_404(db, Donacion, donacion_id, "Donación")

@router.get("/{donacion_id}", response_model=DonacionDetalle)
async def detalle_donacion(donacion_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Consultamos por ID sin filtrar por estado 'activa'
    result = await db.execute(select(Donacion).where(Donacion.id == donacion_id))
    donacion = result.scalar_one_or_none()

    if not donacion:
        raise HTTPException(status_code=404, detail="Donación no encontrada")

    return donacion

@router.post("", response_model=DonacionDetalle, status_code=status.HTTP_201_CREATED)
async def crear_donacion(datos: DonacionGuardar, admin: Usuario = Depends(requiere_admin), db: AsyncSession = Depends(get_db)):
    categoria_id = await _obtener_o_crear_categoria(db, datos.categoria_id)
    ciudad_id = await _obtener_o_crear_ciudad(db, datos.ciudad_id)
    imgs_limpias = _limpiar_urls_imagenes(datos.imagenes)
    claves_imgs = await _claves_validas(imgs_limpias)

    # Leemos el valor de recaudado si viene en los datos, si no asignamos 0.0
    monto_recaudado = getattr(datos, "recaudado", 0.0)
    if monto_recaudado is None:
        monto_recaudado = 0.0

    # 1. Extraemos y limpiamos el nombre de forma segura antes de meterlo a la BD
    org_nombre = getattr(datos, "organizacion_nombre", None)
    if org_nombre is not None and isinstance(org_nombre, str):
        org_nombre = org_nombre.strip()
        if not org_nombre:  # Si quedó vacío tras el strip()
            org_nombre = None

    nueva_donacion = Donacion(
        tipo=TipoIniciativa.DONACION,
        titulo=datos.titulo.strip(),
        descripcion_corta=datos.descripcion_corta.strip(),
        modalidad=datos.modalidad,
        ubicacion=datos.ubicacion,
        ciudad_id=ciudad_id,
        categoria_id=categoria_id,
        meta=datos.meta,
        recaudado=monto_recaudado,
        descripcion_larga=datos.descripcion_larga,
        whatsapp=datos.whatsapp,
        condiciones_recepcion=datos.condiciones_recepcion,
        fecha_limite=datos.fecha_limite,
        horario=datos.horario,
        activa=datos.activa,
        creado_por=admin.id,
        organizacion_nombre=org_nombre
    )

    for op in datos.opciones:
        nueva_donacion.opciones.append(DonacionOpcion(titulo=op.titulo, monto=op.monto))
    for idx, url in enumerate(claves_imgs):
        nueva_donacion.imagenes.append(IniciativaImagen(url=url, orden=idx))

    db.add(nueva_donacion)
    await db.commit()
    await db.refresh(nueva_donacion)

    stmt = select(Donacion).options(
        selectinload(Donacion.ciudad),
        selectinload(Donacion.categoria),
        selectinload(Donacion.imagenes),
        selectinload(Donacion.opciones)
    ).where(Donacion.id == nueva_donacion.id)

    return (await db.execute(stmt)).scalar_one()

@router.put("/{donacion_id}", response_model=DonacionDetalle)
async def actualizar_donacion(
    donacion_id: uuid.UUID,
    datos: DonacionGuardar,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db)
):
    try:
        stmt_obtener = select(Donacion).options(
            selectinload(Donacion.ciudad),
            selectinload(Donacion.categoria),
            selectinload(Donacion.imagenes),
            selectinload(Donacion.opciones)
        ).where(Donacion.id == donacion_id)
        
        donacion = (await db.execute(stmt_obtener)).scalar_one_or_none()
        if not donacion:
            raise HTTPException(status_code=404, detail="Donación no encontrada")

        donacion.categoria_id = await _obtener_o_crear_categoria(db, datos.categoria_id)
        donacion.ciudad_id = await _obtener_o_crear_ciudad(db, datos.ciudad_id)
        donacion.titulo = datos.titulo.strip()
        donacion.descripcion_corta = datos.descripcion_corta.strip()
        donacion.modalidad = datos.modalidad
        donacion.ubicacion = datos.ubicacion

        # 💡 ACTUALIZACIÓN DEL NOMBRE DE LA ORGANIZACIÓN / FUNDACIÓN:
        if hasattr(datos, "organizacion_nombre") and datos.organizacion_nombre is not None:
            donacion.organizacion_nombre = datos.organizacion_nombre.strip() if datos.organizacion_nombre.strip() else None

        if datos.meta is not None:
            donacion.meta = datos.meta

        # LÓGICA DE PROTECCIÓN DE RECAUDADO:
        if hasattr(datos, "recaudado") and datos.recaudado is not None:
            monto_nuevo = float(datos.recaudado)
            monto_actual = float(donacion.recaudado or 0.0)
            if monto_nuevo > monto_actual:
                donacion.recaudado = monto_nuevo

        if datos.descripcion_larga is not None:
            if datos.descripcion_larga.strip() != "" or not donacion.descripcion_larga:
                donacion.descripcion_larga = datos.descripcion_larga
        if datos.whatsapp is not None:
            if datos.whatsapp.strip() != "" or not donacion.whatsapp:
                donacion.whatsapp = datos.whatsapp

        donacion.condiciones_recepcion = datos.condiciones_recepcion
        donacion.fecha_limite = datos.fecha_limite
        donacion.horario = datos.horario
        donacion.activa = datos.activa

        # Eliminar registros anidados para recrearlos
        for op in list(donacion.opciones):
            await db.delete(op)
        donacion.opciones.clear()
        
        for img in list(donacion.imagenes):
            await db.delete(img)
        donacion.imagenes.clear()
        
        await db.flush()

        for op in datos.opciones:
            donacion.opciones.append(DonacionOpcion(titulo=op.titulo, monto=op.monto))
        
        imgs_limpias = _limpiar_urls_imagenes(datos.imagenes)
        claves_imgs = await _claves_validas(imgs_limpias)
        for idx, url in enumerate(claves_imgs):
            donacion.imagenes.append(IniciativaImagen(url=url, orden=idx))

        await db.commit()
        await db.refresh(donacion)
        
        stmt = select(Donacion).options(
            selectinload(Donacion.ciudad),
            selectinload(Donacion.categoria),
            selectinload(Donacion.imagenes),
            selectinload(Donacion.opciones)
        ).where(Donacion.id == donacion.id)
        
        return (await db.execute(stmt)).scalar_one()

    except Exception as e:
        await db.rollback()
        logger.error(f"Error al actualizar la donación {donacion_id}: {e}", exc_info=True)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno al actualizar la donación: {str(e)}"
        )

@router.delete("/{donacion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_donacion(donacion_id: uuid.UUID, _admin: Usuario = Depends(requiere_admin), db: AsyncSession = Depends(get_db)):
    donacion = await obtener_o_404(db, Donacion, donacion_id, "Donación")
    await db.delete(donacion)
    await db.commit()