"""add style fields to layers

Revision ID: 55ccd354549c
Revises: 5f1b267b7a37
Create Date: 2026-03-06 14:00:19.337463

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55ccd354549c'
down_revision: Union[str, None] = '5f1b267b7a37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('layers', sa.Column('map_color', sa.String(length=50), nullable=True))
    op.add_column('layers', sa.Column('map_opacity', sa.Float(), nullable=False, server_default='0.8'))


def downgrade() -> None:
    op.drop_column('layers', 'map_opacity')
    op.drop_column('layers', 'map_color')
