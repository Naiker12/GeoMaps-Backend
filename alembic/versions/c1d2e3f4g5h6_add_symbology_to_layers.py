"""Alembic migration: add symbology JSONB column to layers table.

Revision ID: c1d2e3f4g5h6
Revises: b2c3d4e5f6a7
Create Date: 2026-04-23
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = 'c1d2e3f4g5h6'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('layers', sa.Column('symbology', JSONB, server_default='{}', nullable=True))


def downgrade() -> None:
    op.drop_column('layers', 'symbology')
