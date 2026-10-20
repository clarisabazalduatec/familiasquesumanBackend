"""Herramientas (function calling) con las que el asistente consulta la base de datos.

Esto es el "R" del RAG: el modelo NO escribe SQL ni ve la base. Solo puede pedir una de
estas funciones; el backend la ejecuta con consultas fijas y le regresa un JSON corto.

Reglas de seguridad (no relajar sin pensarlo):
- Solo lectura. Ninguna herramienta escribe, borra ni inscribe.
- Solo contenido público y activo (lo mismo que ve cualquier persona en la app).
- Los datos personales salen únicamente de `mi_cuenta`, que usa el usuario del TOKEN.
  El modelo no puede pedir datos de otro usuario: ninguna herramienta recibe un id de usuario.
- Cada respuesta se arma con una lista blanca de campos: nunca se manda un objeto completo
  (nada de correos, contraseñas, ids de usuario, quién creó qué, etc.).
"""
import re
import unicodedata
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Actividad,
    CentroVisiteo,
    Donacion,
    EstadoInvitacion,
    Familia,
    InvitacionFamilia,
    ModalidadDonacion,
    Proyecto,
    TipoCentro,
    Usuario,
)

ZONA = ZoneInfo("America/Monterrey")
MAX_RESULTADOS = 5      # por búsqueda; el modelo responde mejor con poco contexto
MAX_TEXTO = 350         # recorta descripciones largas
MAX_CANDIDATOS = 200    # el catálogo es chico: se trae y se ordena en Python

PALABRAS_VACIAS = {
    "de", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o", "en", "para", "por",
    "con", "sin", "a", "al", "del", "que", "se", "mi", "mis", "me", "hay", "algo", "alguna",
    "algun", "algún", "quiero", "puedo", "como", "cómo", "donde", "dónde", "cual", "cuál",
}

