"""add_drafted_project_fields

Revision ID: f6a7b8c9d0e1
Revises: e4f5a6b7c8d9
Create Date: 2026-05-20 12:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("glb_model_url", sa.String(length=500), nullable=True))
    op.add_column("project_lots", sa.Column("floor_level", sa.Integer(), nullable=True))

    op.execute(
        "UPDATE project_lots SET status = 'En Proceso' "
        "WHERE lower(status) IN ('proceso', 'en proceso', 'en_proceso')"
    )


def downgrade() -> None:
    op.execute("UPDATE project_lots SET status = 'Proceso' WHERE status = 'En Proceso'")
    op.drop_column("project_lots", "floor_level")
    op.drop_column("projects", "glb_model_url")
