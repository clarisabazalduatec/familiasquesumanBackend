"""Crear notificaciones desde los routers.

Las funciones NO hacen commit: se guardan en la misma transacción que el evento
(si la publicación no se aprueba por un error, tampoco sale la notificación).
"""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Actividad,
    DestinoNotificacion,
    EstadoInscripcion,
    InscripcionActividad,
    Notificacion,
    Publicacion,
    PublicacionLike,
    RolUsuario,
    TipoNotificacion,
    Usuario,
)

ZONA = ZoneInfo("America/Monterrey")
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def nombre_publicacion(p: Publicacion) -> str:
    """Título, o el inicio del texto si la publicación no tiene título."""
    if p.titulo:
        return p.titulo
    texto = " ".join(p.contenido.split())
    return texto[:40] + ("…" if len(texto) > 40 else "")


def _valores(tipo, titulo, cuerpo, destino_tipo, destino_id, clave) -> dict:
    return dict(
        tipo=TipoNotificacion(tipo).value,
        titulo=titulo[:150],
        cuerpo=cuerpo[:500],
        destino_tipo=DestinoNotificacion(destino_tipo).value if destino_tipo else None,
        destino_id=str(destino_id) if destino_id is not None else None,
        clave=clave,
    )


async def notificar(
    db: AsyncSession,
    usuario_id: uuid.UUID,
    tipo: TipoNotificacion,
    titulo: str,
    cuerpo: str,
    destino_tipo: DestinoNotificacion | None = None,
    destino_id=None,
    clave: str | None = None,
) -> None:
    """Una notificación para un usuario. Si ya existe una con la misma clave, no hace nada."""
    stmt = (
        pg_insert(Notificacion)
        .values(usuario_id=usuario_id, **_valores(tipo, titulo, cuerpo, destino_tipo, destino_id, clave))
        .on_conflict_do_nothing(constraint="uq_notificacion_clave")
    )
    await db.execute(stmt)


async def _notificar_a(db: AsyncSession, usuarios, tipo, titulo, cuerpo, destino_tipo, destino_id, clave):
    """INSERT ... SELECT: una fila por cada usuario de la consulta, en una sola sentencia."""
    v = _valores(tipo, titulo, cuerpo, destino_tipo, destino_id, clave)
    columnas = ["usuario_id", *v.keys()]
    origen = select(usuarios.c.id, *[literal(valor) for valor in v.values()])
    stmt = (
        pg_insert(Notificacion)
        .from_select(columnas, origen)
        .on_conflict_do_nothing(constraint="uq_notificacion_clave")
    )
    await db.execute(stmt)


async def notificar_admins(db, tipo, titulo, cuerpo, destino_tipo=None, destino_id=None, clave=None):
    admins = select(Usuario.id).where(Usuario.rol == RolUsuario.ADMIN).subquery()
    await _notificar_a(db, admins, tipo, titulo, cuerpo, destino_tipo, destino_id, clave)


async def notificar_usuarios(db, tipo, titulo, cuerpo, destino_tipo=None, destino_id=None, clave=None):
    """Para todos los usuarios normales (los admins publican los avisos, no los necesitan)."""
    usuarios = select(Usuario.id).where(Usuario.rol == RolUsuario.USUARIO).subquery()
    await _notificar_a(db, usuarios, tipo, titulo, cuerpo, destino_tipo, destino_id, clave)


async def notificar_like(db: AsyncSession, publicacion: Publicacion, quien: Usuario) -> None:
    """Los likes se agrupan en UNA notificación por publicación: "A Carlos y 3 personas más...".

    - Si la anterior sigue sin leer, solo se actualiza el texto (no vuelve a sonar el celular).
    - Si ya la leyó, se reemplaza por una nueva (con id nuevo, para que sí le llegue el aviso).
    """
    if publicacion.autor_id == quien.id:
        return
    total = await db.scalar(
        select(func.count()).select_from(PublicacionLike).where(
            PublicacionLike.publicacion_id == publicacion.id,
            PublicacionLike.usuario_id != publicacion.autor_id,  # el like del propio autor no cuenta
        )
    ) or 1
    nombre = quien.nombre.split(" ")[0]
    pub = nombre_publicacion(publicacion)
    if total <= 1:
        cuerpo = f"A {nombre} le gustó tu publicación «{pub}»."
    else:
        otros = total - 1
        cuerpo = f"A {nombre} y {otros} persona{'s' if otros > 1 else ''} más les gustó tu publicación «{pub}»."

    clave = f"likes:{publicacion.id}"
    anterior = await db.scalar(
        select(Notificacion).where(Notificacion.usuario_id == publicacion.autor_id, Notificacion.clave == clave)
    )
    if anterior is not None and not anterior.leida:
        anterior.cuerpo = cuerpo
        return
    if anterior is not None:
        await db.execute(delete(Notificacion).where(Notificacion.id == anterior.id))
    await notificar(
        db, publicacion.autor_id, TipoNotificacion.NUEVOS_LIKES, "Les gustó tu publicación", cuerpo,
        DestinoNotificacion.PUBLICACION, publicacion.id, clave,
    )