# Palabras que describen la SECCIÓN, no lo que se busca ("¿dónde puedo donar?", "voluntariado del DIF").
# Si contaran, "donar" no coincidiría con nada y el modelo diría que no hay donaciones.
PALABRAS_GENERICAS = {
    "voluntariado", "voluntariados", "voluntario", "voluntaria", "voluntarios", "voluntarias",
    "donar", "dono", "donacion", "donaciones", "donativo", "donativos", "aportar", "aportacion",
    "ayudar", "ayuda", "apoyar", "apoyo", "participar", "colaborar", "visitar", "visita",
    "actividad", "actividades", "proyecto", "proyectos", "centro", "centros", "iniciativa",
    "iniciativas", "evento", "eventos", "opcion", "opciones", "familia", "familias", "app",
    "hay", "tienen", "busco", "buscar", "informacion", "info", "saber", "lugar", "lugares",
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _normalizar(texto: str | None) -> str:
    """minúsculas y sin acentos: 'Niños' -> 'ninos'."""
    if not texto:
        return ""
    sin_acentos = unicodedata.normalize("NFD", texto)
    sin_acentos = "".join(c for c in sin_acentos if unicodedata.category(c) != "Mn")
    return sin_acentos.lower()

_IGNORAR = {_normalizar(v) for v in PALABRAS_VACIAS | PALABRAS_GENERICAS}


def _palabras(texto: str | None) -> list[str]:
    return [
        p for p in re.findall(r"[a-z0-9]+", _normalizar(texto))
        if len(p) > 2 and p not in _IGNORAR
    ]


def _puntaje(consulta: list[str], titulo: str, resto: str) -> int:
    """Recuperación léxica simple: coincidencias en el título valen doble.
    Compara por prefijo para tolerar plurales ('nino' encuentra 'ninos')."""
    titulo_n, resto_n = _palabras(titulo), _palabras(resto)
    puntos = 0
    for p in consulta:
        raiz = p[:5]
        if any(t.startswith(raiz) for t in titulo_n):
            puntos += 2
        elif any(t.startswith(raiz) for t in resto_n):
            puntos += 1
    return puntos


def _ordenar(items: list, texto: str | None, campos) -> tuple[list, bool]:
    """Ordena por relevancia. Regresa (items, hubo_coincidencias)."""
    consulta = _palabras(texto)
    if not consulta:
        return items, True
    con_puntos = [(_puntaje(consulta, *campos(i)), n, i) for n, i in enumerate(items)]
    coinciden = [x for x in con_puntos if x[0] > 0]
    if not coinciden:
        return items, False
    coinciden.sort(key=lambda x: (-x[0], x[1]))  # empate: se respeta el orden original
    return [i for _, _, i in coinciden], True


def _corto(texto: str | None) -> str | None:
    if not texto:
        return None
    texto = " ".join(texto.split())
    return texto if len(texto) <= MAX_TEXTO else texto[:MAX_TEXTO].rsplit(" ", 1)[0] + "…"


def _fecha(dt: datetime) -> str:
    """Fecha legible en hora de Monterrey: 'sábado 18/10/2026 09:00'."""
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    local = dt.astimezone(ZONA)
    return f"{dias[local.weekday()]} {local:%d/%m/%Y %H:%M}"


def _limpio(d: dict) -> dict:
    """Quita los campos vacíos para no gastar contexto."""
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _enlace(tipo: str, id_, titulo: str) -> dict:
    return {"tipo": tipo, "id": str(id_), "titulo": titulo}


def _respuesta(items: list[dict], hubo_coincidencias: bool, total: int, enlaces: list[dict]) -> dict:
    # "_enlaces" NO se manda al modelo (chat.py lo saca): sirve para poner botones en la app
    # que llevan al detalle de lo que el asistente mencione.
    r = {"resultados": items, "total_en_la_app": total, "_enlaces": enlaces}
    if not hubo_coincidencias:
        r["aviso"] = ("Ningún registro menciona esas palabras exactas; estas son TODAS las opciones "
                      "disponibles de esta sección. Revisa si alguna sirve antes de decir que no hay.")
    if not items:
        r["aviso"] = "No hay registros de este tipo en la app por ahora."
    return r


# ---------------------------------------------------------------------------
# Herramientas públicas (catálogo)
# ---------------------------------------------------------------------------

async def buscar_actividades(db: AsyncSession, texto: str | None = None) -> dict:
    ahora = datetime.now(timezone.utc)
    stmt = (
        select(Actividad)
        .where(Actividad.activa.is_(True), Actividad.termina_en >= ahora)
        .order_by(Actividad.inicia_en)
        .limit(MAX_CANDIDATOS)
    )
    todas = list((await db.execute(stmt)).scalars().all())
    orden, hubo = _ordenar(
        todas, texto,
        lambda a: (a.titulo, f"{a.descripcion_corta} {a.acerca_de or ''} {a.categoria.nombre} {a.direccion or ''} {a.ciudad.nombre}"),
    )
    items = [
        _limpio({
            "titulo": a.titulo,
            "categoria": a.categoria.nombre,
            "cuando": f"{_fecha(a.inicia_en)} a {a.termina_en.astimezone(ZONA):%H:%M}",
            "donde": a.ciudad.nombre,
            "como_llegar": a.ubicacion,
            "organiza": a.organizacion.nombre if a.organizacion else None,
            "lugares_disponibles": a.plazas_disponibles,
            "cupo_total": a.cupo_total,
            "descripcion": _corto(a.descripcion_corta),
            "acerca_de": _corto(a.acerca_de),
        })
        for a in orden[:MAX_RESULTADOS]
    ]
    enlaces = [_enlace("actividad", a.id, a.titulo) for a in orden[:MAX_RESULTADOS]]
    return _respuesta(items, hubo, len(todas), enlaces)


async def buscar_proyectos(db: AsyncSession, texto: str | None = None, estado: str | None = None) -> dict:
    stmt = select(Proyecto).where(Proyecto.activa.is_(True))
    if estado in ("ACTIVO", "ANTERIOR"):
        stmt = stmt.where(Proyecto.estado == estado)
    stmt = stmt.order_by(Proyecto.creado_en.desc()).limit(MAX_CANDIDATOS)
    todos = list((await db.execute(stmt)).scalars().all())
    orden, hubo = _ordenar(
        todos, texto,
        lambda p: (p.titulo, f"{p.descripcion_corta} {p.acerca_de or ''} {p.beneficiarios} "
                             f"{' '.join(o.titulo for o in p.opciones_apoyo)}"),
    )
    items = [
        _limpio({
            "titulo": p.titulo,
            "estado": "activo" if p.estado.value == "ACTIVO" else "anterior (ya no recibe apoyo)",
            "beneficiarios": p.beneficiarios,
            "donde": p.ciudad.nombre,
            "como_llegar": p.ubicacion,
            "descripcion": _corto(p.descripcion_corta),
            "acerca_de": _corto(p.acerca_de),
            "como_ayudar": _corto(p.como_ayudar),
            "formas_de_apoyo": [_limpio({"titulo": o.titulo, "detalle": _corto(o.descripcion)}) for o in p.opciones_apoyo],
            "whatsapp": p.whatsapp,
            "telefono": p.telefono,
            "instagram": p.instagram_url,
        })
        for p in orden[:MAX_RESULTADOS]
    ]
    enlaces = [_enlace("proyecto", p.id, p.titulo) for p in orden[:MAX_RESULTADOS]]
    return _respuesta(items, hubo, len(todos), enlaces)


async def buscar_donaciones(db: AsyncSession, texto: str | None = None, modalidad: str | None = None) -> dict:
    stmt = select(Donacion).where(Donacion.activa.is_(True))
    if modalidad in ("CAMPANA", "ESPECIE"):
        stmt = stmt.where(Donacion.modalidad == ModalidadDonacion(modalidad))
    stmt = stmt.order_by(Donacion.creado_en.desc()).limit(MAX_CANDIDATOS)
    todas = list((await db.execute(stmt)).scalars().all())
    orden, hubo = _ordenar(
        todas, texto,
        lambda d: (d.titulo, f"{d.descripcion_corta} {d.descripcion_larga or ''} "
                             f"{d.categoria.nombre if d.categoria else ''} {' '.join(e.valor for e in d.etiquetas)}"),
    )
    items = []
    for d in orden[:MAX_RESULTADOS]:
        etiquetas = {k: v for k, v in d.etiquetas_agrupadas.items() if v}
        items.append(_limpio({
            "titulo": d.titulo,
            "tipo": "campaña de dinero" if d.modalidad == ModalidadDonacion.CAMPANA else "donación en especie",
            "categoria": d.categoria.nombre if d.categoria else None,
            "organiza": d.organizacion.nombre if d.organizacion else None,
            "donde_entregar": d.ciudad.nombre,
            "como_llegar": d.ubicacion,
            "descripcion": _corto(d.descripcion_corta),
            "detalle": _corto(d.descripcion_larga),
            "meta": float(d.meta) if d.meta is not None else None,
            "montos_sugeridos": [{"titulo": o.titulo, "monto": float(o.monto)} for o in d.opciones],
            "etiquetas": etiquetas,
            "condiciones": _corto(d.condiciones_recepcion),
            "whatsapp": d.whatsapp,
        }))
    enlaces = [_enlace("donacion", d.id, d.titulo) for d in orden[:MAX_RESULTADOS]]
    return _respuesta(items, hubo, len(todas), enlaces)


async def buscar_centros(db: AsyncSession, texto: str | None = None, tipo: str | None = None) -> dict:
    stmt = select(CentroVisiteo).where(CentroVisiteo.activo.is_(True))
    if tipo in ("ASILO", "CASA_HOGAR", "COMEDOR"):
        stmt = stmt.where(CentroVisiteo.tipo == TipoCentro(tipo))
    stmt = stmt.order_by(CentroVisiteo.nombre).limit(MAX_CANDIDATOS)
    todos = list((await db.execute(stmt)).scalars().all())
    orden, hubo = _ordenar(
        todos, texto,
        lambda c: (c.nombre, f"{c.descripcion_corta} {c.informacion_general} {c.direccion} "
                             f"{' '.join(n.descripcion for n in c.necesidades)} {c.tipo.value}"),
    )
    nombres_tipo = {"ASILO": "asilo", "CASA_HOGAR": "casa hogar", "COMEDOR": "comedor"}
    items = [
        _limpio({
            "nombre": c.nombre,
            "tipo": nombres_tipo[c.tipo.value],
            "direccion": c.direccion,
            "como_llegar": c.ubicacion,
            "descripcion": _corto(c.descripcion_corta),
            "informacion": _corto(c.informacion_general),
            "necesidades": [_corto(n.descripcion) for n in c.necesidades],
            "como_ayudar": _corto(c.como_ayudar),
            "recomendaciones": _corto(c.recomendaciones),
            "telefono": c.telefono,
            "whatsapp": c.whatsapp,
        })
        for c in orden[:MAX_RESULTADOS]
    ]
    enlaces = [_enlace("centro", c.id, c.nombre) for c in orden[:MAX_RESULTADOS]]
    return _respuesta(items, hubo, len(todos), enlaces)


# ---------------------------------------------------------------------------
# Herramienta personal: SOLO el usuario del token
# ---------------------------------------------------------------------------

def _edad(nacimiento: date) -> int:
    hoy = datetime.now(ZONA).date()
    return hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))


