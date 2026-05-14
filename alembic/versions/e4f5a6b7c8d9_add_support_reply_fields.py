"""add_support_reply_fields

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("support_requests", sa.Column("response_message", sa.Text(), nullable=True))
    op.add_column("support_requests", sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("support_requests", sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("support_requests", "email_sent_at")
    op.drop_column("support_requests", "responded_at")
    op.drop_column("support_requests", "response_message")
