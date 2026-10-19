from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Usuario
from app.models.enums import EstadoInscripcion
from app.models.inscripciones import InscripcionActividad, InscripcionParticipante
from app.routers._comun import _borrar_objetos
from app.routers.imagenes import guardar_imagen_subida
from app.schemas_familia import PerfilActualizar, PerfilOut
from app.schemas_inscripciones import InsigniaOut
from app.security import obtener_usuario_actual

router = APIRouter(prefix="/usuarios", tags=["perfil"])


@router.get("/me", response_model=PerfilOut)
async def mi_perfil(usuario: Usuario = Depends(obtener_usuario_actual)):
    return usuario


@router.patch("/me", response_model=PerfilOut)
async def actualizar_mi_perfil(
    datos: PerfilActualizar,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        if campo == "nombre" and valor is None:
            continue
        setattr(usuario, campo, valor)
    await db.commit()
    await db.refresh(usuario)
    return usuario


# ---------- Foto de perfil ----------

@router.put("/me/foto", response_model=PerfilOut)
async def cambiar_mi_foto(
    archivo: UploadFile,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    clave_nueva = await guardar_imagen_subida(archivo)
    anterior = usuario.foto_url
    usuario.foto_url = clave_nueva
    try:
        await db.commit()
    except Exception:
        await _borrar_objetos([clave_nueva])
        raise
    if anterior:
        await _borrar_objetos([anterior])
    await db.refresh(usuario)
    return usuario


@router.delete("/me/foto", response_model=PerfilOut)
async def quitar_mi_foto(
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    anterior = usuario.foto_url
    usuario.foto_url = None
    await db.commit()
    if anterior:
        await _borrar_objetos([anterior])
    await db.refresh(usuario)
    return usuario


# ---------- Insignias ----------
@router.get("/me/insignias", response_model=List[InsigniaOut])
async def obtener_mis_insignias(
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db)
):
    ahora = datetime.utcnow()

    subq_participante = select(InscripcionParticipante.inscripcion_id).where(
        InscripcionParticipante.usuario_id == usuario_actual.id
    )

    condiciones = [
        InscripcionActividad.inscrito_por_id == usuario_actual.id,
        InscripcionActividad.id.in_(subq_participante)
    ]
    if usuario_actual.familia_id:
        condiciones.append(InscripcionActividad.familia_id == usuario_actual.familia_id)

    stmt = (
        select(InscripcionActividad)
        .options(selectinload(InscripcionActividad.actividad))
        .where(
            or_(*condiciones),
            InscripcionActividad.estado != EstadoInscripcion.CANCELADA
        )
    )
    
    res = await db.execute(stmt)
    inscripciones = res.scalars().all()

    insignias = []
    vistas = set()

    for ins in inscripciones:
        act = ins.actividad
        if not act:
            continue

        act_id = getattr(act, "iniciativa_id", None) or getattr(act, "id", None) or ins.actividad_id
        act_id_str = str(act_id)
        if act_id_str in vistas:
            continue

        fecha_ref = getattr(act, "termina_en", None) or getattr(act, "inicia_en", None)
        
        es_pasada = True
        if fecha_ref:
            if isinstance(fecha_ref, datetime):
                f_cmp = fecha_ref.replace(tzinfo=None) if fecha_ref.tzinfo else fecha_ref
            else:
                f_cmp = datetime(fecha_ref.year, fecha_ref.month, fecha_ref.day)
            es_pasada = f_cmp <= ahora

        if es_pasada:
            vistas.add(act_id_str)
            
            # Obtener el nombre legible de la categoría
            cat_obj = getattr(act, "categoria", None)
            if hasattr(cat_obj, "nombre"):
                cat_nombre = cat_obj.nombre
            elif hasattr(cat_obj, "value"):
                cat_nombre = cat_obj.value
            elif isinstance(cat_obj, str) and not cat_obj.startswith("<"):
                cat_nombre = cat_obj
            else:
                cat_nombre = "General"

            insignias.append(
                InsigniaOut(
                    id=ins.id,
                    actividad_id=act_id,
                    titulo_actividad=act.titulo,
                    categoria=cat_nombre,
                    fecha_otorgada=act.inicia_en or ahora
                )
            )

    return insignias