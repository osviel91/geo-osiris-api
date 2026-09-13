"""Add external source sync state.

Revision ID: 20260913_04
Revises: 20260913_03
Create Date: 2026-09-13 00:00:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_04"
down_revision: str | None = "20260913_03"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("layer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("adapter", sa.String(length=100), nullable=False),
        sa.Column("dataset_id", sa.String(length=200), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('never', 'success', 'failed')",
            name="external_sources_status_check",
        ),
        sa.ForeignKeyConstraint(["layer_id"], ["layers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("layer_id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_external_sources_layer_id", "external_sources", ["layer_id"])
    op.create_index("ix_external_sources_slug", "external_sources", ["slug"])


def downgrade() -> None:
    op.drop_table("external_sources")
