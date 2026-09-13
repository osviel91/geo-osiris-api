"""Add isolated GeoJSON and CSV import staging.

Revision ID: 20260913_03
Revises: 20260913_02
Create Date: 2026-09-13 00:00:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_03"
down_revision: str | None = "20260913_02"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("layer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("format IN ('geojson', 'csv')", name="imports_format_check"),
        sa.CheckConstraint(
            "status IN ('validated', 'committed', 'cancelled')",
            name="imports_status_check",
        ),
        sa.ForeignKeyConstraint(["layer_id"], ["layers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_imports_layer_id", "imports", ["layer_id"])
    op.create_table(
        "import_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("geometry", postgresql.JSONB(), nullable=True),
        sa.Column("properties", postgresql.JSONB(), nullable=False),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("candidate_feature_ids", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["import_id"], ["imports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_rows_import_id", "import_rows", ["import_id"])


def downgrade() -> None:
    op.drop_table("import_rows")
    op.drop_table("imports")
