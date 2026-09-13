"""Add import-level provenance source fields.

Revision ID: 20260913_09
Revises: 20260913_08
Create Date: 2026-09-13 00:00:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_09"
down_revision: str | None = "20260913_08"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "imports", sa.Column("source_name", sa.String(length=200), nullable=True)
    )
    op.add_column("imports", sa.Column("source_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("imports", "source_url")
    op.drop_column("imports", "source_name")
