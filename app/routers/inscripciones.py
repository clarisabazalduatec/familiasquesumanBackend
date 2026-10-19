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
from app.inscripciones_servicio import ESTADOS_ACTIVOS, ahora, bloquear_actividad, contar_ocupados, promover_lista_espera
from app.models import (
    Actividad,
    EstadoInscripcion,
    FamiliaMenor,
    InscripcionActividad,
    InscripcionParticipante,
    Usuario,
    DestinoNotificacion,
    TipoNotificacion,
    EncuestaActividad,
)
from app.schemas_inscripciones import (
    AsistenciaGuardar,
    InscripcionAdminOut,
    InscripcionGuardar,
    InscripcionOut,
    MiInscripcionOut,
)

from app.notificaciones_servicio import notificar_admins, notificar_inscripcion
from app.security import obtener_usuario_actual, requiere_admin

router = APIRouter(tags=["inscripciones"])


# ---------- helpers ----------
async def _inscripcion_activa(
    db: AsyncSession, actividad_id: uuid.UUID, familia_id: uuid.UUID
) -> InscripcionActividad | None:
    """La inscripción vigente de la familia: CONFIRMADA o EN_ESPERA (no las canceladas)."""
    return await db.scalar(
        select(InscripcionActividad).where(
            InscripcionActividad.actividad_id == actividad_id,
            InscripcionActividad.familia_id == familia_id,
            InscripcionActividad.estado.in_(ESTADOS_ACTIVOS),
        )
    )


async def _con_posicion(db, insc: InscripcionActividad) -> InscripcionActividad:
    insc.posicion_espera = None
    if insc.estado == EstadoInscripcion.EN_ESPERA:
        antes = await db.scalar(
            select(func.count()).select_from(InscripcionActividad).where(
                InscripcionActividad.actividad_id == insc.actividad_id,
                InscripcionActividad.estado == EstadoInscripcion.EN_ESPERA,
                InscripcionActividad.en_espera_desde < insc.en_espera_desde,
            )
        )
        insc.posicion_espera = (antes or 0) + 1
    return insc

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

