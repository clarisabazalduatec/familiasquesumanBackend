"""donaciones: recaudado y organizacion_nombre

El modelo Donacion ya usaba estas columnas, pero ninguna migración las creaba:
en una base nueva GET /donaciones daba 500 ("column donaciones.recaudado does not exist").
Usa IF NOT EXISTS porque en algunas bases ya se agregaron a mano.

Revision ID: b3d9e2f4a6c8
Revises: f1a8c3d5e7b9
Create Date: 2026-10-18 11:30:00.000000

"""
from alembic import op


revision = "b3d9e2f4a6c8"
down_revision = "f1a8c3d5e7b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE donaciones ADD COLUMN IF NOT EXISTS recaudado NUMERIC(12, 2) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE donaciones ADD COLUMN IF NOT EXISTS organizacion_nombre VARCHAR(200)")
    op.execute("ALTER TABLE donaciones DROP CONSTRAINT IF EXISTS ck_donaciones_recaudado_no_negativo")
    op.execute(
        "ALTER TABLE donaciones ADD CONSTRAINT ck_donaciones_recaudado_no_negativo CHECK (recaudado >= 0)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE donaciones DROP CONSTRAINT IF EXISTS ck_donaciones_recaudado_no_negativo")
    op.execute("ALTER TABLE donaciones DROP COLUMN IF EXISTS organizacion_nombre")
    op.execute("ALTER TABLE donaciones DROP COLUMN IF EXISTS recaudado")