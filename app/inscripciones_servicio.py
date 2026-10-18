"""Reglas de cupo compartidas por los routers de inscripciones, actividades y familias."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Actividad,
    EstadoInscripcion,
    InscripcionActividad,
    InscripcionParticipante,
    DestinoNotificacion,
    TipoNotificacion, 
    Usuario,
)
from app.notificaciones_servicio import notificar

ESTADOS_ACTIVOS = (EstadoInscripcion.CONFIRMADA, EstadoInscripcion.EN_ESPERA)

def ahora() -> datetime:
    return datetime.now(timezone.utc)


async def bloquear_actividad(db: AsyncSession, actividad_id: uuid.UUID) -> bool:
    """SELECT ... FOR UPDATE sobre la fila de la actividad. Regresa False si no existe.

    Mientras dure la transacción, cualquier otra inscripción a ESTA actividad espera aquí,
    así "contar lugares y luego insertar" no puede dejar pasar a dos familias al último lugar.
    Se bloquea solo la tabla `actividades` (no el join con `iniciativas`) para no bloquear
    de más ni mezclar FOR UPDATE con la subconsulta de lugares_ocupados.
    """
    tabla = Actividad.__table__
    fila = await db.execute(
        select(tabla.c.iniciativa_id).where(tabla.c.iniciativa_id == actividad_id).with_for_update()
    )
    return fila.first() is not None


async def contar_ocupados(
    db: AsyncSession, actividad_id: uuid.UUID, excluir_inscripcion_id: uuid.UUID | None = None
) -> int:
    """Lugares ocupados en este momento. Llamar DESPUÉS de bloquear_actividad."""
    stmt = (
        select(func.count(InscripcionParticipante.id))
        .join(InscripcionActividad, InscripcionParticipante.inscripcion_id == InscripcionActividad.id)
        .where(
            InscripcionActividad.actividad_id == actividad_id,
            InscripcionActividad.estado == EstadoInscripcion.CONFIRMADA,
        )
    )
    if excluir_inscripcion_id is not None:
        stmt = stmt.where(InscripcionActividad.id != excluir_inscripcion_id)
    return await db.scalar(stmt) or 0


async def cancelar_inscripciones_vacias(db: AsyncSession, familia_id: uuid.UUID) -> None:
    """Si a una inscripción CONFIRMADA ya no le queda nadie (se borró el menor o salió el adulto),
    se cancela: una inscripción sin participantes no tiene sentido y confundiría al admin."""
    con_gente = select(InscripcionParticipante.inscripcion_id)
    await db.execute(
        update(InscripcionActividad)
        .where(
            InscripcionActividad.familia_id == familia_id,
            InscripcionActividad.estado.in_(ESTADOS_ACTIVOS),
            InscripcionActividad.id.not_in(con_gente),
        )
        .values(estado=EstadoInscripcion.CANCELADA, cancelada_en=ahora(), en_espera_desde=None)
        .execution_options(synchronize_session=False)
    )


async def quitar_adulto_de_inscripciones_futuras(
    db: AsyncSession, usuario_id: uuid.UUID, familia_id: uuid.UUID
) -> None:
    """Cuando un adulto sale de su familia deja de ir a las actividades FUTURAS de esa familia.
    Las pasadas se conservan como historial de asistencia."""
    futuras = (
        select(InscripcionActividad.id)
        .join(Actividad, InscripcionActividad.actividad_id == Actividad.id)
        .where(
            InscripcionActividad.familia_id == familia_id,
            InscripcionActividad.estado.in_(ESTADOS_ACTIVOS),
            Actividad.inicia_en > ahora(),
        )
    )
    await db.execute(
        delete(InscripcionParticipante)
        .where(
            InscripcionParticipante.usuario_id == usuario_id,
            InscripcionParticipante.inscripcion_id.in_(futuras),
        )
        .execution_options(synchronize_session=False)
    )
    
async def promover_lista_espera(db: AsyncSession, actividad_id: uuid.UUID) -> int:
    """Sube familias de la espera a CONFIRMADA mientras quepan. Regresa cuántas subió.

    PRECONDICIÓN: ya se tomó bloquear_actividad() en esta transacción.
    No hace commit: la promoción y su notificación van en la misma transacción que el evento.
    """
    await db.flush()  # que lo pendiente (cupo nuevo, participantes) ya sea visible
    actividad = await db.get(Actividad, actividad_id)
    if actividad is None or not actividad.activa or actividad.inicia_en <= ahora():
        return 0

    libres = actividad.cupo_total - await contar_ocupados(db, actividad_id)
    if libres <= 0:
        return 0

    fila = (
        await db.execute(
            select(InscripcionActividad)
            .where(
                InscripcionActividad.actividad_id == actividad_id,
                InscripcionActividad.estado == EstadoInscripcion.EN_ESPERA,
            )
            .order_by(InscripcionActividad.en_espera_desde, InscripcionActividad.id)
            .execution_options(populate_existing=True)
        )
    ).scalars().all()

    subidas = 0
    for insc in fila:
        n = len(insc.participantes)
        if n == 0 or n > libres:
            continue  # no cabe completa: conserva su lugar en la fila
        insc.estado = EstadoInscripcion.CONFIRMADA
        insc.en_espera_desde = None
        libres -= n
        subidas += 1

        adultos = (await db.execute(
            select(Usuario.id).where(Usuario.familia_id == insc.familia_id)
        )).scalars().all()
        for uid in adultos:
            await notificar(
                db, uid, TipoNotificacion.LUGAR_CONFIRMADO,
                "¡Tu familia tiene lugar!",
                f"Se liberó un lugar y tu familia quedó confirmada en «{actividad.titulo}».",
                DestinoNotificacion.ACTIVIDAD, actividad_id, clave=f"lugar:{insc.id}:{uid}",
            )
        if libres <= 0:
            break
    return subidas


async def actividades_futuras_confirmadas(db: AsyncSession, familia_id: uuid.UUID) -> list[uuid.UUID]:
    """Para familias.py: actividades futuras donde la familia ocupa lugares (ordenadas, para
    bloquear siempre en el mismo orden y evitar deadlocks)."""
    stmt = (
        select(InscripcionActividad.actividad_id)
        .join(Actividad, InscripcionActividad.actividad_id == Actividad.id)
        .where(
            InscripcionActividad.familia_id == familia_id,
            InscripcionActividad.estado == EstadoInscripcion.CONFIRMADA,
            Actividad.inicia_en > ahora(),
        )
        .order_by(InscripcionActividad.actividad_id)
    )
    return list((await db.execute(stmt)).scalars().all())


async def bloquear_actividades(db: AsyncSession, ids: list[uuid.UUID]) -> None:
    for aid in ids:
        await bloquear_actividad(db, aid)


async def promover_varias(db: AsyncSession, ids: list[uuid.UUID]) -> None:
    for aid in ids:
        await promover_lista_espera(db, aid)