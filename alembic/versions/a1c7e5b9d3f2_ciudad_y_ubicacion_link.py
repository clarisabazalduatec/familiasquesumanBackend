"""ciudad (FK) + ubicacion (link de Google Maps) en todo

Revision ID: a1c7e5b9d3f2
Revises: c4b66733d154
"""
from alembic import op
import sqlalchemy as sa

revision = "a1c7e5b9d3f2"
down_revision = "c4b66733d154"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- iniciativas (actividades, proyectos, donaciones) ----
    op.alter_column("iniciativas", "ubicacion", new_column_name="direccion")
    op.add_column("iniciativas", sa.Column("ubicacion", sa.String(500), nullable=True))
    # Los formularios guardaban "Monterrey, Nuevo León" en el texto: se usa para acomodar la ciudad real
    op.execute("""UPDATE iniciativas i SET ciudad_id = c.id FROM ciudades c
                  WHERE i.direccion ILIKE c.nombre || '%'""")

    # ---- publicaciones ----
    op.alter_column("publicaciones", "ubicacion", new_column_name="direccion")
    op.add_column("publicaciones", sa.Column("ciudad_id", sa.Integer(), nullable=True))
    op.add_column("publicaciones", sa.Column("ubicacion", sa.String(500), nullable=True))
    op.create_foreign_key("fk_publicaciones_ciudad_id", "publicaciones", "ciudades", ["ciudad_id"], ["id"])
    op.create_index("ix_publicaciones_ciudad_id", "publicaciones", ["ciudad_id"])
    op.execute("""UPDATE publicaciones p SET ciudad_id = c.id FROM ciudades c
                  WHERE p.direccion ILIKE c.nombre || '%'""")

    # ---- centros: mapa_url -> ubicacion ----
    op.alter_column("centros_visiteo", "mapa_url", new_column_name="ubicacion")

    # ---- usuarios: ubicacion (texto) -> ciudad_id ----
    op.add_column("usuarios", sa.Column("ciudad_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_usuarios_ciudad_id", "usuarios", "ciudades", ["ciudad_id"], ["id"])
    op.create_index("ix_usuarios_ciudad_id", "usuarios", ["ciudad_id"])
    op.execute("""UPDATE usuarios u SET ciudad_id = c.id FROM ciudades c
                  WHERE u.ubicacion ILIKE c.nombre || '%'""")
    op.drop_column("usuarios", "ubicacion")


def downgrade() -> None:
    op.add_column("usuarios", sa.Column("ubicacion", sa.String(120), nullable=True))
    op.execute("UPDATE usuarios u SET ubicacion = c.nombre FROM ciudades c WHERE u.ciudad_id = c.id")
    op.drop_index("ix_usuarios_ciudad_id", table_name="usuarios")
    op.drop_constraint("fk_usuarios_ciudad_id", "usuarios", type_="foreignkey")
    op.drop_column("usuarios", "ciudad_id")

    op.alter_column("centros_visiteo", "ubicacion", new_column_name="mapa_url")

    op.drop_index("ix_publicaciones_ciudad_id", table_name="publicaciones")
    op.drop_constraint("fk_publicaciones_ciudad_id", "publicaciones", type_="foreignkey")
    op.drop_column("publicaciones", "ubicacion")
    op.drop_column("publicaciones", "ciudad_id")
    op.alter_column("publicaciones", "direccion", new_column_name="ubicacion")

    op.drop_column("iniciativas", "ubicacion")
    op.alter_column("iniciativas", "direccion", new_column_name="ubicacion")