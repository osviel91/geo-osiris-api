"""Enable generic geometry repair for the MITECO source.

Revision ID: 20260921_01
Revises: 20260920_01
Create Date: 2026-09-21 00:00:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_01"
down_revision: str | None = "20260920_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE external_sources
            SET adapter_config = adapter_config || CAST(:repair AS jsonb)
            WHERE slug = 'miteco-protected-natural-areas'
            """
        ).bindparams(repair='{"geometry_repair":{"method":"make_valid"}}')
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE external_sources
            SET adapter_config = adapter_config - 'geometry_repair'
            WHERE slug = 'miteco-protected-natural-areas'
            """
        )
    )
