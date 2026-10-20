"""crear_tabla_encuesta_inicial

Revision ID: 02774f70b5bd
Revises: a1c7e5b9d3f2
Create Date: 2026-10-20 06:20:34.696747

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '02774f70b5bd'
down_revision = 'a1c7e5b9d3f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('encuesta_inicial_actividad',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('usuario_id', sa.Uuid(), nullable=False),    # Tipo UUID
        sa.Column('actividad_id', sa.Uuid(), nullable=False),  # Tipo UUID
        sa.Column('motivos', sa.JSON(), nullable=True),
        sa.Column('otro_motivo', sa.String(), nullable=True),
        sa.Column('expectativas', sa.JSON(), nullable=True),
        sa.Column('otra_expectativa', sa.String(), nullable=True),
        sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['actividad_id'], ['iniciativas.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('encuesta_inicial_actividad')