"""Carga los datos de ejemplo (los antiguos mocks de la app) en PostgreSQL.

Uso:  docker compose exec api python -m app.seed

Ubicación de cada cosa (igual que en la base desde la migración a1c7e5b9d3f2):
  - ciudad    -> FK a ciudades (Monterrey / Hermosillo). Es lo que filtra por la ciudad del perfil.
  - direccion -> texto ("Parque Central, Puerta Norte").
  - ubicacion -> link de Google Maps; la app lo muestra como botón "Cómo llegar".
Las fechas de las actividades son relativas a HOY: siempre hay próximas y concluidas.
Es idempotente por partes:
  - Catálogo (ciudades, actividades, proyectos, donaciones, centros): solo si no hay ciudades.
  - Comunidad (usuarios demo, publicaciones, avisos, likes y comentarios): solo si no hay
    publicaciones. Así se puede correr en una base que ya tenía el catálogo.
"""
import os
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Actividad, AmbitoCategoria, Categoria, CentroNecesidad, CentroVisiteo, Ciudad,
    Comentario, ComentarioLike, Donacion, DonacionEtiqueta, DonacionOpcion, EstadoAsistencia,
    EstadoInscripcion, EstadoProyecto, EstadoPublicacion, Familia, GrupoEtiqueta,
    IniciativaImagen, InscripcionActividad, InscripcionParticipante, ModalidadDonacion,
    Organizacion, Proyecto, ProyectoOpcionApoyo, Publicacion, PublicacionImagen,
    PublicacionLike, RolUsuario, TipoApoyo, TipoCentro, TipoPublicacion, Usuario,
)
from app.security import hashear_password

# Monterrey/Hermosillo: UTC-6 todo el año (sin horario de verano)
TZ = timezone(timedelta(hours=-6))


def maps(lugar: str) -> str:
    """Link de Google Maps que busca el lugar (botón "Cómo llegar")."""
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(lugar)


def en_dias(dias: int, hora: int, minuto: int = 0) -> datetime:
    """Fecha relativa a hoy (negativo = ya pasó), a la hora indicada de Monterrey."""
    base = datetime.now(TZ) + timedelta(days=dias)
    return base.replace(hour=hora, minute=minuto, second=0, microsecond=0)


def imgs(*urls: str) -> list[IniciativaImagen]:
    return [IniciativaImagen(url=u, orden=i) for i, u in enumerate(urls)]


