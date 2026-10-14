"""proyectos: como_ayudar e instagram_url

- Agrega proyectos.como_ayudar (recuadro "¿Cómo ayudar?") e instagram_url ("Síguenos en").
- Acomoda los textos de los 2 proyectos del seed al uso acordado de cada campo:
    descripcion_corta -> tarjeta de la lista y línea bajo el título del detalle
    acerca_de         -> sección "Acerca del proyecto"
    descripcion_larga -> sección "Descripción"
  (si esos proyectos no existen en la base, los UPDATE no hacen nada)

Revision ID: e3b8c5d1a2f4
Revises: d4f1a7c2b9e0
Create Date: 2026-10-13 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e3b8c5d1a2f4"
down_revision = "d4f1a7c2b9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("proyectos", sa.Column("como_ayudar", sa.Text(), nullable=True))
    op.add_column("proyectos", sa.Column("instagram_url", sa.String(length=300), nullable=True))

    # ---------- datos del seed ----------
    proyectos = sa.table(
        "proyectos",
        sa.column("iniciativa_id", sa.UUID()),
        sa.column("acerca_de", sa.Text()),
        sa.column("descripcion_larga", sa.Text()),
        sa.column("como_ayudar", sa.Text()),
        sa.column("whatsapp", sa.String()),
        sa.column("telefono", sa.String()),
    )
    iniciativas = sa.table(
        "iniciativas",
        sa.column("id", sa.UUID()),
        sa.column("titulo", sa.String()),
        sa.column("descripcion_corta", sa.String()),
    )

    def id_de(titulo: str):
        return sa.select(iniciativas.c.id).where(iniciativas.c.titulo == titulo).scalar_subquery()

    trazo = "Trazo... Escribiendo una nueva historia"
    op.execute(
        iniciativas.update()
        .where(iniciativas.c.titulo == trazo)
        .values(descripcion_corta="Voluntariado que visita a mujeres en el penal de Escobedo.")
    )
    op.execute(
        proyectos.update()
        .where(proyectos.c.iniciativa_id == id_de(trazo))
        .values(
            acerca_de=(
                "Trazo es un voluntariado que nace de la Asociación Renace, desde hace más de 2 años "
                "lleva pláticas de desarrollo humano y cursos de acuarela y caligrafía a mujeres "
                "privadas de la libertad quienes al final del semestre reciben un reconocimiento el "
                "cual les ayuda en su expediente judicial."
            ),
            descripcion_larga=(
                "Somos un grupo de mujeres voluntarias que realizamos visitas quincenales al Centro de "
                "Reinserción Social de Escobedo para acompañar a mujeres privadas de la libertad "
                "mediante pláticas de desarrollo humano, talleres de acuarela y actividades que "
                "fortalecen su autoestima, creatividad y crecimiento personal.\n\n"
                "En cada encuentro buscamos ofrecer un espacio de escucha, aprendizaje y esperanza, "
                "recordándoles que siempre es posible comenzar de nuevo."
            ),
        )
    )

    dif = "Voluntariado DIF Te Acompaña"
    op.execute(
        iniciativas.update()
        .where(iniciativas.c.titulo == dif)
        .values(descripcion_corta="Acompañar a personas vulnerables.")
    )
    op.execute(
        proyectos.update()
        .where(proyectos.c.iniciativa_id == id_de(dif))
        .values(
            acerca_de=(
                "El voluntariado existe desde hace varios años y se busca apoyar a personas "
                "vulnerables con una visita o ayuda con alimentos, medicinas o acompañamiento."
            ),
            descripcion_larga=(
                "Acompañar a adultos mayores o jóvenes vulnerables, en soledad, con discapacidad o con "
                "una red de apoyo reducida. Realizar visitas en familia mínimo una vez cada 15 días. "
                "Se les puede asistir en compras de alimentos, medicamentos o solo una visita."
            ),
            como_ayudar=(
                "Inscribir a su familia para que el Voluntariado les asigne una persona para visitar "
                "o acompañar."
            ),
            whatsapp="5218113008725",
            telefono="8113008725",
        )
    )


def downgrade() -> None:
    op.drop_column("proyectos", "instagram_url")
    op.drop_column("proyectos", "como_ayudar")