"""merge: seguridad (e8f2a4c6b1d3) + encuesta inicial (02774f70b5bd)

Las dos migraciones salieron de a1c7e5b9d3f2 al mismo tiempo y dejaron dos "heads".
Esta las une en una sola línea.

Además: 02774f70b5bd crea la tabla `encuesta_inicial_actividad` (singular), pero el modelo
EncuestaInicialActividad usa `encuestas_iniciales_actividad` (plural), que es la que crea y
arregla e8f2a4c6b1d3. La singular no la usa ningún código, así que aquí se borra si está vacía.
Si por algo tuviera datos, se deja para revisarla a mano.

Revision ID: 9b7d3e1f5a2c
Revises: e8f2a4c6b1d3, 02774f70b5bd
Create Date: 2026-10-20 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9b7d3e1f5a2c"
down_revision = ("e8f2a4c6b1d3", "02774f70b5bd")
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if sa.inspect(conn).has_table("encuesta_inicial_actividad"):
        filas = conn.execute(sa.text("SELECT count(*) FROM encuesta_inicial_actividad")).scalar()
        if filas == 0:
            op.drop_table("encuesta_inicial_actividad")


def downgrade() -> None:
    pass