def sembrar(db: Session) -> None:
    if db.scalar(select(func.count(Ciudad.id))):
        print("La base ya tiene datos; no se siembra nada.")
        return

    # ---------- Ciudades ----------
    mty = Ciudad(nombre="Monterrey", estado="Nuevo León")
    hmo = Ciudad(nombre="Hermosillo", estado="Sonora")
    db.add_all([mty, hmo])

    # ---------- Categorías ----------
    def cats(ambito: AmbitoCategoria, nombres: list[str]) -> dict[str, Categoria]:
        return {n: Categoria(ambito=ambito, nombre=n) for n in nombres}

    c_act = cats(AmbitoCategoria.ACTIVIDAD, ["Medio Ambiente", "Educación", "Apoyo Social", "Otros"])
    c_don = cats(AmbitoCategoria.DONACION,
                 ["Juguetes", "Ropa", "Alimentos", "Higiene", "Electrónicos", "Salud", "Útiles"])
    c_pub = cats(AmbitoCategoria.PUBLICACION,
                 ["Medio Ambiente", "Comedor Solidario", "Educación", "Voluntariado", "Salud"])
    db.add_all([*c_act.values(), *c_don.values(), *c_pub.values()])

    # ---------- Organizaciones ----------
    org = {
        "fqs": Organizacion(nombre="Familias que Suman", verificada=True, whatsapp="528120322281"),
        "verde": Organizacion(nombre="Fundación Verde Vivo", verificada=True),
        "lectores": Organizacion(nombre="Círculo de Lectores", verificada=True),
        "manos": Organizacion(nombre="Manos Amigas", verificada=False),
        "sanber": Organizacion(nombre="Escuela San Bernabé", verificada=True),
        "sanjose": Organizacion(nombre="Comedor San José", verificada=True),
    }
    db.add_all(org.values())

    # ---------- Actividades Próximas y Concluidas ----------
    act_utiles = Actividad(
        titulo="Campaña de Donación de Útiles",
        descripcion_corta="Entrega de paquetes escolares a niños de la comunidad.",
        direccion="García, N.L.", ubicacion=maps("Plaza Principal García Nuevo León"), ciudad=mty, organizacion=org["fqs"],
        categoria=c_act["Educación"], inicia_en=en_dias(-9, 9), termina_en=en_dias(-9, 13),
        cupo_total=40,
        acerca_de="Jornada de entrega de útiles y convivencia con las familias inscritas en el programa.",
    )

    act_limpieza = Actividad(
        titulo="Jornada Comunitaria de Limpieza",
        descripcion_corta="Limpieza y acondicionamiento del parque comunitario.",
        direccion="Escobedo, N.L.", ubicacion=maps("Parque Escobedo Nuevo León"), ciudad=mty, organizacion=org["verde"],
        categoria=c_act["Medio Ambiente"], inicia_en=en_dias(-7, 10), termina_en=en_dias(-7, 14),
        cupo_total=30,
        acerca_de="Recolección de residuos y pintura de bancas en el parque público.",
    )

    db.add_all([
        act_utiles,
        act_limpieza,
        Actividad(
            titulo="Reforestación Parque Central",
            descripcion_corta="Únete a la jornada de plantación de árboles nativos.",
            direccion="Parque Central, Puerta Norte", ubicacion=maps("Parque Fundidora Monterrey"), ciudad=mty, organizacion=org["verde"],
            categoria=c_act["Medio Ambiente"], inicia_en=en_dias(5, 9), termina_en=en_dias(5, 13),
            cupo_total=50,
            acerca_de=("Únete a nosotros para restaurar el pulmón de nuestra ciudad. Durante esta "
                       "jornada, las familias plantarán árboles autóctonos y aprenderán sobre la "
                       "importancia de la biodiversidad local."),
        ),
        Actividad(
            titulo="Lectura para Niños",
            descripcion_corta="Apoya como voluntario en el círculo de lectura comunitaria.",
            direccion="Biblioteca Norte", ubicacion=maps("Biblioteca Central Monterrey"), ciudad=mty, organizacion=org["lectores"],
            categoria=c_act["Educación"], inicia_en=en_dias(6, 10), termina_en=en_dias(6, 12),
            cupo_total=20,
            acerca_de=("Apoya como voluntario leyendo cuentos a niños de la comunidad. Ayudaremos a "
                       "fomentar el hábito de la lectura y la imaginación en los más pequeños."),
        ),
        Actividad(
            titulo="Comedor Solidario",
            descripcion_corta="Colabora en la preparación y entrega de alimentos a quienes más lo necesitan.",
            direccion="Centro Comunitario", ubicacion=maps("Centro Comunitario Independencia Monterrey"), ciudad=mty, organizacion=org["manos"],
            categoria=c_act["Apoyo Social"], inicia_en=en_dias(9, 16), termina_en=en_dias(9, 19),
            cupo_total=30,
            acerca_de=("Colabora en la preparación y entrega de alimentos a quienes más lo necesitan "
                       "en nuestra comunidad. Toda ayuda es bienvenida para servir cenas calientes."),
        ),
    ])

    # ---------- Proyectos ----------
    db.add_all([
        Proyecto(
            titulo="Trazo... Escribiendo una nueva historia",
            descripcion_corta="Voluntariado que visita a mujeres en el penal de Escobedo.",
            direccion="Penal de Escobedo, Escobedo, N.L.", ciudad=mty, organizacion=org["fqs"],
            estado=EstadoProyecto.ACTIVO, beneficiarios="25 Mujeres",
            acerca_de=("Trazo es un voluntariado que nace de la Asociación Renace, desde hace más de 2 "
                       "años lleva pláticas de desarrollo humano y cursos de acuarela y caligrafía a "
                       "mujeres privadas de la libertad quienes al final del semestre reciben un "
                       "reconocimiento el cual les ayuda en su expediente judicial."),
            descripcion_larga=(
                "Somos un grupo de mujeres voluntarias que realizamos visitas quincenales al Centro de "
                "Reinserción Social de Escobedo para acompañar a mujeres privadas de la libertad "
                "mediante pláticas de desarrollo humano, talleres de acuarela y actividades que "
                "fortalecen su autoestima, creatividad y crecimiento personal.\n\n"
                "En cada encuentro buscamos ofrecer un espacio de escucha, aprendizaje y esperanza, "
                "recordándoles que siempre es posible comenzar de nuevo."),
            whatsapp="5218110771068", telefono="8110771068",
            opciones_apoyo=[
                ProyectoOpcionApoyo(
                    tipo=TipoApoyo.TIEMPO_TALENTO,
                    titulo="Buscamos personas que quieran compartir su tiempo y talento.",
                    descripcion=("Voluntarias que imparten pláticas de desarrollo humano. • Talleres de "
                                 "acuarela y actividades creativas. • Otros talleres que promuevan el "
                                 "aprendizaje y el bienestar emocional.")),
                ProyectoOpcionApoyo(
                    tipo=TipoApoyo.APORTACION_ECONOMICA,
                    titulo="Aportación económica",
                    descripcion=("Donativos para comprar materiales: • Pinturas, pinceles, papel y otros "
                                 "insumos. • Aportaciones económicas para los alimentos que se entregan "
                                 "durante cada visita.")),
            ],
        ),
        Proyecto(
            titulo="Voluntariado DIF Te Acompaña",
            descripcion_corta="Acompañar a personas vulnerables.",
            direccion="San Pedro Garza García", ubicacion=maps("DIF San Pedro Garza García"), ciudad=mty, organizacion=org["fqs"],
            estado=EstadoProyecto.ACTIVO, beneficiarios="200 adultos mayores",
            acerca_de=("El voluntariado existe desde hace varios años y se busca apoyar a personas "
                       "vulnerables con una visita o ayuda con alimentos, medicinas o acompañamiento."),
            descripcion_larga=("Acompañar a adultos mayores o jóvenes vulnerables, en soledad, con "
                               "discapacidad o con una red de apoyo reducida. Realizar visitas en "
                               "familia mínimo una vez cada 15 días. Se les puede asistir en compras de "
                               "alimentos, medicamentos o solo una visita."),
            como_ayudar=("Inscribir a su familia para que el Voluntariado les asigne una persona para "
                         "visitar o acompañar."),
            whatsapp="5218113008725", telefono="8113008725",
        ),
    ])

    # ---------- Donaciones ----------
    def etiquetas(grupo: GrupoEtiqueta, valores: list[str]) -> list[DonacionEtiqueta]:
        return [DonacionEtiqueta(grupo=grupo, valor=v) for v in valores]

    db.add_all([
        # 1. Campaña Monetaria
        Donacion(
            titulo="Destellos de Luz",
            descripcion_corta=("Destellos de Luz A.B.P. cuenta con más de 29 años de experiencia brindando "
                               "atención oftalmológica integral y programas educativos que impulsan la autonomía "
                               "y calidad de vida de personas con discapacidad visual."),
            direccion="Monterrey, N.L.", ciudad=mty, organizacion=org["fqs"],
            modalidad=ModalidadDonacion.CAMPANA, categoria=c_don["Salud"],
            meta=Decimal("35700"), recaudado=Decimal("14000"), whatsapp="8180924504",
            descripcion_larga=(
                "Destellos de Luz A.B.P. es una asociación con más de 29 años de trayectoria, que cuenta con "
                "un área médica y un área educativa.\n\n"
                "En el área Médica: brindamos atención oftalmológica integral, respaldada por un cuerpo médico "
                "altruista especializado, desde la valoración médica hasta cirugías y tratamientos especializados, "
                "para quienes más lo necesitan.\n\n"
                "En el área Educativa: a través de 7 programas de educación fortalecemos las habilidades de personas "
                "con discapacidad visual para favorecer su superación y mejorar su calidad de vida."
            ),
            imagenes=imgs("https://base44.app/api/apps/69ed00f78e8b6884c29526e1/files/mp/public/69ed00f78e8b6884c29526e1/cd5c3a666_PHOTO-2026-09-21-13-28-07.jpg"),
            opciones=[
                DonacionOpcion(titulo="Bastón para desplazamiento", monto=Decimal("700")),
                DonacionOpcion(titulo="Computadora parlante", monto=Decimal("21000")),
                DonacionOpcion(titulo="Cirugía", monto=Decimal("14000")),
            ],
        ),

        # 2. En Especie
        Donacion(
            titulo="Suma a su Mesa",
            descripcion_corta=("Recolección de alimentos y productos de limpieza para el Asilo de Ancianos "
                               "Morada del Anciano Desvalido de Cadereyta. Se sirven 6,900 servicios de alimentación al mes."),
            direccion="Calle Cóndor 1001, Fracc. Azhara (y 2 puntos más)", ubicacion=maps("Calle Cóndor 1001 Monterrey"), ciudad=mty, organizacion=org["sanjose"],
            modalidad=ModalidadDonacion.ESPECIE, categoria=c_don["Alimentos"],
            meta=Decimal("100"), recaudado=Decimal("25"), whatsapp="8114707350",
            fecha_limite=en_dias(30, 23, 59),
            condiciones_recepcion="Puntos de acopio: 1) Calle Cóndor 1001, Fracc. Azhara. 2) Río Amazonas 327, Del Valle, San Pedro. 3) Fuego 45, Col. Olinca.",
            descripcion_larga=(
                "Recolección de alimentos no perecederos y productos de limpieza para el Asilo con Adultos Mayores en Cadereyta.\n\n"
                "Alimentos: aceite, arroz, frijoles, lentejas, azúcar, avena, atún, productos enlatados, leche, té, café, galletas, gelatina, pasta, saladitas, servilletas, papel de baño.\n\n"
                "Productos de limpieza: escobas, trapeador, bolsas de basura, cloro, fabuloso, pinol, esponjas, jabón líquido, desengrasante."
            ),
            imagenes=imgs("https://base44.app/api/apps/69ed00f78e8b6884c29526e1/files/mp/public/69ed00f78e8b6884c29526e1/28159ef65_exec-ad334238-070b-4802-b0bc-d990edb3e521.png"),
            opciones=[
                DonacionOpcion(titulo="Alimentos no perecederos", monto=Decimal("0")),
                DonacionOpcion(titulo="Productos de limpieza", monto=Decimal("0")),
            ],
            etiquetas=[
                *etiquetas(GrupoEtiqueta.ARTICULO, ["Alimentos", "Limpieza"]),
                *etiquetas(GrupoEtiqueta.DESTINATARIO, ["Adultos Mayores"]),
                *etiquetas(GrupoEtiqueta.CONDICION, ["Nuevo"]),
            ],
        ),

        # 3. Tiempo / Voluntariado
        Donacion(
            titulo="Acompañamiento a Adultos Mayores",
            descripcion_corta=("Asociación civil con 81 años de labor que brinda atención integral y permanente "
                               "a 104 adultos mayores en situación vulnerable."),
            direccion="Hidalgo Sur #637, Zona Centro, Saltillo / Monterrey", ubicacion=maps("Hidalgo Sur 637 Zona Centro Monterrey"), ciudad=mty, organizacion=org["fqs"],
            modalidad=ModalidadDonacion.ESPECIE, categoria=c_don["Salud"],
            meta=Decimal("30"), recaudado=Decimal("12"), whatsapp="8110809078",
            fecha_limite=en_dias(60, 23, 59), horario="Sábados de 10:00 AM a 1:00 PM",
            descripcion_larga=(
                "Asociación civil con 81 años de labor que brinda atención integral y permanente a 104 adultos mayores "
                "en situación vulnerable, muchos de ellos sin familia, pensión ni servicios de salud."
            ),
            imagenes=imgs("https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTS7d1X_t0oN_Z0twQrE4mFovZHz-pUsdlBW--V7YXBQHuK-z7a5BYOokY&s=10"),
        ),
    ])

    # ---------- Hermosillo ----------
    # La app muestra solo lo de la ciudad del perfil: sin esto, un usuario de Hermosillo vería todo vacío.
    db.add_all([
        Actividad(
            titulo="Limpieza del Cerro de la Campana",
            descripcion_corta="Recolección de basura en los senderos del cerro, en familia.",
            direccion="Cerro de la Campana, acceso principal", ubicacion=maps("Cerro de la Campana Hermosillo"),
            ciudad=hmo, organizacion=org["verde"], categoria=c_act["Medio Ambiente"],
            inicia_en=en_dias(7, 7), termina_en=en_dias(7, 10), cupo_total=35,
            acerca_de=("Subiremos temprano para evitar el calor. Se entregan guantes y bolsas; trae agua, "
                       "gorra y bloqueador. Ideal para familias con niños mayores de 8 años."),
        ),
        Actividad(
            titulo="Taller de Lectura en Familia",
            descripcion_corta="Cuentacuentos y juegos de lectura para niños y papás.",
            direccion="Biblioteca Pública, Col. Centro", ubicacion=maps("Biblioteca Pública Hermosillo Centro"),
            ciudad=hmo, organizacion=org["lectores"], categoria=c_act["Educación"],
            inicia_en=en_dias(12, 17), termina_en=en_dias(12, 19), cupo_total=20,
            acerca_de="Lectura en voz alta, manualidades y préstamo de libros para llevar a casa.",
        ),
        Proyecto(
            titulo="Acompañamiento a Adultos Mayores Hermosillo",
            descripcion_corta="Visitas quincenales en familia a adultos mayores que viven solos.",
            direccion="Col. Centro, Hermosillo, Son.", ubicacion=maps("DIF Sonora Hermosillo"),
            ciudad=hmo, organizacion=org["fqs"], estado=EstadoProyecto.ACTIVO,
            beneficiarios="60 adultos mayores",
            acerca_de="Programa de visitas y acompañamiento coordinado con el DIF estatal.",
            como_ayudar="Inscribe a tu familia y te asignamos a una persona para visitar.",
        ),
    ])
    db.add(CentroVisiteo(
        tipo=TipoCentro.CASA_HOGAR,
        nombre="Casa Hogar Rayito de Luz Hermosillo",
        descripcion_corta="Casa hogar que atiende a 30 niñas y niños de 4 a 12 años.",
        informacion_general="Brinda hogar, alimentación y apoyo escolar a niñas y niños sin cuidado parental.",
        direccion="Col. Centro, Hermosillo, Son.", ciudad=hmo,
        ubicacion=maps("Casa Hogar Hermosillo Centro"),
        como_ayudar="Donación de útiles y ropa; tardes de juegos y tareas con los niños.",
        recomendaciones="Agenda tu visita con una semana de anticipación.",
        necesidades=[CentroNecesidad(orden=0, descripcion="Útiles escolares, ropa infantil y leche")],
    ))

    # ---------- Directorio de visiteo ----------
    db.add(CentroVisiteo(
        tipo=TipoCentro.ASILO,
        nombre="Morada del Anciano Desvalido Cadereyta",
        descripcion_corta="Asilo de ancianos donde se atienden 24 horas a 46 adultos mayores.",
        informacion_general=("Atención a adultos mayores en abandono, soledad y falta de apoyo familiar. "
                             "Se les proporciona una vida digna. Se les ofrece refugio, alimentación, "
                             "atención integral y compañía."),
        direccion="Blvd Jose Maria Gonzalez #1000, Cadereyta", ciudad=mty,
        ubicacion="https://www.google.com/maps/search/?api=1&query=Blvd+Jose+Maria+Gonzalez+1000+Cadereyta+Nuevo+Leon",
        como_ayudar="Donación en especie. Visita a los ancianos para convivir y platicar.",
        recomendaciones="Hablar con anticipación para ver que actividades se recomiendan y en que horario.",
        telefono="8282844311", whatsapp="528282844311",
        necesidades=[
            CentroNecesidad(orden=0, descripcion=(
                "Alimentos como: azúcar, leche, aceite, té, gelatina, mole en lata, saladitas, "
                "servilletas, ensure, jugos y frutas")),
            CentroNecesidad(orden=1, descripcion=(
                "Limpieza: trapeadores, cubetas, botes de basura, guantes, cloro, fabuloso, pino, "
                "jabón líquido, shampoo, desengrasantes, bolsas de basura")),
        ],
    ))

    db.commit()
    print("Datos de ejemplo cargados correctamente.")


