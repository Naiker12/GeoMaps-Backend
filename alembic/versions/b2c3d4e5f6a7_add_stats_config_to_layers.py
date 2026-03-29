"""add_stats_config_feature_card_config_to_layers

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-29 11:09:00.000000

Agrega columnas stats_config y feature_card_config (JSONB) a la tabla layers,
y puebla la configuración de las 4 capas existentes.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('layers', sa.Column(
        'stats_config',
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        server_default=sa.text("'{}'::jsonb")
    ))
    op.add_column('layers', sa.Column(
        'feature_card_config',
        postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
        server_default=sa.text("'{}'::jsonb")
    ))
    # La configuración data ya fue aplicada directamente vía MCP.
    # Esta migración registra el DDL en el historial de Alembic.


def downgrade() -> None:
    op.drop_column('layers', 'feature_card_config')
    op.drop_column('layers', 'stats_config')
