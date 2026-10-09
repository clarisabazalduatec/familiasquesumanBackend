"""Carga los datos de ejemplo (los antiguos mocks de la app) en PostgreSQL.

Uso:  docker compose exec api python -m app.seed
Es idempotente: si ya hay ciudades, no hace nada.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Actividad, AmbitoCategoria, Categoria, CentroNecesidad, CentroVisiteo, Ciudad,
    Donacion, DonacionEtiqueta, DonacionOpcion, EstadoProyecto, GrupoEtiqueta,
    IniciativaImagen, ModalidadDonacion, Organizacion, Proyecto, ProyectoOpcionApoyo,
    TipoApoyo, TipoCentro,
)

# Monterrey/Hermosillo: UTC-6 todo el año (sin horario de verano)
TZ = timezone(timedelta(hours=-6))


def dt(mes: int, dia: int, hora: int, minuto: int = 0, anio: int = 2026) -> datetime:
    return datetime(anio, mes, dia, hora, minuto, tzinfo=TZ)


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

    # ---------- Actividades ----------
    db.add_all([
        Actividad(
            titulo="Reforestación Parque Central",
            descripcion_corta="Únete a la jornada de plantación de árboles nativos.",
            ubicacion="Parque Central, Puerta Norte", ciudad=mty, organizacion=org["verde"],
            categoria=c_act["Medio Ambiente"], inicia_en=dt(10, 24, 9), termina_en=dt(10, 24, 13),
            cupo_total=50,
            acerca_de=("Únete a nosotros para restaurar el pulmón de nuestra ciudad. Durante esta "
                       "jornada, las familias plantarán árboles autóctonos y aprenderán sobre la "
                       "importancia de la biodiversidad local."),
        ),
        Actividad(
            titulo="Lectura para Niños",
            descripcion_corta="Apoya como voluntario en el círculo de lectura comunitaria.",
            ubicacion="Biblioteca Norte", ciudad=mty, organizacion=org["lectores"],
            categoria=c_act["Educación"], inicia_en=dt(10, 25, 10), termina_en=dt(10, 25, 12),
            cupo_total=20,
            acerca_de=("Apoya como voluntario leyendo cuentos a niños de la comunidad. Ayudaremos a "
                       "fomentar el hábito de la lectura y la imaginación en los más pequeños."),
        ),
        Actividad(
            titulo="Comedor Solidario",
            descripcion_corta="Colabora en la preparación y entrega de alimentos a quienes más lo necesitan.",
            ubicacion="Centro Comunitario", ciudad=mty, organizacion=org["manos"],
            categoria=c_act["Apoyo Social"], inicia_en=dt(10, 28, 16), termina_en=dt(10, 28, 19),
            cupo_total=30,
            acerca_de=("Colabora en la preparación y entrega de alimentos a quienes más lo necesitan "
                       "en nuestra comunidad. Toda ayuda es bienvenida para servir cenas calientes."),
        ),
    ])

    # ---------- Proyectos ----------
    db.add_all([
        Proyecto(
            titulo="Trazo... Escribiendo una nueva historia",
            descripcion_corta=("Somos un grupo de mujeres voluntarias que realizamos visitas quincenales "
                               "al Centro de Reinserción Social de Escobedo para acompañar a mujeres "
                               "privadas de la libertad."),
            ubicacion="Monterrey", ciudad=mty, organizacion=org["fqs"],
            estado=EstadoProyecto.ACTIVO, beneficiarios="25 Mujeres",
            acerca_de="Voluntariado que visita a mujeres en el penal de Escobedo.",
            descripcion_larga=(
                "Trazo es un voluntariado que nace de la Asociación Renace, desde hace más de 2 años "
                "lleva pláticas de desarrollo humano y cursos de acuarela y caligrafía a mujeres "
                "privadas de la libertad quienes al final del semestre reciben un reconocimiento el "
                "cual les ayuda en su expediente judicial.\n\nEn cada encuentro buscamos ofrecer un "
                "espacio de escucha, aprendizaje y esperanza, recordándoles que siempre es posible "
                "comenzar de nuevo."),
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
            descripcion_corta=("Acompañar a adultos mayores o jóvenes vulnerables, en soledad, con "
                               "discapacidad o con una red de apoyo reducida."),
            ubicacion="San Pedro Garza García", ciudad=mty, organizacion=org["fqs"],
            estado=EstadoProyecto.ACTIVO, beneficiarios="200 adultos mayores",
            acerca_de="Acompañamiento a adultos mayores en situación de vulnerabilidad.",
            descripcion_larga=("Acompañar a adultos mayores o jóvenes vulnerables, en soledad, con "
                               "discapacidad o con una red de apoyo reducida. Realizar visitas en "
                               "familia mínimo una vez cada 15 días."),
        ),
    ])

    # ---------- Donaciones: campañas ----------
    db.add_all([
        Donacion(
            titulo="Comedor Solidario Barrio Sur",
            descripcion_corta=("Ayúdanos a asegurar 500 raciones semanales para familias en situación "
                               "de vulnerabilidad."),
            ubicacion=None, ciudad=mty, organizacion=org["fqs"],
            modalidad=ModalidadDonacion.CAMPANA, meta=Decimal("6000"), whatsapp="528112345678",
            descripcion_larga=("El Comedor Solidario Barrio Sur atiende a más de 120 familias "
                               "diariamente. Con tu apoyo, aseguraremos los insumos básicos para brindar "
                               "comidas calientes durante los próximos 3 meses.\n\nHorario de atención: "
                               "Lunes a Viernes de 8:00 AM a 4:00 PM."),
            imagenes=imgs("https://images.unsplash.com/photo-1488521787991-ed7bbaae773c?q=80&w=600&auto=format&fit=crop"),
            opciones=[
                DonacionOpcion(titulo="Despensa básica", monto=Decimal("350")),
                DonacionOpcion(titulo="Apoyo semanal para 1 familia", monto=Decimal("700")),
                DonacionOpcion(titulo="Insumos para el comedor (1 día)", monto=Decimal("2500")),
            ],
        ),
        Donacion(
            titulo="Uniformes Escolares Comunitarios",
            descripcion_corta="Dona para equipar con uniformes a 100 estudiantes de primaria en zonas rurales.",
            ciudad=mty, organizacion=org["fqs"],
            modalidad=ModalidadDonacion.CAMPANA, meta=Decimal("50000"), whatsapp="528112345678",
            descripcion_larga=("Buscamos proveer un kit completo (pantalón/falda, camisa, suéter y "
                               "zapatos) a 100 niños y niñas para que la falta de uniforme no sea un "
                               "impedimento en su educación."),
            imagenes=imgs("https://images.unsplash.com/photo-1503676260728-1c00da094a0b?q=80&w=600&auto=format&fit=crop"),
        ),
    ])

    # ---------- Donaciones: en especie ----------
    def etiquetas(grupo: GrupoEtiqueta, valores: list[str]) -> list[DonacionEtiqueta]:
        return [DonacionEtiqueta(grupo=grupo, valor=v) for v in valores]

    db.add_all([
        Donacion(
            titulo="Tablets para Aprender",
            descripcion_corta=("Equipamiento del aula digital de la Escuela No. 4 para que la clase "
                               "completa pueda aprender y crecer."),
            ubicacion="Av. Alfonso Reyes 100, Zona Poniente, Monterrey, N.L.",
            ciudad=mty, organizacion=org["sanber"],
            modalidad=ModalidadDonacion.ESPECIE, categoria=c_don["Electrónicos"],
            whatsapp="8110809078",
            condiciones_recepcion="Pantalla intacta, Wi-Fi funcional y de preferencia cargador incluido.",
            imagenes=imgs("https://images.unsplash.com/photo-1561154464-82e9adf32764?q=80&w=600&auto=format&fit=crop"),
            etiquetas=[
                *etiquetas(GrupoEtiqueta.ARTICULO, ["Tablets", "Cargadores", "Electrónicos"]),
                *etiquetas(GrupoEtiqueta.DESTINATARIO, ["Estudiantes", "Niños"]),
                *etiquetas(GrupoEtiqueta.CONDICION, ["Nuevo", "Usado en buen estado"]),
                *etiquetas(GrupoEtiqueta.METODO_ENTREGA, ["Entrega en el centro", "Recolección"]),
            ],
        ),
        Donacion(
            titulo="Abrigos y Cobijas de Invierno",
            descripcion_corta=("Colecta de prendas abrigadoras y cobijas limpias para apoyar a familias "
                               "y adultos mayores del sector."),
            ubicacion="Av. Aztlán 2304, Col. San Bernabé, Monterrey, N.L.",
            ciudad=mty, organizacion=org["sanjose"],
            modalidad=ModalidadDonacion.ESPECIE, categoria=c_don["Ropa"],
            whatsapp="8181234567",
            condiciones_recepcion="Entregar prendas limpias, desinfectadas y en bolsas cerradas.",
            imagenes=imgs("https://images.unsplash.com/photo-1434389677669-e08b4cac3105?q=80&w=600&auto=format&fit=crop"),
            etiquetas=[
                *etiquetas(GrupoEtiqueta.ARTICULO, ["Ropa de Invierno", "Cobijas", "Calzado"]),
                *etiquetas(GrupoEtiqueta.DESTINATARIO, ["Familias", "Adultos Mayores", "Niños"]),
                *etiquetas(GrupoEtiqueta.CONDICION, ["Nuevo", "Usado en buen estado"]),
                *etiquetas(GrupoEtiqueta.METODO_ENTREGA, ["Entrega en el centro"]),
            ],
        ),
    ])

    # ---------- Directorio de visiteo ----------
    db.add(CentroVisiteo(
        tipo=TipoCentro.ASILO,
        nombre="Morada del Anciano Desvalido Cadereyta",
        descripcion_corta="Asilo de ancianos donde se atienden 24 horas a 46 adultos mayores.",
        informacion_general=("Atención a adultos mayores en abandono, soledad y falta de apoyo familiar. "
                             "Se les proporciona una vida digna. Se les ofrece refugio, alimentación, "
                             "atención integral y compañía."),
        direccion="Blvd Jose Maria Gonzalez #1000, Cadereyta", ciudad=mty,
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


if __name__ == "__main__":
    engine = create_engine(settings.database_url_sync)
    with Session(engine) as db:
        sembrar(db)