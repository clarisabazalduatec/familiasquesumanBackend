"""Inscripción de familias a actividades (con cupo) y pase de lista del admin.

Rutas:
  Familia (login):  /actividades/{id}/inscripcion   POST | GET | PUT | DELETE
                    /familias/mia/inscripciones     GET
  Admin:            /actividades/{id}/inscripciones GET
                    /actividades/{id}/inscripciones/{inscripcion_id}  DELETE
                    /actividades/{id}/asistencia    PUT
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.inscripciones_servicio import ahora, bloquear_actividad, contar_ocupados
from app.models import (
    Actividad,
    EstadoInscripcion,
    FamiliaMenor,
    InscripcionActividad,
    InscripcionParticipante,
    Usuario,
)
from app.schemas_inscripciones import (
    AsistenciaGuardar,
    InscripcionAdminOut,
    InscripcionGuardar,
    InscripcionOut,
    MiInscripcionOut,
)
from app.security import obtener_usuario_actual, requiere_admin

router = APIRouter(tags=["inscripciones"])


# ---------- helpers ----------
def _familia_de(usuario: Usuario) -> uuid.UUID:
    if usuario.familia_id is None:
        raise HTTPException(
            status_code=400, detail="Necesitas crear o unirte a una familia para inscribirte"
        )
    return usuario.familia_id


async def _actividad_inscribible(db: AsyncSession, actividad_id: uuid.UUID) -> Actividad:
    """Bloquea la actividad y valida que se pueda inscribir/modificar. Llamar al inicio de la transacción."""
    if not await bloquear_actividad(db, actividad_id):
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    actividad = await db.get(Actividad, actividad_id)
    if actividad is None or not actividad.activa:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    if actividad.inicia_en <= ahora():
        raise HTTPException(status_code=409, detail="La actividad ya comenzó; ya no se pueden hacer cambios")
    return actividad


async def _inscripcion_confirmada(
    db: AsyncSession, actividad_id: uuid.UUID, familia_id: uuid.UUID
) -> InscripcionActividad | None:
    return await db.scalar(
        select(InscripcionActividad).where(
            InscripcionActividad.actividad_id == actividad_id,
            InscripcionActividad.familia_id == familia_id,
            InscripcionActividad.estado == EstadoInscripcion.CONFIRMADA,
        )
    )


async def _validar_personas(db: AsyncSession, familia_id: uuid.UUID, datos: InscripcionGuardar) -> None:
    """Todos los adultos y menores enviados deben ser de ESTA familia."""
    if datos.usuario_ids:
        n = await db.scalar(
            select(func.count()).select_from(Usuario).where(
                Usuario.id.in_(datos.usuario_ids), Usuario.familia_id == familia_id
            )
        )
        if n != len(datos.usuario_ids):
            raise HTTPException(status_code=422, detail="Algún adulto no pertenece a tu familia")
    if datos.menor_ids:
        n = await db.scalar(
            select(func.count()).select_from(FamiliaMenor).where(
                FamiliaMenor.id.in_(datos.menor_ids), FamiliaMenor.familia_id == familia_id
            )
        )
        if n != len(datos.menor_ids):
            raise HTTPException(status_code=422, detail="Algún menor no pertenece a tu familia")


def _verificar_cupo(actividad: Actividad, ocupados: int, solicitados: int) -> None:
    libres = max(actividad.cupo_total - ocupados, 0)
    if solicitados > libres:
        if libres == 0:
            raise HTTPException(status_code=409, detail="La actividad ya no tiene lugares disponibles")
        raise HTTPException(
            status_code=409,
            detail=f"Solo quedan {libres} lugar{'es' if libres != 1 else ''}; seleccionaste {solicitados}",
        )


async def _recargar(db: AsyncSession, inscripcion_id: uuid.UUID) -> InscripcionActividad:
    stmt = (
        select(InscripcionActividad)
        .where(InscripcionActividad.id == inscripcion_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


# =====================================================================
# FAMILIA
# =====================================================================

@router.post(
    "/actividades/{actividad_id}/inscripcion",
    response_model=InscripcionOut,
    status_code=status.HTTP_201_CREATED,
)
async def inscribirse(
    actividad_id: uuid.UUID,
    datos: InscripcionGuardar,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    familia_id = _familia_de(usuario)
    actividad = await _actividad_inscribible(db, actividad_id)  # <- toma el candado

    if await _inscripcion_confirmada(db, actividad_id, familia_id) is not None:
        raise HTTPException(
            status_code=409, detail="Tu familia ya está inscrita; puedes modificar quiénes asisten"
        )
    await _validar_personas(db, familia_id, datos)
    _verificar_cupo(actividad, await contar_ocupados(db, actividad_id), datos.total)

    inscripcion = InscripcionActividad(
        actividad_id=actividad_id,
        familia_id=familia_id,
        inscrito_por_id=usuario.id,
        participantes=[InscripcionParticipante(usuario_id=u) for u in datos.usuario_ids]
        + [InscripcionParticipante(menor_id=m) for m in datos.menor_ids],
    )
    db.add(inscripcion)
    try:
        await db.commit()
    except IntegrityError:
        # Respaldo: dos adultos de la misma familia inscribiéndose al mismo tiempo
        await db.rollback()
        raise HTTPException(status_code=409, detail="Tu familia ya está inscrita en esta actividad")
    return await _recargar(db, inscripcion.id)


@router.get("/actividades/{actividad_id}/inscripcion", response_model=InscripcionOut)
async def mi_inscripcion(
    actividad_id: uuid.UUID,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    inscripcion = None
    if usuario.familia_id is not None:
        inscripcion = await _inscripcion_confirmada(db, actividad_id, usuario.familia_id)
    if inscripcion is None:
        raise HTTPException(status_code=404, detail="Tu familia no está inscrita en esta actividad")
    return inscripcion


@router.put("/actividades/{actividad_id}/inscripcion", response_model=InscripcionOut)
async def cambiar_participantes(
    actividad_id: uuid.UUID,
    datos: InscripcionGuardar,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    familia_id = _familia_de(usuario)
    actividad = await _actividad_inscribible(db, actividad_id)

    inscripcion = await _inscripcion_confirmada(db, actividad_id, familia_id)
    if inscripcion is None:
        raise HTTPException(status_code=404, detail="Tu familia no está inscrita en esta actividad")
    await _validar_personas(db, familia_id, datos)
    # Lo que ocupan las DEMÁS familias + lo que pide esta ahora
    _verificar_cupo(actividad, await contar_ocupados(db, actividad_id, inscripcion.id), datos.total)

    # Diferencia en vez de reemplazar todo: se conservan las filas de quien sigue
    # (y su asistencia) y no se choca con los UNIQUE al reinsertar a la misma persona.
    nuevos_u, nuevos_m = set(datos.usuario_ids), set(datos.menor_ids)
    inscripcion.participantes = [
        p for p in inscripcion.participantes
        if (p.usuario_id in nuevos_u) or (p.menor_id in nuevos_m)
    ]
    ya_u = {p.usuario_id for p in inscripcion.participantes if p.usuario_id}
    ya_m = {p.menor_id for p in inscripcion.participantes if p.menor_id}
    inscripcion.participantes += [InscripcionParticipante(usuario_id=u) for u in datos.usuario_ids if u not in ya_u]
    inscripcion.participantes += [InscripcionParticipante(menor_id=m) for m in datos.menor_ids if m not in ya_m]

    await db.commit()
    return await _recargar(db, inscripcion.id)


@router.delete("/actividades/{actividad_id}/inscripcion", status_code=status.HTTP_204_NO_CONTENT)
async def cancelar_inscripcion(
    actividad_id: uuid.UUID,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    familia_id = _familia_de(usuario)
    inscripcion = await _inscripcion_confirmada(db, actividad_id, familia_id)
    if inscripcion is None:
        raise HTTPException(status_code=404, detail="Tu familia no está inscrita en esta actividad")
    if inscripcion.actividad.inicia_en <= ahora():
        raise HTTPException(status_code=409, detail="La actividad ya comenzó; ya no se puede cancelar")

    # No se borra: queda como historial. Al dejar de estar CONFIRMADA ya no ocupa lugares.
    inscripcion.estado = EstadoInscripcion.CANCELADA
    inscripcion.cancelada_en = ahora()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/familias/mia/inscripciones", response_model=list[MiInscripcionOut])
async def inscripciones_de_mi_familia(
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    """Actividades a las que está inscrita la familia (próximas y pasadas), por fecha.
    Sin familia regresa [] en vez de error: la pantalla simplemente sale vacía."""
    if usuario.familia_id is None:
        return []
    stmt = (
        select(InscripcionActividad)
        .join(Actividad, InscripcionActividad.actividad_id == Actividad.id)
        .where(
            InscripcionActividad.familia_id == usuario.familia_id,
            InscripcionActividad.estado == EstadoInscripcion.CONFIRMADA,
        )
        .order_by(Actividad.inicia_en)
    )
    return (await db.execute(stmt)).scalars().all()


# =====================================================================
# ADMIN
# =====================================================================

@router.get("/actividades/{actividad_id}/inscripciones", response_model=list[InscripcionAdminOut])
async def inscripciones_de_actividad(
    actividad_id: uuid.UUID,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(Actividad, actividad_id) is None:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    stmt = (
        select(InscripcionActividad)
        .where(
            InscripcionActividad.actividad_id == actividad_id,
            InscripcionActividad.estado == EstadoInscripcion.CONFIRMADA,
        )
        .order_by(InscripcionActividad.creado_en)
    )
    return (await db.execute(stmt)).scalars().all()


@router.put("/actividades/{actividad_id}/asistencia", response_model=list[InscripcionAdminOut])
async def pasar_lista(
    actividad_id: uuid.UUID,
    datos: AsistenciaGuardar,
    admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    """Pase de lista en lote. Solo acepta participantes de inscripciones CONFIRMADAS de esta actividad."""
    ids = {i.participante_id for i in datos.items}
    participantes = (
        await db.execute(
            select(InscripcionParticipante)
            .join(InscripcionActividad, InscripcionParticipante.inscripcion_id == InscripcionActividad.id)
            .where(
                InscripcionParticipante.id.in_(ids),
                InscripcionActividad.actividad_id == actividad_id,
                InscripcionActividad.estado == EstadoInscripcion.CONFIRMADA,
            )
        )
    ).scalars().all()
    if len(participantes) != len(ids):
        raise HTTPException(status_code=422, detail="Algún participante no está inscrito en esta actividad")

    por_id = {p.id: p for p in participantes}
    for item in datos.items:
        por_id[item.participante_id].asistencia = item.asistencia
    await db.commit()
    return await inscripciones_de_actividad(actividad_id, admin, db)


@router.delete(
    "/actividades/{actividad_id}/inscripciones/{inscripcion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancelar_inscripcion_admin(
    actividad_id: uuid.UUID,
    inscripcion_id: uuid.UUID,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    inscripcion = await db.get(InscripcionActividad, inscripcion_id)
    if (
        inscripcion is None
        or inscripcion.actividad_id != actividad_id
        or inscripcion.estado != EstadoInscripcion.CONFIRMADA
    ):
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    inscripcion.estado = EstadoInscripcion.CANCELADA
    inscripcion.cancelada_en = ahora()
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)