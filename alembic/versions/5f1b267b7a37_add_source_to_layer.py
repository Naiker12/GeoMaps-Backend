"""Add source to layer

Revision ID: 5f1b267b7a37
Revises: 70d6a091006e
Create Date: 2026-03-02 15:24:54.448884

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5f1b267b7a37'
down_revision: Union[str, None] = '70d6a091006e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('layers', sa.Column('source', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('layers', 'source')
