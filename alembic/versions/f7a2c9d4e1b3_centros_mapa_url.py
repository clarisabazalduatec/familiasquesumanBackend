"""centros_visiteo: mapa_url

- Agrega centros_visiteo.mapa_url: link a Google Maps (u otro servicio de mapas) que abre
  el botón "Cómo llegar". La columna `direccion` se queda como el texto que se muestra.
- Le pone el link al centro del seed (si no existe en la base, el UPDATE no hace nada).

Revision ID: f7a2c9d4e1b3
Revises: e3b8c5d1a2f4
Create Date: 2026-10-14 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "f7a2c9d4e1b3"
down_revision = "e3b8c5d1a2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("centros_visiteo", sa.Column("mapa_url", sa.String(length=500), nullable=True))

    centros = sa.table(
        "centros_visiteo",
        sa.column("nombre", sa.String()),
        sa.column("mapa_url", sa.String()),
    )
    op.execute(
        centros.update()
        .where(centros.c.nombre == "Morada del Anciano Desvalido Cadereyta")
        .values(mapa_url="https://www.google.com/maps/search/?api=1&query=Blvd+Jose+Maria+Gonzalez+1000+Cadereyta+Nuevo+Leon")
    )


def downgrade() -> None:
    op.drop_column("centros_visiteo", "mapa_url")
