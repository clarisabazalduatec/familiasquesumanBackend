"""lista de espera en inscripciones

Revision ID: f1a8c3d5e7b9
Revises: 4aaeee5f0640
"""
from alembic import op
import sqlalchemy as sa

revision = "f1a8c3d5e7b9"
down_revision = "4aaeee5f0640"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("estado_inscripcion", "inscripciones_actividad", type_="check")
    op.create_check_constraint(
        "estado_inscripcion", "inscripciones_actividad",
        "estado IN ('CONFIRMADA', 'EN_ESPERA', 'CANCELADA')",
    )
    op.add_column("inscripciones_actividad",
                  sa.Column("en_espera_desde", sa.DateTime(timezone=True), nullable=True))

    op.drop_index("uq_inscripcion_confirmada", table_name="inscripciones_actividad")
    op.create_index(
        "uq_inscripcion_activa", "inscripciones_actividad", ["actividad_id", "familia_id"],
        unique=True, postgresql_where=sa.text("estado IN ('CONFIRMADA', 'EN_ESPERA')"),
    )
    op.create_index(
        "ix_inscripciones_actividad_espera", "inscripciones_actividad",
        ["actividad_id", "en_espera_desde"],
        postgresql_where=sa.text("estado = 'EN_ESPERA'"),
    )


def downgrade() -> None:
    op.drop_index("ix_inscripciones_actividad_espera", table_name="inscripciones_actividad")
    op.drop_index("uq_inscripcion_activa", table_name="inscripciones_actividad")
    # Las que estén en espera no existen en el esquema viejo
    op.execute("UPDATE inscripciones_actividad SET estado='CANCELADA' WHERE estado='EN_ESPERA'")
    op.create_index(
        "uq_inscripcion_confirmada", "inscripciones_actividad", ["actividad_id", "familia_id"],
        unique=True, postgresql_where=sa.text("estado = 'CONFIRMADA'"),
    )
    op.drop_column("inscripciones_actividad", "en_espera_desde")
    op.drop_constraint("estado_inscripcion", "inscripciones_actividad", type_="check")
    op.create_check_constraint(
        "estado_inscripcion", "inscripciones_actividad", "estado IN ('CONFIRMADA', 'CANCELADA')"
    )