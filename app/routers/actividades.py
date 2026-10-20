import uuid
import csv
import io
from datetime import datetime, timezone

from app.models.iniciativas import EncuestaInicialActividad
from app.schemas_inscripciones import EncuestaInicialCreate, EncuestaInicialOut
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    Actividad, AmbitoCategoria, Categoria, IniciativaImagen, Organizacion, TipoIniciativa, Usuario, EstadoInscripcion, InscripcionActividad, EncuestaActividad, EstadoAsistencia
)
from app.routers._comun import (
    Paginacion, _borrar_objetos, _ciudad_id, _claves_validas, obtener_o_404,
)
from app.schemas_catalogo import ActividadAdmin, ActividadDetalle, ActividadGuardar, ActividadResumen
from app.security import requiere_admin, obtener_usuario_actual

from app.inscripciones_servicio import bloquear_actividad, contar_ocupados, promover_lista_espera

from app.schemas import EncuestaActividadCreate, EncuestaActividadOut

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


def _celda_csv(valor) -> str:
    """Evita CSV/formula injection: Excel ejecuta celdas que empiezan con = + - @ (ej. un nombre
    "=HYPERLINK(...)"). Con un apóstrofo delante se muestran como texto."""
    texto = "" if valor is None else str(valor)
    if len(texto) > 1 and texto[0] in ("=", "+", "-", "@", "\t", "\r", "|", "%"):
        return "'" + texto
    return texto


@router.get("/encuestas/exportar")
async def exportar_todas_encuestas_csv(
    _admin: Usuario = Depends(requiere_admin),
    db: AsyncSession = Depends(get_db)
):
    """Genera y descarga un archivo CSV con TODAS las encuestas registradas."""
    
    # 1. Cargar Usuarios en memoria de forma segura
    mapa_usuarios = {}
    try:
        res_u = await db.execute(select(Usuario))
        mapa_usuarios = {u.id: u.nombre for u in res_u.scalars().all()}
    except Exception:
        await db.rollback()

    # 2. Cargar Actividades en memoria
    mapa_actividades = {}
    try:
        res_a = await db.execute(select(Actividad))
        for a in res_a.scalars().all():
            act_id = getattr(a, "id", None) or getattr(a, "iniciativa_id", None)
            mapa_actividades[act_id] = getattr(a, "titulo", "Sin título")
    except Exception:
        await db.rollback()

    # 3. Consultar Encuestas
    encuestas_iniciales, encuestas_finales = [], []
    try:
        res_inic = await db.execute(select(EncuestaInicialActividad))
        encuestas_iniciales = res_inic.scalars().all()
    except Exception:
        await db.rollback()

    try:
        res_fin = await db.execute(select(EncuestaActividad))
        encuestas_finales = res_fin.scalars().all()
    except Exception:
        await db.rollback()

    registros = []

    # 4. Procesar Encuestas Iniciales
    for enc in encuestas_iniciales:
        nombre_u = mapa_usuarios.get(getattr(enc, "usuario_id", None), "Usuario Desconocido")
        titulo_a = mapa_actividades.get(getattr(enc, "actividad_id", None), "Actividad Desconocida")

        motivos = getattr(enc, "motivos", None)
        motivos_str = ", ".join(str(m) for m in motivos if m) if isinstance(motivos, list) else (str(motivos) if motivos else "")

        expectativas = getattr(enc, "expectativas", None)
        exp_str = ", ".join(str(e) for e in expectativas if e) if isinstance(expectativas, list) else (str(expectativas) if expectativas else "")

        creado_en = getattr(enc, "creado_en", None)
        fecha_str = creado_en.strftime("%Y-%m-%d %H:%M:%S") if isinstance(creado_en, datetime) else ""

        registros.append({
            "fecha": creado_en,
            "row": [
                "Inicial", titulo_a, nombre_u,
                motivos_str, getattr(enc, "otro_motivo", "") or "",
                exp_str, getattr(enc, "otra_expectativa", "") or "",
                "-", "-", "-", "-", fecha_str
            ]
        })

    # 5. Procesar Encuestas Finales
    for enc in encuestas_finales:
        nombre_u = mapa_usuarios.get(getattr(enc, "usuario_id", None), "Usuario Desconocido")
        titulo_a = mapa_actividades.get(getattr(enc, "actividad_id", None), "Actividad Desconocida")

        creado_en = getattr(enc, "creado_en", None)
        fecha_str = creado_en.strftime("%Y-%m-%d %H:%M:%S") if isinstance(creado_en, datetime) else ""

        registros.append({
            "fecha": creado_en,
            "row": [
                "Final", titulo_a, nombre_u,
                "-", "-", "-", "-",
                str(getattr(enc, "experiencia_general", "-")),
                str(getattr(enc, "utilidad_valor", "-")),
                str(getattr(enc, "facilidad_participacion", "-")),
                getattr(enc, "comentarios", "") or "Sin comentarios",
                fecha_str
            ]
        })

    # 6. Ordenamiento infalible (evita choque entre fechas con y sin zona horaria)
    def obtener_timestamp(dt):
        try:
            return dt.timestamp() if isinstance(dt, datetime) else 0.0
        except Exception:
            return 0.0

    registros.sort(key=lambda x: obtener_timestamp(x["fecha"]), reverse=True)

    # 7. Escribir CSV
    output = io.StringIO()
    output.write('\ufeff')  # BOM UTF-8
    writer = csv.writer(output)

    writer.writerow([
        "Tipo Encuesta", "Actividad", "Nombre del Participante", 
        "Motivos (Inicial)", "Otro Motivo (Inicial)", 
        "Expectativas (Inicial)", "Otra Expectativa (Inicial)", 
        "Experiencia General (1-5)", "Utilidad y Valor (1-5)", 
        "Facilidad (1-5)", "Comentarios (Final)", "Fecha"
    ])

    for item in registros:
        # Actividad, nombre, motivos y comentarios los escribe el usuario: se neutralizan
        writer.writerow([_celda_csv(v) for v in item["row"]])

    # Enviar respuesta dejando que FastAPI calcule los bytes y headers
    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=reporte_general_encuestas.csv"}
    )


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


