"""agregar_tiempo_a_modalidad

Revision ID: 90afee3b1af5
Revises: e6c2f9a1b4d7
Create Date: 2026-10-21 04:28:57.897801

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '90afee3b1af5'
down_revision = 'e6c2f9a1b4d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE donaciones DROP CONSTRAINT IF EXISTS modalidad_donacion;")
    op.execute("ALTER TABLE donaciones ADD CONSTRAINT modalidad_donacion CHECK (modalidad IN ('CAMPANA', 'ESPECIE', 'TIEMPO'));")

def downgrade() -> None:
    op.execute("ALTER TABLE donaciones DROP CONSTRAINT IF EXISTS modalidad_donacion;")
    op.execute("ALTER TABLE donaciones ADD CONSTRAINT modalidad_donacion CHECK (modalidad IN ('CAMPANA', 'ESPECIE'));")