"""inscripciones de familias a actividades

- inscripciones_actividad: una fila por familia inscrita (CONFIRMADA o CANCELADA).
- inscripcion_participantes: quién de la familia va (adulto o menor) y su asistencia.
- El cupo se calcula contando participantes de inscripciones CONFIRMADAS
  (no hay columna contador en actividades).

Revision ID: b5e2d8f1c4a7
Revises: da8fe3ce4313
Create Date: 2026-10-15 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b5e2d8f1c4a7"
down_revision = "da8fe3ce4313"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inscripciones_actividad",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actividad_id", sa.UUID(), nullable=False),
        sa.Column("familia_id", sa.UUID(), nullable=False),
        sa.Column("inscrito_por_id", sa.UUID(), nullable=True),
        sa.Column(
            "estado",
            sa.Enum(
                "CONFIRMADA", "CANCELADA",
                name="estado_inscripcion", native_enum=False, create_constraint=True, length=30,
            ),
            server_default="CONFIRMADA",
            nullable=False,
        ),
        sa.Column("creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("cancelada_en", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["actividad_id"], ["actividades.iniciativa_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["familia_id"], ["familias.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inscrito_por_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inscripciones_actividad_familia_id", "inscripciones_actividad", ["familia_id"])
    op.create_index(
        "uq_inscripcion_confirmada",
        "inscripciones_actividad",
        ["actividad_id", "familia_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'CONFIRMADA'"),
    )
    op.create_index(
        "ix_inscripciones_actividad_confirmadas",
        "inscripciones_actividad",
        ["actividad_id"],
        postgresql_where=sa.text("estado = 'CONFIRMADA'"),
    )

    op.create_table(
        "inscripcion_participantes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("inscripcion_id", sa.UUID(), nullable=False),
        sa.Column("usuario_id", sa.UUID(), nullable=True),
        sa.Column("menor_id", sa.UUID(), nullable=True),
        sa.Column(
            "asistencia",
            sa.Enum(
                "PENDIENTE", "ASISTIO", "FALTO",
                name="estado_asistencia", native_enum=False, create_constraint=True, length=30,
            ),
            server_default="PENDIENTE",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["inscripcion_id"], ["inscripciones_actividad.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["menor_id"], ["familia_menores.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "(usuario_id IS NOT NULL) <> (menor_id IS NOT NULL)", name="ck_participante_adulto_o_menor"
        ),
        sa.UniqueConstraint("inscripcion_id", "usuario_id", name="uq_participante_usuario"),
        sa.UniqueConstraint("inscripcion_id", "menor_id", name="uq_participante_menor"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inscripcion_participantes_inscripcion_id", "inscripcion_participantes", ["inscripcion_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_inscripcion_participantes_inscripcion_id", table_name="inscripcion_participantes")
    op.drop_table("inscripcion_participantes")
    op.drop_index("ix_inscripciones_actividad_confirmadas", table_name="inscripciones_actividad")
    op.drop_index("uq_inscripcion_confirmada", table_name="inscripciones_actividad")
    op.drop_index("ix_inscripciones_actividad_familia_id", table_name="inscripciones_actividad")
    op.drop_table("inscripciones_actividad")