def _cuando(inicia_en: datetime) -> str:
    local = inicia_en.astimezone(ZONA)
    hoy = datetime.now(ZONA).date()
    if local.date() == hoy:
        dia = "hoy"
    elif local.date() == hoy + timedelta(days=1):
        dia = "mañana"
    else:
        dia = f"el {_DIAS[local.weekday()]} {local:%d/%m}"
    return f"{dia} a las {local:%H:%M}"


async def generar_recordatorios(db: AsyncSession, usuario: Usuario) -> None:
    """Recordatorio de las actividades de su familia que empiezan en las próximas 24 h.

    No hace falta un cron: se generan cuando la app pregunta por sus notificaciones
    (al abrirla o desde WorkManager cada 15 min). La clave evita repetirlos. Hace commit.
    """
    if usuario.familia_id is None:
        return
    ahora = datetime.now(timezone.utc)
    stmt = (
        select(Actividad)
        .join(InscripcionActividad, InscripcionActividad.actividad_id == Actividad.id)
        .where(
            InscripcionActividad.familia_id == usuario.familia_id,
            InscripcionActividad.estado == EstadoInscripcion.CONFIRMADA,
            Actividad.activa.is_(True),
            Actividad.inicia_en > ahora,
            Actividad.inicia_en <= ahora + timedelta(hours=24),
        )
    )
    actividades = (await db.execute(stmt)).scalars().all()
    for a in actividades:
        lugar = f" en {a.ciudad.nombre}" if a.ubicacion else ""
        await notificar(
            db, usuario.id, TipoNotificacion.RECORDATORIO_ACTIVIDAD,
            "Recordatorio de actividad",
            f"Tu familia está inscrita en «{a.titulo}»: empieza {_cuando(a.inicia_en)}{lugar}.",
            DestinoNotificacion.ACTIVIDAD, a.id, clave=f"recordatorio:{a.id}",
        )
    if actividades:
        await db.commit()


async def notificar_inscripcion(
    db: AsyncSession,
    actividad: Actividad,
    inscripcion_id: uuid.UUID,
    quien: Usuario,
    adultos: list[uuid.UUID],
    total_personas: int,
    en_espera: bool,
    agregados: bool = False,
) -> None:
    """Aviso de inscripción a una actividad.

    - Quien inscribió (persona A): confirmación de lo que hizo.
    - Cada adulto que va (persona B): que alguien de su familia lo inscribió.
    agregados=True: solo se avisa a los adultos nuevos (cuando se modifica la inscripción).
    """
    nombre = quien.nombre.split(" ")[0]
    cuando = _cuando(actividad.inicia_en)
    personas = f"{total_personas} persona{'s' if total_personas != 1 else ''}"
    destino = (DestinoNotificacion.ACTIVIDAD, actividad.id)

    if not agregados:
        if en_espera:
            titulo, cuerpo = (
                "Tu familia está en lista de espera",
                f"«{actividad.titulo}» no tiene lugares por ahora; tu familia quedó en lista de espera "
                f"({personas}). Te avisaremos si se libera un lugar.",
            )
        else:
            titulo, cuerpo = (
                "Inscripción confirmada",
                f"Inscribiste a tu familia en «{actividad.titulo}» ({personas}). Empieza {cuando}.",
            )
        await notificar(db, quien.id, TipoNotificacion.INSCRIPCION_ACTIVIDAD, titulo, cuerpo,
                        *destino, clave=f"inscripcion:{inscripcion_id}:{quien.id}")

    for uid in dict.fromkeys(adultos):  # sin repetidos, en orden
        if uid == quien.id:
            continue  # quien inscribió ya recibió su confirmación
        verbo = "te agregó a" if agregados else "te inscribió en"
        if en_espera:
            titulo = "Te anotaron en una lista de espera"
            cuerpo = (f"{nombre} {verbo} la lista de espera de «{actividad.titulo}». "
                      f"Te avisaremos si se libera un lugar.")
        else:
            titulo = "Te inscribieron a una actividad"
            cuerpo = f"{nombre} {verbo} «{actividad.titulo}». Empieza {cuando}."
        await notificar(db, uid, TipoNotificacion.INSCRIPCION_ACTIVIDAD, titulo, cuerpo, *destino,
                        # Al agregar sin clave: si lo quitan y lo vuelven a agregar, sí vuelve a avisar
                        clave=None if agregados else f"inscripcion:{inscripcion_id}:{uid}")