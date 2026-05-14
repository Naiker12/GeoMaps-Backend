"""add_support_requests

Revision ID: d3e4f5a6b7c8
Revises: c1d2e3f4g5h6
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c1d2e3f4g5h6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "support_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="new", nullable=False),
        sa.Column("priority", sa.String(length=30), server_default="normal", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), server_default="help_panel", nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_requests_assigned_to", "support_requests", ["assigned_to"])
    op.create_index("ix_support_requests_created_at", "support_requests", ["created_at"])
    op.create_index("ix_support_requests_email", "support_requests", ["email"])
    op.create_index("ix_support_requests_priority", "support_requests", ["priority"])
    op.create_index("ix_support_requests_status", "support_requests", ["status"])
    op.create_index("ix_support_requests_type", "support_requests", ["type"])
    op.create_index("ix_support_requests_user_id", "support_requests", ["user_id"])

    op.execute("ALTER TABLE public.support_requests ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_support_requests_user_id", table_name="support_requests")
    op.drop_index("ix_support_requests_type", table_name="support_requests")
    op.drop_index("ix_support_requests_status", table_name="support_requests")
    op.drop_index("ix_support_requests_priority", table_name="support_requests")
    op.drop_index("ix_support_requests_email", table_name="support_requests")
    op.drop_index("ix_support_requests_created_at", table_name="support_requests")
    op.drop_index("ix_support_requests_assigned_to", table_name="support_requests")
    op.drop_table("support_requests")