async def mi_cuenta(db: AsyncSession, usuario: Usuario | None) -> dict:
    if usuario is None:
        return {"sesion_iniciada": False,
                "aviso": "La persona no ha iniciado sesión; no hay datos personales."}

    datos: dict = {
        "sesion_iniciada": True,
        "nombre": usuario.nombre,
        "ciudad": usuario.ciudad.nombre if usuario.ciudad else None,
        "es_administrador": usuario.rol.value == "ADMIN",
    }

    if usuario.familia_id:
        # selectinload: en async no se pueden cargar relaciones "al vuelo"
        familia = await db.scalar(
            select(Familia).options(selectinload(Familia.menores)).where(Familia.id == usuario.familia_id)
        )
        if familia is not None:
            # Solo nombre y parentesco de su propia familia: nada de correos ni ids.
            adultos = (await db.execute(
                select(Usuario.nombre, Usuario.parentesco).where(Usuario.familia_id == familia.id)
            )).all()
            menores = sorted(familia.menores, key=lambda m: m.fecha_nacimiento)
            datos["familia"] = _limpio({
                "nombre": familia.nombre,
                "adultos": [_limpio({"nombre": n, "parentesco": p.value.lower() if p else None}) for n, p in adultos],
                # Solo la edad: los nombres de menores no se mandan a un tercero (Gemini)
                "menores": [{"edad": _edad(m.fecha_nacimiento)} for m in menores],
            })
    else:
        datos["familia"] = "Todavía no pertenece a ninguna familia (puede crearla desde su Perfil)."

    pendientes = (await db.execute(
        select(InvitacionFamilia).where(
            InvitacionFamilia.invitado_id == usuario.id,
            InvitacionFamilia.estado == EstadoInvitacion.PENDIENTE,
        )
    )).scalars().all()
    if pendientes:
        datos["invitaciones_pendientes"] = len(pendientes)

    return _limpio(datos)

