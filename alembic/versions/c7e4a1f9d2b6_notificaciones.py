"""notificaciones

- Crea la tabla notificaciones: la campana de la app y los avisos locales del celular
  (WorkManager pide las nuevas con ?despues_de=<último id>).
- uq_notificacion_clave evita duplicados (recordatorios, cupo lleno, likes agrupados).

Revision ID: c7e4a1f9d2b6
Revises: a9d3e6f2c1b8
Create Date: 2026-10-16 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c7e4a1f9d2b6"
down_revision = "a9d3e6f2c1b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notificaciones",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column(
            "usuario_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("titulo", sa.String(length=150), nullable=False),
        sa.Column("cuerpo", sa.String(length=500), nullable=False),
        sa.Column("destino_tipo", sa.String(length=30), nullable=True),
        sa.Column("destino_id", sa.String(length=64), nullable=True),
        sa.Column("clave", sa.String(length=120), nullable=True),
        sa.Column("leida", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("usuario_id", "clave", name="uq_notificacion_clave"),
    )
    op.create_index("ix_notificaciones_usuario_id_id", "notificaciones", ["usuario_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_notificaciones_usuario_id_id", table_name="notificaciones")
    op.drop_table("notificaciones")