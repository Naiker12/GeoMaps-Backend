"""Add quota reservations and unique daily statistics.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
"""

from alembic import op
import sqlalchemy as sa

revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No borrar ni fusionar silenciosamente estadísticas históricas duplicadas.
    op.execute("LOCK TABLE api_key_daily_stats IN SHARE ROW EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM api_key_daily_stats
                GROUP BY api_key_id, stat_date HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'Existen estadísticas diarias duplicadas'
                    USING HINT = 'Revisar duplicados por api_key_id y stat_date antes de aplicar esta revisión; no se han fusionado ni eliminado filas.';
            END IF;
        END $$
    """)
    op.create_unique_constraint("uq_api_key_daily_stats_key_date", "api_key_daily_stats", ["api_key_id", "stat_date"])
    op.add_column("api_key_usage_logs", sa.Column("quota_pending", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("api_key_usage_logs", "quota_pending")
    op.drop_constraint("uq_api_key_daily_stats_key_date", "api_key_daily_stats", type_="unique")
