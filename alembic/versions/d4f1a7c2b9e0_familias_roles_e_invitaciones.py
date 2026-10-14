"""familias, roles e invitaciones

- usuarios: rol (USUARIO/ADMIN), familia_id, parentesco
- familias
- familia_menores
- invitaciones_familia

Revision ID: d4f1a7c2b9e0
Revises: cca53aec61fa
Create Date: 2026-10-13 16:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d4f1a7c2b9e0"
down_revision = "cca53aec61fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- familias (va primero porque usuarios.familia_id la referencia) ---
    op.create_table(
        "familias",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- usuarios: rol, familia_id, parentesco ---
    # Las filas existentes quedan como USUARIO gracias al server_default.
    op.add_column(
        "usuarios",
        sa.Column("rol", sa.String(length=30), server_default="USUARIO", nullable=False),
    )
    op.create_check_constraint("rol_usuario", "usuarios", "rol IN ('USUARIO', 'ADMIN')")

    op.add_column("usuarios", sa.Column("familia_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_usuarios_familia_id", "usuarios", "familias", ["familia_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_usuarios_familia_id", "usuarios", ["familia_id"])

    op.add_column("usuarios", sa.Column("parentesco", sa.String(length=30), nullable=True))
    op.create_check_constraint(
        "parentesco", "usuarios", "parentesco IN ('MAMA', 'PAPA', 'TUTOR', 'ABUELO', 'OTRO')"
    )

    # --- familia_menores ---
    op.create_table(
        "familia_menores",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("familia_id", sa.UUID(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("fecha_nacimiento", sa.Date(), nullable=False),
        sa.Column("registrado_por_id", sa.UUID(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["familia_id"], ["familias.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["registrado_por_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_familia_menores_familia_id", "familia_menores", ["familia_id"])

    # --- invitaciones_familia ---
    op.create_table(
        "invitaciones_familia",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("familia_id", sa.UUID(), nullable=False),
        sa.Column("invitado_id", sa.UUID(), nullable=False),
        sa.Column("invitado_por_id", sa.UUID(), nullable=True),
        sa.Column(
            "estado",
            sa.Enum(
                "PENDIENTE", "ACEPTADA", "RECHAZADA", "CANCELADA",
                name="estado_invitacion", native_enum=False, create_constraint=True, length=30,
            ),
            server_default="PENDIENTE",
            nullable=False,
        ),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("respondida_en", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["familia_id"], ["familias.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invitado_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invitado_por_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invitaciones_familia_familia_id", "invitaciones_familia", ["familia_id"])
    op.create_index("ix_invitaciones_familia_invitado_id", "invitaciones_familia", ["invitado_id"])
    op.create_index(
        "uq_invitacion_pendiente",
        "invitaciones_familia",
        ["familia_id", "invitado_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'PENDIENTE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_invitacion_pendiente", table_name="invitaciones_familia")
    op.drop_index("ix_invitaciones_familia_invitado_id", table_name="invitaciones_familia")
    op.drop_index("ix_invitaciones_familia_familia_id", table_name="invitaciones_familia")
    op.drop_table("invitaciones_familia")

    op.drop_index("ix_familia_menores_familia_id", table_name="familia_menores")
    op.drop_table("familia_menores")

    op.drop_constraint("parentesco", "usuarios", type_="check")
    op.drop_column("usuarios", "parentesco")
    op.drop_index("ix_usuarios_familia_id", table_name="usuarios")
    op.drop_constraint("fk_usuarios_familia_id", "usuarios", type_="foreignkey")
    op.drop_column("usuarios", "familia_id")
    op.drop_constraint("rol_usuario", "usuarios", type_="check")
    op.drop_column("usuarios", "rol")

    op.drop_table("familias")