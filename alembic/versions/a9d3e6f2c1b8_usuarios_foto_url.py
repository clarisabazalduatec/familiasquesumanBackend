"""usuarios: foto_url

- Agrega usuarios.foto_url: clave en el almacén de la foto de perfil ("abc.jpg").
  Es opcional: los usuarios que ya existen quedan sin foto (la app muestra sus iniciales).

Revision ID: a9d3e6f2c1b8
Revises: b5e2d8f1c4a7
Create Date: 2026-10-16 13:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a9d3e6f2c1b8"
down_revision = "b5e2d8f1c4a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("foto_url", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("usuarios", "foto_url")