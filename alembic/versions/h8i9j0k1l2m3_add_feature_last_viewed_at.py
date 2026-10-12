"""Add feature last_viewed_at.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
"""

from alembic import op
import sqlalchemy as sa

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("layer_features", sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("layer_features", "last_viewed_at")