# =====================================================================
# Comunidad y Pruebas
# =====================================================================

PASSWORD_DEMO = "demo12345"  # solo para la base local de desarrollo


def _usuario_demo(db: Session, nombre: str, email: str, rol: RolUsuario = RolUsuario.USUARIO,
                 password: str = PASSWORD_DEMO, ciudad: str = "Monterrey") -> Usuario:
    """Regresa el usuario con ese correo; si no existe, lo crea (en esa ciudad)."""
    existente = db.scalar(select(Usuario).where(Usuario.email == email))
    if existente:
        return existente
    u = Usuario(nombre=nombre, email=email, password_hash=hashear_password(password),
                ciudad=db.scalar(select(Ciudad).where(Ciudad.nombre == ciudad)), rol=rol)
    db.add(u)
    db.flush()
    return u


def sembrar_comunidad(db: Session) -> None:
    if db.scalar(select(func.count(Publicacion.id))):
        print("Ya hay publicaciones; no se siembra la comunidad.")
        return

    ahora = datetime.now(TZ)

    def hace(dias: int, horas: int = 0) -> datetime:
        return ahora - timedelta(days=dias, hours=horas)

    # ---------- Usuarios demo ----------
    mariana = _usuario_demo(db, "Mariana López", "mariana@demo.familiasquesuman.mx")
    carlos = _usuario_demo(db, "Carlos Treviño", "carlos@demo.familiasquesuman.mx")
    sofia = _usuario_demo(db, "Sofía Garza", "sofia@demo.familiasquesuman.mx")
    jorge = _usuario_demo(db, "Jorge Medina", "jorge@demo.familiasquesuman.mx", ciudad="Hermosillo")

    # Crear familia para Mariana y asociar inscripciones con asistencia para probar encuestas
    familia_mariana = db.scalar(select(Familia).where(Familia.nombre == "Familia López"))
    if not familia_mariana:
        familia_mariana = Familia(nombre="Familia López")
        db.add(familia_mariana)
        db.flush()

    mariana.familia_id = familia_mariana.id

    # Buscar las actividades concluidas creadas en sembrar()
    actividades_concluidas = db.scalars(
        select(Actividad).where(Actividad.titulo.in_([
            "Campaña de Donación de Útiles",
            "Jornada Comunitaria de Limpieza"
        ]))
    ).all()

    for act in actividades_concluidas:
        inscripcion = InscripcionActividad(
            actividad_id=act.id,
            familia_id=familia_mariana.id,
            estado=EstadoInscripcion.CONFIRMADA
        )
        db.add(inscripcion)
        db.flush()

        participante = InscripcionParticipante(
            inscripcion_id=inscripcion.id,
            usuario_id=mariana.id,
            asistencia=EstadoAsistencia.ASISTIO
        )
        db.add(participante)

    # Admin
    admin = db.scalar(select(Usuario).where(Usuario.rol == RolUsuario.ADMIN).order_by(Usuario.creado_en))
    if admin is None:
        # El admin NUNCA usa la contraseña demo: es una cuenta con todos los permisos y la
        # contraseña estaba en el repo. Hay que definir SEED_ADMIN_PASSWORD (y no se imprime).
        password_admin = os.getenv("SEED_ADMIN_PASSWORD", "")
        if len(password_admin) < 12:
            raise SystemExit("Define SEED_ADMIN_PASSWORD (mínimo 12 caracteres) en el .env para crear el admin demo.")
        admin = _usuario_demo(db, "Equipo Familias que Suman", "equipo@demo.familiasquesuman.mx",
                              rol=RolUsuario.ADMIN, password=password_admin)
        print("Admin creado: equipo@demo.familiasquesuman.mx (contraseña: la de SEED_ADMIN_PASSWORD)")

    # Categorías de publicaciones
    def cat(nombre: str) -> Categoria:
        c = db.scalar(select(Categoria).where(
            Categoria.ambito == AmbitoCategoria.PUBLICACION, Categoria.nombre == nombre))
        if c is None:
            c = Categoria(ambito=AmbitoCategoria.PUBLICACION, nombre=nombre)
            db.add(c)
            db.flush()
        return c

    def fotos(*urls: str) -> list[PublicacionImagen]:
        return [PublicacionImagen(url=u, orden=i) for i, u in enumerate(urls)]

    def unsplash(foto: str) -> str:
        return f"https://images.unsplash.com/{foto}?q=80&w=800&auto=format&fit=crop"

    # ---------- Publicaciones de la comunidad ----------
    reforestacion = Publicacion(
        tipo=TipoPublicacion.COMUNIDAD, autor_id=mariana.id, ciudad_id=mariana.ciudad_id, estado=EstadoPublicacion.APROBADA,
        titulo="Nuestra primera reforestación en familia",
        contenido=("El sábado fuimos con los niños a plantar árboles al Parque Central. Plantamos 12 "
                   "encinos y aprendimos a cuidarlos. Los niños ya quieren regresar a ver cómo crecen. "
                   "¡Gracias a Fundación Verde Vivo por organizar!"),
        categoria=cat("Medio Ambiente"), direccion="Parque Central, Monterrey",
        creado_en=hace(6), publicada_en=hace(6), revisado_por=admin.id, revisado_en=hace(6),
        imagenes=fotos(unsplash("photo-1542601906990-b4d3fb778b09"),
                       unsplash("photo-1466692476868-aef1dfb1e735")),
    )
    comedor = Publicacion(
        tipo=TipoPublicacion.COMUNIDAD, autor_id=carlos.id, ciudad_id=mariana.ciudad_id, estado=EstadoPublicacion.APROBADA,
        titulo="Servimos 150 cenas en el Comedor Solidario",
        contenido=("Ayer apoyamos en el Comedor Solidario del Barrio Sur. Entre todos los voluntarios "
                   "preparamos y servimos 150 cenas calientes. Si pueden, vayan: siempre hace falta "
                   "una mano para lavar y servir."),
        categoria=cat("Comedor Solidario"), direccion="Centro Comunitario Barrio Sur",
        creado_en=hace(4), publicada_en=hace(4), revisado_por=admin.id, revisado_en=hace(4),
        imagenes=fotos(unsplash("photo-1488521787991-ed7bbaae773c")),
    )
    lectura = Publicacion(
        tipo=TipoPublicacion.COMUNIDAD, autor_id=sofia.id, ciudad_id=mariana.ciudad_id, estado=EstadoPublicacion.APROBADA,
        titulo="Tarde de cuentos en la Biblioteca Norte",
        contenido=("Mi hija de 8 años leyó en voz alta para niños más pequeños. Fue muy bonito verla "
                   "tan segura. Recomiendo mucho la actividad de Lectura para Niños para ir en familia."),
        categoria=cat("Educación"), direccion="Biblioteca Norte",
        creado_en=hace(3), publicada_en=hace(3), revisado_por=admin.id, revisado_en=hace(3),
        imagenes=fotos(unsplash("photo-1503676260728-1c00da094a0b")),
    )
    asilo = Publicacion(
        tipo=TipoPublicacion.COMUNIDAD, autor_id=jorge.id, ciudad_id=jorge.ciudad_id, estado=EstadoPublicacion.APROBADA,
        titulo="Visita a la Morada del Anciano en Cadereyta",
        contenido=("Llevamos despensa y pasamos la tarde platicando con los abuelitos. Nos contaron "
                   "historias increíbles. Ellos necesitan sobre todo compañía; una visita les cambia el día."),
        categoria=cat("Voluntariado"), direccion="Cadereyta, N.L.",
        creado_en=hace(2), publicada_en=hace(2), revisado_por=admin.id, revisado_en=hace(2),
    )
    salud = Publicacion(
        tipo=TipoPublicacion.COMUNIDAD, autor_id=mariana.id, ciudad_id=mariana.ciudad_id, estado=EstadoPublicacion.APROBADA,
        titulo="Jornada de salud gratuita en la colonia",
        contenido=("Este domingo habrá toma de presión, glucosa y vacunas en el kiosco de la colonia "
                   "Independencia, de 9 a 13 h. Corran la voz con los vecinos."),
        categoria=cat("Salud"), direccion="Col. Independencia, Monterrey",
        creado_en=hace(1, 5), publicada_en=hace(1, 5), revisado_por=admin.id, revisado_en=hace(1, 5),
    )
    colecta = Publicacion(
        tipo=TipoPublicacion.COMUNIDAD, autor_id=carlos.id, ciudad_id=mariana.ciudad_id, estado=EstadoPublicacion.APROBADA,
        titulo=None,
        contenido=("¿Alguien sabe dónde reciben juguetes usados en buen estado? Tenemos varios que "
                   "ya no usan mis hijos y nos gustaría donarlos antes de Navidad."),
        creado_en=hace(0, 6), publicada_en=hace(0, 6), revisado_por=admin.id, revisado_en=hace(0, 6),
    )

    # ---------- Para probar moderación ----------
    pendiente1 = Publicacion(
        tipo=TipoPublicacion.COMUNIDAD, autor_id=sofia.id, ciudad_id=mariana.ciudad_id, estado=EstadoPublicacion.PENDIENTE,
        titulo="Recolecta de útiles escolares",
        contenido=("Estamos juntando cuadernos, colores y mochilas para la escuela San Bernabé. "
                   "Si alguien quiere sumarse, el punto de acopio es la tienda de la esquina de Aztlán."),
        categoria=cat("Educación"), direccion="Col. San Bernabé",
        creado_en=hace(0, 3),
    )
    pendiente2 = Publicacion(
        tipo=TipoPublicacion.COMUNIDAD, autor_id=jorge.id, ciudad_id=jorge.ciudad_id, estado=EstadoPublicacion.PENDIENTE,
        titulo="Limpieza del río Santa Catarina",
        contenido="Propongo organizar una limpieza del río el próximo mes. ¿Quién se apunta?",
        categoria=cat("Medio Ambiente"), creado_en=hace(0, 1),
    )
    rechazada = Publicacion(
        tipo=TipoPublicacion.COMUNIDAD, autor_id=jorge.id, ciudad_id=jorge.ciudad_id, estado=EstadoPublicacion.RECHAZADA,
        titulo="Vendo bicicleta",
        contenido="Vendo bicicleta rodada 26 en buen estado, interesados mándenme mensaje.",
        motivo_rechazo="La comunidad es solo para voluntariado y ayuda; no se permiten ventas.",
        creado_en=hace(2, 4), revisado_por=admin.id, revisado_en=hace(2),
    )

    # ---------- Avisos oficiales ----------
    aviso_evento = Publicacion(
        tipo=TipoPublicacion.OFICIAL, autor_id=admin.id, estado=EstadoPublicacion.APROBADA,
        titulo="Gran Colecta de Invierno 2026",
        contenido=("Familias que Suman organiza su colecta anual de cobijas y ropa abrigadora. "
                   "Habrá centros de acopio en Monterrey y San Pedro. ¡Te esperamos con tu familia!"),
        evento_inicia_en=ahora + timedelta(days=10), evento_termina_en=ahora + timedelta(days=10, hours=6),
        publico_objetivo="Todas las familias",
        creado_en=hace(1), publicada_en=hace(1),
        imagenes=fotos(unsplash("photo-1434389677669-e08b4cac3105")),
    )
    aviso_guia = Publicacion(
        tipo=TipoPublicacion.OFICIAL, autor_id=admin.id, estado=EstadoPublicacion.APROBADA,
        titulo="Guía para tu primera visita a un asilo",
        contenido=("Preparamos una guía con recomendaciones para visitar asilos y casas hogar en "
                   "familia: qué llevar, cómo platicar con los adultos mayores y qué evitar."),
        publico_objetivo="Familias con niños",
        documento_url="https://www.familiasquesuman.mx/guias/primera-visita.pdf",
        documento_nombre="Guía primera visita.pdf",
        creado_en=hace(5), publicada_en=hace(5),
    )
    aviso_app = Publicacion(
        tipo=TipoPublicacion.OFICIAL, autor_id=admin.id, estado=EstadoPublicacion.APROBADA,
        titulo="Nuevo: asistente en la app",
        contenido=("Ya puedes preguntarle al asistente por actividades, proyectos, donaciones y "
                   "centros para visitar. Lo encuentras en el botón de chat."),
        creado_en=hace(0, 2), publicada_en=hace(0, 2),
    )

    publicaciones = [reforestacion, comedor, lectura, asilo, salud, colecta,
                     pendiente1, pendiente2, rechazada, aviso_evento, aviso_guia, aviso_app]
    db.add_all(publicaciones)
    db.flush()

    # ---------- Likes ----------
    def likes(pub: Publicacion, *usuarios: Usuario) -> None:
        db.add_all([PublicacionLike(publicacion_id=pub.id, usuario_id=u.id) for u in usuarios])

    likes(reforestacion, carlos, sofia, jorge)
    likes(comedor, mariana, sofia)
    likes(lectura, mariana, carlos, jorge)
    likes(asilo, sofia)
    likes(salud, carlos, jorge)

    # ---------- Comentarios ----------
    def comentar(pub: Publicacion, autor: Usuario, texto: str, horas_despues: int,
                 le_gusta_a: tuple[Usuario, ...] = (), visible: bool = True) -> Comentario:
        c = Comentario(publicacion_id=pub.id, autor_id=autor.id, contenido=texto, visible=visible,
                       creado_en=(pub.publicada_en or pub.creado_en) + timedelta(hours=horas_despues))
        db.add(c)
        db.flush()
        db.add_all([ComentarioLike(comentario_id=c.id, usuario_id=u.id) for u in le_gusta_a])
        return c

    comentar(reforestacion, carlos, "¡Qué padre! ¿Cuándo es la siguiente jornada?", 2, (mariana,))
    comentar(reforestacion, mariana, "Creo que el próximo mes, la publican en Actividades.", 3, (carlos, sofia))
    comentar(reforestacion, sofia, "Nos apuntamos la próxima vez.", 5)
    comentar(comedor, jorge, "Gracias por compartir, el sábado vamos con mis hijos.", 1, (carlos,))
    comentar(lectura, carlos, "Qué bonito, felicidades a tu hija.", 2, (sofia,))
    comentar(lectura, jorge, "Mi hijo también quiere participar.", 6)
    comentar(asilo, mariana, "¿Qué es lo que más necesitan llevar?", 1)
    comentar(asilo, jorge, "Leche, ensure y artículos de limpieza. Viene todo en el Directorio.", 2, (mariana,))
    comentar(colecta, sofia, "En Quiero Donar hay una campaña que recibe juguetes, revísala.", 1, (carlos,))
    comentar(colecta, jorge, "Comentario ocultado por moderación.", 2, visible=False)

    db.commit()
    print(f"Comunidad cargada: {len(publicaciones)} publicaciones, usuarios demo con contraseña "
          f"'{PASSWORD_DEMO}' (ej. mariana@demo.familiasquesuman.mx).")


if __name__ == "__main__":
    # Los datos demo traen cuentas con contraseña conocida: nunca en producción
    if settings.es_prod:
        raise SystemExit("ENTORNO=prod: la semilla de datos demo está deshabilitada en producción.")
    # Se revisa antes de sembrar nada, para no dejar la base a medias
    if len(os.getenv("SEED_ADMIN_PASSWORD", "")) < 12:
        raise SystemExit("Define SEED_ADMIN_PASSWORD (mínimo 12 caracteres) en el .env para crear el admin demo.")
    engine = create_engine(settings.database_url_sync)
    with Session(engine) as db:
        sembrar(db)
        sembrar_comunidad(db)