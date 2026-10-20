"""seguridad: sesiones revocables, bloqueo de login, email sin mayúsculas, encuestas con reglas

- usuarios: sesion_version (revocar tokens), intentos_fallidos y bloqueado_hasta (lockout).
- usuarios: correos a minúsculas + índice único lower(email). Si hay dos cuentas que solo
  difieren en mayúsculas, la migración se detiene y dice cuáles (hay que resolverlo a mano).
- encuestas_iniciales_actividad: antes la creaba create_all dentro de un endpoint. Aquí se crea
  si no existe; si ya existe, se le agregan llave foránea, UNIQUE y límites de texto.
- encuestas_actividades: UNIQUE (usuario_id, actividad_id).

Revision ID: e8f2a4c6b1d3
Revises: a1c7e5b9d3f2
Create Date: 2026-10-19 23:59:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e8f2a4c6b1d3"
down_revision = "a1c7e5b9d3f2"
branch_labels = None
depends_on = None


def _hay_tabla(nombre: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(nombre)


def _hay_restriccion(tabla: str, nombre: str) -> bool:
    insp = sa.inspect(op.get_bind())
    nombres = {c["name"] for c in insp.get_unique_constraints(tabla)}
    nombres |= {c["name"] for c in insp.get_foreign_keys(tabla)}
    return nombre in nombres


def _quitar_duplicados(tabla: str) -> None:
    # Se queda con la respuesta más antigua de cada persona por actividad
    op.execute(f"""
        DELETE FROM {tabla} t
        USING {tabla} otra
        WHERE t.usuario_id = otra.usuario_id
          AND t.actividad_id = otra.actividad_id
          AND (t.creado_en, t.id::text) > (otra.creado_en, otra.id::text)
    """)


def upgrade() -> None:
    conn = op.get_bind()

    # ---------- usuarios: sesión y bloqueo ----------
    op.add_column("usuarios", sa.Column("sesion_version", sa.Integer(), server_default="0", nullable=False))
    op.add_column("usuarios", sa.Column("intentos_fallidos", sa.Integer(), server_default="0", nullable=False))
    op.add_column("usuarios", sa.Column("bloqueado_hasta", sa.DateTime(timezone=True), nullable=True))

    # ---------- usuarios: email sin distinguir mayúsculas ----------
    duplicados = conn.execute(sa.text(
        "SELECT lower(email) FROM usuarios GROUP BY lower(email) HAVING count(*) > 1"
    )).scalars().all()
    if duplicados:
        raise RuntimeError(
            "Hay cuentas repetidas que solo difieren en mayúsculas: " + ", ".join(duplicados)
            + ". Une o borra las sobrantes y vuelve a correr la migración."
        )
    op.execute("UPDATE usuarios SET email = lower(trim(email)) WHERE email <> lower(trim(email))")
    op.create_index("uq_usuarios_email_lower", "usuarios", [sa.text("lower(email)")], unique=True)

    # ---------- encuestas_iniciales_actividad ----------
    if not _hay_tabla("encuestas_iniciales_actividad"):
        op.create_table(
            "encuestas_iniciales_actividad",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("usuario_id", sa.UUID(), nullable=False),
            sa.Column("actividad_id", sa.UUID(), nullable=False),
            sa.Column("motivos", sa.JSON(), nullable=False),
            sa.Column("otro_motivo", sa.String(length=300), nullable=True),
            sa.Column("expectativas", sa.JSON(), nullable=False),
            sa.Column("otra_expectativa", sa.String(length=300), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["actividad_id"], ["actividades.iniciativa_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("usuario_id", "actividad_id", name="uq_encuesta_inicial_usuario_actividad"),
        )
    else:
        # Ya la había creado create_all: se limpia y se le agregan las restricciones que no tenía
        op.execute("""
            DELETE FROM encuestas_iniciales_actividad e
            WHERE NOT EXISTS (SELECT 1 FROM actividades a WHERE a.iniciativa_id = e.actividad_id)
        """)
        _quitar_duplicados("encuestas_iniciales_actividad")
        op.execute("UPDATE encuestas_iniciales_actividad SET otro_motivo = left(otro_motivo, 300) WHERE length(otro_motivo) > 300")
        op.execute("UPDATE encuestas_iniciales_actividad SET otra_expectativa = left(otra_expectativa, 300) WHERE length(otra_expectativa) > 300")
        op.alter_column("encuestas_iniciales_actividad", "otro_motivo", type_=sa.String(length=300))
        op.alter_column("encuestas_iniciales_actividad", "otra_expectativa", type_=sa.String(length=300))

        # Las FK que hubiera (la de create_all no tenía ON DELETE CASCADE) se reemplazan
        insp = sa.inspect(conn)
        for fk in insp.get_foreign_keys("encuestas_iniciales_actividad"):
            if fk.get("name"):
                op.drop_constraint(fk["name"], "encuestas_iniciales_actividad", type_="foreignkey")
        op.create_foreign_key(
            "encuestas_iniciales_actividad_usuario_id_fkey", "encuestas_iniciales_actividad",
            "usuarios", ["usuario_id"], ["id"], ondelete="CASCADE",
        )
        op.create_foreign_key(
            "encuestas_iniciales_actividad_actividad_id_fkey", "encuestas_iniciales_actividad",
            "actividades", ["actividad_id"], ["iniciativa_id"], ondelete="CASCADE",
        )
        if not _hay_restriccion("encuestas_iniciales_actividad", "uq_encuesta_inicial_usuario_actividad"):
            op.create_unique_constraint(
                "uq_encuesta_inicial_usuario_actividad", "encuestas_iniciales_actividad",
                ["usuario_id", "actividad_id"],
            )

    # ---------- encuestas_actividades ----------
    _quitar_duplicados("encuestas_actividades")
    op.create_unique_constraint(
        "uq_encuesta_usuario_actividad", "encuestas_actividades", ["usuario_id", "actividad_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_encuesta_usuario_actividad", "encuestas_actividades", type_="unique")
    # encuestas_iniciales_actividad se deja: pudo existir antes de esta migración (create_all)
    op.drop_constraint("uq_encuesta_inicial_usuario_actividad", "encuestas_iniciales_actividad", type_="unique")
    op.drop_index("uq_usuarios_email_lower", table_name="usuarios")
    op.drop_column("usuarios", "bloqueado_hasta")
    op.drop_column("usuarios", "intentos_fallidos")
    op.drop_column("usuarios", "sesion_version")
