"""Add published-data freshness markers to layers.

Revision ID: 20260913_06
Revises: 20260913_05
Create Date: 2026-09-13 00:00:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_06"
down_revision: str | None = "20260913_05"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "layers",
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "layers",
        sa.Column("data_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE layers
        SET revision = 1,
            data_updated_at = COALESCE(updated_at, now())
        WHERE id IN (
            SELECT DISTINCT layer_id FROM features
            WHERE status = 'published' AND archived_at IS NULL
        )
        """
    )


def downgrade() -> None:
    op.drop_column("layers", "data_updated_at")
    op.drop_column("layers", "revision")