# ---------- Encuestas: reglas de negocio ----------
async def _inscripcion_de_mi_familia(
    db: AsyncSession, usuario: Usuario, actividad_id: uuid.UUID, estados: tuple
) -> InscripcionActividad | None:
    """La inscripción de la familia del usuario (o hecha por él) en esa actividad."""
    condicion = InscripcionActividad.inscrito_por_id == usuario.id
    if usuario.familia_id is not None:
        condicion = condicion | (InscripcionActividad.familia_id == usuario.familia_id)
    return await db.scalar(
        select(InscripcionActividad).where(
            InscripcionActividad.actividad_id == actividad_id,
            InscripcionActividad.estado.in_(estados),
            condicion,
        )
    )


# Encuesta inicial (pre-actividad): por qué se inscribieron y qué esperan lograr.
@router.post("/{actividad_id}/encuesta-inicial", response_model=EncuestaInicialOut)
async def enviar_encuesta_inicial(
    actividad_id: uuid.UUID,
    encuesta: EncuestaInicialCreate,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db)
):
    # La tabla la crea la migración (antes se hacía create_all en cada request, saltándose Alembic)
    actividad = await db.get(Actividad, actividad_id)
    if actividad is None or not actividad.activa:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")

    # Solo quien se inscribió (confirmado o en lista de espera)
    if await _inscripcion_de_mi_familia(
        db, usuario_actual, actividad_id, (EstadoInscripcion.CONFIRMADA, EstadoInscripcion.EN_ESPERA)
    ) is None:
        raise HTTPException(status_code=403, detail="Solo puedes responder la encuesta de actividades a las que te inscribiste")

    existe = await db.scalar(select(EncuestaInicialActividad).where(
        EncuestaInicialActividad.actividad_id == actividad_id,
        EncuestaInicialActividad.usuario_id == usuario_actual.id,
    ))
    if existe:
        return existe  # ya la respondió: se regresa la existente

    nueva_encuesta = EncuestaInicialActividad(
        usuario_id=usuario_actual.id,
        actividad_id=actividad_id,
        motivos=encuesta.motivos,
        otro_motivo=encuesta.otro_motivo,
        expectativas=encuesta.expectativas,
        otra_expectativa=encuesta.otra_expectativa,
    )
    db.add(nueva_encuesta)
    try:
        await db.commit()
    except IntegrityError:
        # Dos envíos al mismo tiempo: el UNIQUE (usuario_id, actividad_id) frena al segundo
        await db.rollback()
        return await db.scalar(select(EncuestaInicialActividad).where(
            EncuestaInicialActividad.actividad_id == actividad_id,
            EncuestaInicialActividad.usuario_id == usuario_actual.id,
        ))
    await db.refresh(nueva_encuesta)
    return nueva_encuesta


