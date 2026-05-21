"""create_project_assets

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-21 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("storage_bucket", sa.String(length=100), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("public_url", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=150), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("extension", sa.String(length=20), nullable=True),
        sa.Column("derived_from_asset_id", sa.UUID(), nullable=True),
        sa.Column("conversion_status", sa.String(length=50), nullable=False),
        sa.Column("conversion_error", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("transform", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["derived_from_asset_id"], ["project_assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_project_assets_project_id", "project_assets", ["project_id"])
    op.create_index("idx_project_assets_kind", "project_assets", ["kind"])
    op.create_index("idx_project_assets_is_primary", "project_assets", ["is_primary"])
    op.create_index(
        "uq_project_assets_primary_kind",
        "project_assets",
        ["project_id", "kind"],
        unique=True,
        postgresql_where=sa.text("is_primary = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_project_assets_primary_kind", table_name="project_assets", postgresql_where=sa.text("is_primary = true"))
    op.drop_index("idx_project_assets_is_primary", table_name="project_assets")
    op.drop_index("idx_project_assets_kind", table_name="project_assets")
    op.drop_index("idx_project_assets_project_id", table_name="project_assets")
    op.drop_table("project_assets")
