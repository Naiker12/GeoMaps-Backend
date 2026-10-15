"""Retira exclusivamente las tablas del módulo de proyectos con respaldo verificado."""

from alembic import context, op
import sqlalchemy as sa

from app.maintenance.project_retirement import PROJECT_TABLES, rows_digest, verified_backup

revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade():
    if context.is_offline_mode():
        raise RuntimeError("Esta migración requiere verificación online del respaldo y las filas actuales")
    backup_path = context.config.attributes.get("project_retirement_backup") or context.get_x_argument(as_dictionary=True).get("project_retirement_backup")
    if not backup_path:
        raise RuntimeError("Ejecuta scripts/retire_projects.py --apply para respaldar y retirar proyectos")
    manifest = verified_backup(backup_path)
    bind = op.get_bind()
    bind.execute(sa.text("SET LOCAL lock_timeout = '10s'"))
    targets = ", ".join(f'public."{name}"' for name in PROJECT_TABLES)
    bind.execute(sa.text(f"LOCK TABLE {targets} IN ACCESS EXCLUSIVE MODE"))
    for name in PROJECT_TABLES:
        rows = [row[0] for row in bind.execute(sa.text(f'SELECT to_jsonb(t) FROM public."{name}" t'))]
        if rows_digest(rows) != manifest["table_digests"][name]:
            raise RuntimeError("Los datos de proyectos cambiaron después del respaldo; genera un respaldo nuevo")
    # RESTRICT implícito: una dependencia externa aborta y revierte la transacción.
    # Nunca usar CASCADE: el alcance son solo estas diez tablas.
    for name in PROJECT_TABLES:
        op.drop_table(name, schema="public")


def downgrade():
    raise RuntimeError("Retiro irreversible por Alembic: restaurar restore.sql y los archivos desde el respaldo privado verificado")