async def _avisar_si_se_lleno(db: AsyncSession, actividad: Actividad, ocupados_ahora: int) -> None:
    """Admin: la actividad se quedó sin lugares. La clave lleva el cupo: si el admin lo
    amplía y se vuelve a llenar, vuelve a avisar; mientras tanto no se repite."""
    if ocupados_ahora >= actividad.cupo_total:
        await notificar_admins(
            db, TipoNotificacion.ACTIVIDAD_LLENA,
            "Actividad sin lugares",
            f"«{actividad.titulo}» llenó su cupo "
            f"({actividad.cupo_total} lugar{'es' if actividad.cupo_total != 1 else ''}).",
            DestinoNotificacion.ACTIVIDAD, actividad.id,
            clave=f"cupo_lleno:{actividad.id}:{actividad.cupo_total}",
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
    actividad = await _actividad_inscribible(db, actividad_id)  # candado

    if datos.total > actividad.cupo_total:
        raise HTTPException(status_code=422,
            detail=f"La actividad solo tiene {actividad.cupo_total} lugares; seleccionaste {datos.total}")
    if await _inscripcion_activa(db, actividad_id, familia_id) is not None:
        raise HTTPException(status_code=409,
            detail="Tu familia ya está inscrita o en lista de espera; puedes modificar quiénes asisten")
    await _validar_personas(db, familia_id, datos)

    ocupados = await contar_ocupados(db, actividad_id)
    libres = max(actividad.cupo_total - ocupados, 0)
    en_espera = False
    if datos.total <= libres:
        await _avisar_si_se_lleno(db, actividad, ocupados + datos.total)
    elif datos.lista_espera:
        en_espera = True
    else:
        _verificar_cupo(actividad, ocupados, datos.total)  # lanza el 409 de siempre

    inscripcion = InscripcionActividad(
        actividad_id=actividad_id, familia_id=familia_id, inscrito_por_id=usuario.id,
        estado=EstadoInscripcion.EN_ESPERA if en_espera else EstadoInscripcion.CONFIRMADA,
        en_espera_desde=ahora() if en_espera else None,
        participantes=[InscripcionParticipante(usuario_id=u) for u in datos.usuario_ids]
        + [InscripcionParticipante(menor_id=m) for m in datos.menor_ids],
    )
    db.add(inscripcion)
    try:
        await db.flush()  # si la familia ya estaba inscrita, falla aquí (antes de notificar)
        # A quien inscribió y a cada adulto inscrito (los menores no tienen cuenta)
        await notificar_inscripcion(
            db, actividad, inscripcion.id, usuario, datos.usuario_ids, datos.total, en_espera,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Tu familia ya está inscrita en esta actividad")
    return await _con_posicion(db, await _recargar(db, inscripcion.id))

@router.get("/actividades/{actividad_id}/inscripcion", response_model=InscripcionOut)
async def mi_inscripcion(
    actividad_id: uuid.UUID,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    inscripcion = None
    if usuario.familia_id is not None:
        inscripcion = await _inscripcion_activa(db, actividad_id, usuario.familia_id)
    if inscripcion is None:
        raise HTTPException(status_code=404, detail="Tu familia no está inscrita en esta actividad")
    return await _con_posicion(db, inscripcion)  # si está en espera, con su lugar en la fila


@router.put("/actividades/{actividad_id}/inscripcion", response_model=InscripcionOut)
async def cambiar_participantes(
    actividad_id: uuid.UUID,
    datos: InscripcionGuardar,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    familia_id = _familia_de(usuario)
    actividad = await _actividad_inscribible(db, actividad_id)
    inscripcion = await _inscripcion_activa(db, actividad_id, familia_id)
    if inscripcion is None:
        raise HTTPException(status_code=404, detail="Tu familia no está inscrita en esta actividad")
    if datos.total > actividad.cupo_total:
        raise HTTPException(status_code=422, detail="Seleccionaste más personas que el cupo total")
    await _validar_personas(db, familia_id, datos)

    if inscripcion.estado == EstadoInscripcion.CONFIRMADA:
        ocupados_otras = await contar_ocupados(db, actividad_id, inscripcion.id)
        _verificar_cupo(actividad, ocupados_otras, datos.total)
        await _avisar_si_se_lleno(db, actividad, ocupados_otras + datos.total)

    # Diferencia en vez de reemplazar todo: se conservan las filas de quien sigue
    # (y su asistencia) y no se choca con los UNIQUE al reinsertar a la misma persona.
    nuevos_u, nuevos_m = set(datos.usuario_ids), set(datos.menor_ids)
    adultos_antes = {p.usuario_id for p in inscripcion.participantes if p.usuario_id}
    inscripcion.participantes = [
        p for p in inscripcion.participantes
        if (p.usuario_id in nuevos_u) or (p.menor_id in nuevos_m)
    ]
    ya_u = {p.usuario_id for p in inscripcion.participantes if p.usuario_id}
    ya_m = {p.menor_id for p in inscripcion.participantes if p.menor_id}
    inscripcion.participantes += [InscripcionParticipante(usuario_id=u) for u in datos.usuario_ids if u not in ya_u]
    inscripcion.participantes += [InscripcionParticipante(menor_id=m) for m in datos.menor_ids if m not in ya_m]

    # Solo a los adultos que se agregaron ahora (a los que ya iban ya se les avisó)
    agregados = [u for u in datos.usuario_ids if u not in adultos_antes]
    if agregados:
        await notificar_inscripcion(
            db, actividad, inscripcion.id, usuario, agregados, datos.total,
            en_espera=inscripcion.estado == EstadoInscripcion.EN_ESPERA, agregados=True,
        )

    await promover_lista_espera(db, actividad_id)  # si se redujo, quizá ya cabe alguien (o ella misma)
    await db.commit()
    return await _con_posicion(db, await _recargar(db, inscripcion.id))


@router.delete("/actividades/{actividad_id}/inscripcion", status_code=status.HTTP_204_NO_CONTENT)
async def cancelar_inscripcion(
    actividad_id: uuid.UUID,
    usuario: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db),
):
    familia_id = _familia_de(usuario)
    if not await bloquear_actividad(db, actividad_id):
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    inscripcion = await _inscripcion_activa(db, actividad_id, familia_id)
    if inscripcion is None:
        raise HTTPException(status_code=404, detail="Tu familia no está inscrita en esta actividad")
    if inscripcion.actividad.inicia_en <= ahora():
        raise HTTPException(status_code=409, detail="La actividad ya comenzó; ya no se puede cancelar")

    inscripcion.estado = EstadoInscripcion.CANCELADA
    inscripcion.cancelada_en = ahora()
    inscripcion.en_espera_desde = None
    await promover_lista_espera(db, actividad_id)
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
            InscripcionActividad.estado.in_(ESTADOS_ACTIVOS),
        )
        .order_by(Actividad.inicia_en)
    )
    filas = (await db.execute(stmt)).scalars().all()

    # 1. Consultar los IDs de las actividades cuya encuesta final YA respondió el usuario
    stmt_enc = select(EncuestaActividad.actividad_id).where(
        EncuestaActividad.usuario_id == usuario.id
    )
    res_enc = await db.execute(stmt_enc)
    actividades_respondidas = set(res_enc.scalars().all())

    # 2. Mapear cada inscripción calculando encuesta_respondida = True/False
    resultado = []
    for f in filas:
        insc = await _con_posicion(db, f)
        dto = MiInscripcionOut.model_validate(insc)
        dto.encuesta_respondida = (insc.actividad_id in actividades_respondidas)
        resultado.append(dto)

    return resultado


# =====================================================================
# ADMIN
# =====================================================================

@router.get("/actividades/{actividad_id}/inscripciones", response_model=list[InscripcionAdminOut])
async def inscripciones_de_actividad(
    actividad_id: uuid.UUID,
    estado: EstadoInscripcion = EstadoInscripcion.CONFIRMADA,
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db),
):
    """Inscripciones de la actividad: ?estado=CONFIRMADA (default) o ?estado=EN_ESPERA (en orden de la fila)."""
    if await db.get(Actividad, actividad_id) is None:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    orden = (InscripcionActividad.en_espera_desde, InscripcionActividad.id) \
        if estado == EstadoInscripcion.EN_ESPERA else (InscripcionActividad.creado_en,)
    stmt = (select(InscripcionActividad)
            .where(InscripcionActividad.actividad_id == actividad_id, InscripcionActividad.estado == estado)
            .order_by(*orden))
    filas = (await db.execute(stmt)).scalars().all()
    return [await _con_posicion(db, f) for f in filas]


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
    return await inscripciones_de_actividad(
        actividad_id, estado=EstadoInscripcion.CONFIRMADA, _admin=admin, db=db
    )


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
    if not await bloquear_actividad(db, actividad_id):
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    inscripcion = await db.get(InscripcionActividad, inscripcion_id)
    if (inscripcion is None or inscripcion.actividad_id != actividad_id
            or inscripcion.estado not in ESTADOS_ACTIVOS):
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    inscripcion.estado = EstadoInscripcion.CANCELADA
    inscripcion.cancelada_en = ahora()
    inscripcion.en_espera_desde = None
    await promover_lista_espera(db, actividad_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)