# ---------------------------------------------------------------------------
# Declaraciones para Gemini (lo que el modelo "ve" de cada herramienta)
# ---------------------------------------------------------------------------

def _texto(desc: str) -> types.Schema:
    return types.Schema(type=types.Type.STRING, description=desc)


def _opciones(desc: str, valores: list[str]) -> types.Schema:
    return types.Schema(type=types.Type.STRING, description=desc, enum=valores, format="enum")


def _objeto(propiedades: dict) -> types.Schema:
    return types.Schema(type=types.Type.OBJECT, properties=propiedades)


_TEXTO_BUSQUEDA = _texto(
    "Palabras clave de lo que busca la persona (ej. 'niños', 'ropa', 'adultos mayores'). "
    "Omítelo para traer los más próximos/recientes."
)

DECLARACIONES = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="buscar_en_todo",
        description="Busca en TODAS las secciones a la vez (actividades, proyectos, donaciones y centros). "
                    "Úsala cuando la persona menciona un nombre (organización, lugar, causa) o no está claro "
                    "en qué sección está lo que busca.",
        parameters=_objeto({"texto": _texto("Palabras clave, ej. 'DIF', 'Cadereyta', 'adultos mayores'.")}),
    ),
    types.FunctionDeclaration(
        name="buscar_actividades",
        description="Busca actividades de voluntariado en familia PRÓXIMAS (fecha, lugar, lugares disponibles).",
        parameters=_objeto({"texto": _TEXTO_BUSQUEDA}),
    ),
    types.FunctionDeclaration(
        name="buscar_proyectos",
        description="Busca proyectos sociales y voluntariados permanentes de organizaciones (ej. DIF): "
                    "a quién benefician, cómo ayudar, formas de apoyo y contacto.",
        parameters=_objeto({
            "texto": _TEXTO_BUSQUEDA,
            "estado": _opciones("ACTIVO = recibe apoyo hoy; ANTERIOR = ya terminó.", ["ACTIVO", "ANTERIOR"]),
        }),
    ),
    types.FunctionDeclaration(
        name="buscar_donaciones",
        description="Busca campañas de donación de dinero o en especie: qué se necesita, metas, montos y dónde entregar.",
        parameters=_objeto({
            "texto": _TEXTO_BUSQUEDA,
            "modalidad": _opciones("CAMPANA = dinero; ESPECIE = artículos.", ["CAMPANA", "ESPECIE"]),
        }),
    ),
    types.FunctionDeclaration(
        name="buscar_centros",
        description="Busca en el Directorio de Visiteo (asilos, casas hogar, comedores): dirección, necesidades, cómo ayudar y contacto.",
        parameters=_objeto({
            "texto": _TEXTO_BUSQUEDA,
            "tipo": _opciones("Tipo de centro.", ["ASILO", "CASA_HOGAR", "COMEDOR"]),
        }),
    ),
    types.FunctionDeclaration(
        name="mi_cuenta",
        description="Datos de la persona que está chateando: su nombre, su familia (adultos y menores con edad) "
                    "e invitaciones pendientes. Úsala para recomendaciones personalizadas o si pregunta por su cuenta.",
        parameters=None,  # sin parámetros
    ),
])