# Encuesta de actividad (post-actividad): opinión sobre la experiencia.
@router.post("/{actividad_id}/encuesta", response_model=EncuestaActividadOut)
async def enviar_encuesta(
    actividad_id: uuid.UUID,
    encuesta: EncuestaActividadCreate,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db)
):
    actividad = await db.get(Actividad, actividad_id)
    if not actividad:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    if actividad.termina_en > datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="La encuesta se habilita cuando termina la actividad")

    # Su familia tuvo que estar confirmada y alguien de ella no marcado como "faltó".
    # (No se exige ASISTIO: si el admin no pasó lista, nadie podría responder.)
    inscripcion = await _inscripcion_de_mi_familia(db, usuario_actual, actividad_id, (EstadoInscripcion.CONFIRMADA,))
    if inscripcion is None or all(p.asistencia == EstadoAsistencia.FALTO for p in inscripcion.participantes):
        raise HTTPException(status_code=403, detail="Solo pueden responder quienes participaron en la actividad")

    existe = await db.scalar(select(EncuestaActividad).where(
        EncuestaActividad.actividad_id == actividad_id,
        EncuestaActividad.usuario_id == usuario_actual.id,
    ))
    if existe:
        return existe

    nueva_encuesta = EncuestaActividad(
        usuario_id=usuario_actual.id,
        actividad_id=actividad_id,
        experiencia_general=encuesta.experiencia_general,
        utilidad_valor=encuesta.utilidad_valor,
        facilidad_participacion=encuesta.facilidad_participacion,
        comentarios=encuesta.comentarios,
    )
    db.add(nueva_encuesta)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return await db.scalar(select(EncuestaActividad).where(
            EncuestaActividad.actividad_id == actividad_id,
            EncuestaActividad.usuario_id == usuario_actual.id,
        ))
    await db.refresh(nueva_encuesta)
    return nueva_encuesta


@router.get("/{actividad_id}/encuestas/estado")
async def estado_encuestas_usuario(
    actividad_id: uuid.UUID,
    usuario_actual: Usuario = Depends(obtener_usuario_actual),
    db: AsyncSession = Depends(get_db)
):
    """Retorna si el usuario ya respondió la encuesta inicial y/o la encuesta final."""
    
    # 1. Verificar si ya respondió la encuesta inicial
    stmt_inicial = select(EncuestaInicialActividad).where(
        EncuestaInicialActividad.actividad_id == actividad_id,
        EncuestaInicialActividad.usuario_id == usuario_actual.id
    )
    respondio_inicial = await db.scalar(stmt_inicial) is not None

    # 2. Verificar si ya respondió la encuesta final
    stmt_final = select(EncuestaActividad).where(
        EncuestaActividad.actividad_id == actividad_id,
        EncuestaActividad.usuario_id == usuario_actual.id
    )
    respondio_final = await db.scalar(stmt_final) is not None

    return {
        "encuesta_inicial_respondida": respondio_inicial,
        "encuesta_final_respondida": respondio_final
    }
