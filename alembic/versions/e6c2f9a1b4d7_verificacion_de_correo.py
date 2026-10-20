"""verificación de correo al registrarse

Revision ID: e6c2f9a1b4d7
Revises: 9b7d3e1f5a2c (merge de seguridad + encuesta inicial)

- usuarios.correo_verificado (false para cuentas nuevas)
- verificaciones_correo: el código pendiente de cada usuario (solo su hash)
Las cuentas que YA existen se marcan como verificadas para no bloquearlas.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e6c2f9a1b4d7"
down_revision = "9b7d3e1f5a2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usuarios",
        sa.Column("correo_verificado", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute("UPDATE usuarios SET correo_verificado = true")

    op.create_table(
        "verificaciones_correo",
        sa.Column("usuario_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("codigo_hash", sa.String(64), nullable=False),
        sa.Column("sal", sa.String(32), nullable=False),
        sa.Column("enviado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intentos", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("verificaciones_correo")
    op.drop_column("usuarios", "correo_verificado")