async def buscar_en_todo(db: AsyncSession, texto: str | None) -> dict:
    """Busca en las 4 secciones a la vez. Útil cuando no está claro si algo es actividad,
    proyecto, donación o centro (ej. "DIF", "Cadereyta", "niños")."""
    secciones = {
        "actividades": await buscar_actividades(db, texto),
        "proyectos": await buscar_proyectos(db, texto),
        "donaciones": await buscar_donaciones(db, texto),
        "centros": await buscar_centros(db, texto),
    }
    r: dict = {"_enlaces": []}
    for nombre, res in secciones.items():
        if res["resultados"] and "aviso" not in res:  # solo lo que sí coincide
            r[nombre] = res["resultados"][:3]
            r["_enlaces"] += res["_enlaces"][:3]
    if len(r) == 1:
        r["aviso"] = "Nada en la app menciona esas palabras. Prueba con la sección más cercana."
    return r


async def ejecutar(nombre: str, args: dict, db: AsyncSession, usuario: Usuario | None) -> dict:
    """Ejecuta la herramienta pedida por el modelo. Los argumentos se filtran: solo pasan los esperados."""
    texto = args.get("texto")
    texto = str(texto)[:100] if texto else None
    if nombre == "buscar_en_todo":
        return await buscar_en_todo(db, texto)
    if nombre == "buscar_actividades":
        return await buscar_actividades(db, texto)
    if nombre == "buscar_proyectos":
        return await buscar_proyectos(db, texto, args.get("estado"))
    if nombre == "buscar_donaciones":
        return await buscar_donaciones(db, texto, args.get("modalidad"))
    if nombre == "buscar_centros":
        return await buscar_centros(db, texto, args.get("tipo"))
    if nombre == "mi_cuenta":
        return await mi_cuenta(db, usuario)  # el usuario sale del token, nunca de los argumentos
    return {"error": f"La herramienta '{nombre}' no existe."}