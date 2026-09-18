"""Add declarative external-source adapter configuration.

Revision ID: 20260914_11
Revises: 20260914_10
Create Date: 2026-09-14 00:00:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_11"
down_revision: str | None = "20260914_10"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "external_sources",
        sa.Column(
            "adapter_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("external_sources", "adapter_config")
