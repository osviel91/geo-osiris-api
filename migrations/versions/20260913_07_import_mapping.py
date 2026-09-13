"""Persist the normalized CSV mapping and header snapshot on imports.

Revision ID: 20260913_07
Revises: 20260913_06
Create Date: 2026-09-13 00:00:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_07"
down_revision: str | None = "20260913_06"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "imports",
        sa.Column(
            "csv_mapping",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "imports",
        sa.Column(
            "csv_headers",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "imports",
        sa.Column(
            "mapping_version", sa.String(length=20), nullable=False, server_default="1"
        ),
    )


def downgrade() -> None:
    op.drop_column("imports", "mapping_version")
    op.drop_column("imports", "csv_headers")
    op.drop_column("imports", "csv_mapping")
