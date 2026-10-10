"""hacer usuario_id opcional en mensajes_chat

Revision ID: cca53aec61fa
Revises: cf4c5737091f
Create Date: 2026-10-10 01:40:22.809724

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cca53aec61fa'
down_revision = 'cf4c5737091f'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.alter_column(
        "mensajes_chat",
        "usuario_id",
        existing_type=sa.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "mensajes_chat",
        "usuario_id",
        existing_type=sa.UUID(),
        nullable=False,
    )