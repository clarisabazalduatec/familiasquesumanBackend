"""Atajos para preparar datos en la BD de pruebas.

Los datos de partida se crean directo en la base (rápido y sin depender de otros endpoints);
lo que se está probando se hace siempre por la API, como lo haría la app.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Actividad, AmbitoCategoria, Categoria, CentroNecesidad, CentroVisiteo, Donacion,
    DonacionEtiqueta, DonacionOpcion, EstadoInscripcion, EstadoProyecto, Familia, FamiliaMenor,
    GrupoEtiqueta, InscripcionActividad, InscripcionParticipante, ModalidadDonacion, Organizacion,
    Proyecto, ProyectoOpcionApoyo, RolUsuario, TipoApoyo, TipoCentro, Usuario,
)
from app.security import crear_access_token, hashear_password

PASSWORD = "secreta123"
MONTERREY = 1
HERMOSILLO = 2


def en_horas(horas: float) -> datetime:
    """Fecha relativa a ahora (negativo = ya pasó)."""
    return datetime.now(timezone.utc) + timedelta(hours=horas)


def auth(usuario: Usuario) -> dict:
    """Encabezado de sesión para ese usuario."""
    return {"Authorization": f"Bearer {crear_access_token(usuario.id)}"}


# ---------- Usuarios y familias ----------
async def crear_usuario(
    db: AsyncSession, nombre: str = "Usuario Prueba", *, admin: bool = False,
    ciudad_id: int | None = MONTERREY, familia: Familia | None = None, email: str | None = None,
) -> Usuario:
    u = Usuario(
        nombre=nombre,
        email=email or f"u{uuid.uuid4().hex[:10]}@pruebas.mx",
        password_hash=hashear_password(PASSWORD),
        rol=RolUsuario.ADMIN if admin else RolUsuario.USUARIO,
        ciudad_id=ciudad_id,
        familia_id=familia.id if familia else None,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def crear_familia(
    db: AsyncSession, nombre: str = "Familia Prueba", *, adultos: int = 1,
    menores: list[tuple[str, date]] = (),
) -> tuple[Familia, list[Usuario], list[FamiliaMenor]]:
    """Familia con N adultos (usuarios con cuenta) y los menores indicados [(nombre, nacimiento)]."""
    familia = Familia(nombre=nombre)
    db.add(familia)
    await db.flush()
    lista_adultos = []
    for i in range(adultos):
        u = Usuario(
            nombre=f"Adulto {i + 1} {nombre}", email=f"a{uuid.uuid4().hex[:10]}@pruebas.mx",
            password_hash=hashear_password(PASSWORD), rol=RolUsuario.USUARIO,
            ciudad_id=MONTERREY, familia_id=familia.id,
        )
        db.add(u)
        lista_adultos.append(u)
    lista_menores = [FamiliaMenor(familia_id=familia.id, nombre=n, fecha_nacimiento=f) for n, f in menores]
    db.add_all(lista_menores)
    await db.commit()
    return familia, lista_adultos, lista_menores


# ---------- Catálogo ----------
async def categoria(db: AsyncSession, ambito: AmbitoCategoria, nombre: str) -> Categoria:
    c = await db.scalar(select(Categoria).where(Categoria.ambito == ambito, Categoria.nombre == nombre))
    if c is None:
        c = Categoria(ambito=ambito, nombre=nombre)
        db.add(c)
        await db.flush()
    return c


async def organizacion(db: AsyncSession, nombre: str = "Fundación Prueba", verificada: bool = True) -> Organizacion:
    o = await db.scalar(select(Organizacion).where(Organizacion.nombre == nombre))
    if o is None:
        o = Organizacion(nombre=nombre, verificada=verificada)
        db.add(o)
        await db.flush()
    return o


async def crear_actividad(
    db: AsyncSession, titulo: str = "Reforestación", *, cupo: int = 10, inicia_en: datetime | None = None,
    duracion_horas: float = 3, ciudad_id: int = MONTERREY, activa: bool = True,
    categoria_nombre: str = "Medio Ambiente", ubicacion: str | None = "https://maps.app.goo.gl/parque",
) -> Actividad:
    inicio = inicia_en or en_horas(72)
    a = Actividad(
        titulo=titulo, descripcion_corta=f"Descripción de {titulo}",
        acerca_de=f"Todo sobre {titulo}", direccion="Parque Central, Puerta Norte", ubicacion=ubicacion,
        ciudad_id=ciudad_id, organizacion=await organizacion(db),
        categoria=await categoria(db, AmbitoCategoria.ACTIVIDAD, categoria_nombre),
        inicia_en=inicio, termina_en=inicio + timedelta(hours=duracion_horas), cupo_total=cupo, activa=activa,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def inscribir_directo(
    db: AsyncSession, actividad: Actividad, familia: Familia, adultos: list[Usuario],
    menores: list[FamiliaMenor] = (), estado: EstadoInscripcion = EstadoInscripcion.CONFIRMADA,
) -> InscripcionActividad:
    """Inscripción ya hecha (para preparar escenarios, p. ej. actividades que ya pasaron)."""
    insc = InscripcionActividad(
        actividad_id=actividad.id, familia_id=familia.id, inscrito_por_id=adultos[0].id, estado=estado,
        en_espera_desde=en_horas(0) if estado == EstadoInscripcion.EN_ESPERA else None,
        participantes=[InscripcionParticipante(usuario_id=u.id) for u in adultos]
        + [InscripcionParticipante(menor_id=m.id) for m in menores],
    )
    db.add(insc)
    await db.commit()
    return insc


async def crear_centro(
    db: AsyncSession, nombre: str = "Casa Hogar Esperanza", *, tipo: TipoCentro = TipoCentro.CASA_HOGAR,
    ciudad_id: int = MONTERREY, verificado: bool = True, activo: bool = True,
) -> CentroVisiteo:
    c = CentroVisiteo(
        tipo=tipo, nombre=nombre, descripcion_corta=f"{nombre}: atendemos a 30 niños",
        informacion_general="Atiende a niñas y niños de 4 a 12 años sin cuidado parental.",
        direccion="Av. Siempre Viva 742", ubicacion="https://maps.app.goo.gl/centro",
        ciudad_id=ciudad_id, telefono="8112345678", whatsapp="528112345678",
        como_ayudar="Visitas y donación de útiles", verificado=verificado, activo=activo,
        necesidades=[CentroNecesidad(orden=0, descripcion="Leche y pañales"),
                     CentroNecesidad(orden=1, descripcion="Útiles escolares")],
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def crear_proyecto(
    db: AsyncSession, titulo: str = "Acompañamiento a Adultos Mayores", *,
    estado: EstadoProyecto = EstadoProyecto.ACTIVO, activa: bool = True, ciudad_id: int = MONTERREY,
) -> Proyecto:
    p = Proyecto(
        titulo=titulo, descripcion_corta="Visitas quincenales", beneficiarios="60 adultos mayores",
        estado=estado, activa=activa, ciudad_id=ciudad_id, organizacion=await organizacion(db),
        acerca_de="Programa de visitas", whatsapp="528110000000",
        opciones_apoyo=[ProyectoOpcionApoyo(tipo=TipoApoyo.TIEMPO_TALENTO, titulo="Tiempo", descripcion="Visitar en familia")],
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def crear_donacion(
    db: AsyncSession, titulo: str = "Colecta de Invierno", *,
    modalidad: ModalidadDonacion = ModalidadDonacion.ESPECIE, meta: float | None = None,
    recaudado: float = 0, ciudad_id: int = MONTERREY, activa: bool = True,
) -> Donacion:
    d = Donacion(
        titulo=titulo, descripcion_corta="Reunimos cobijas y ropa", modalidad=modalidad,
        ciudad_id=ciudad_id, activa=activa, organizacion=await organizacion(db),
        categoria=await categoria(db, AmbitoCategoria.DONACION, "Ropa"),
        meta=Decimal(str(meta)) if meta is not None else None, recaudado=Decimal(str(recaudado)),
        direccion="Calle Cóndor 1001", ubicacion="https://maps.app.goo.gl/acopio",
        condiciones_recepcion="Ropa limpia y en buen estado", horario="Sábados de 10:00 a 13:00",
        fecha_limite=en_horas(24 * 30), whatsapp="528114707350",
        opciones=[DonacionOpcion(titulo="Cobija", monto=Decimal("250")),
                  DonacionOpcion(titulo="Chamarra", monto=Decimal("400"))],
        etiquetas=[DonacionEtiqueta(grupo=GrupoEtiqueta.ARTICULO, valor="Cobijas"),
                   DonacionEtiqueta(grupo=GrupoEtiqueta.ARTICULO, valor="Ropa de invierno"),
                   DonacionEtiqueta(grupo=GrupoEtiqueta.METODO_ENTREGA, valor="Punto de acopio")],
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


# Imagen PNG mínima válida (la API revisa la firma real del archivo)
# PNG de 1x1 válido (el backend ahora re-codifica las imágenes con Pillow; el anterior tenía
# un CRC roto y Pillow lo rechaza con 415).
PNG_1PX = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
