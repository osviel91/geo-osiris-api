"""Add duplicate explanations and explicit import-row resolution.

Revision ID: 20260913_08
Revises: 20260913_07
Create Date: 2026-09-13 00:00:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_08"
down_revision: str | None = "20260913_07"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

RADIO_SLUG = "amateur-radio-repeaters-es"


def upgrade() -> None:
    op.add_column(
        "import_rows",
        sa.Column(
            "candidate_matches",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "import_rows", sa.Column("resolution", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "import_rows",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "import_rows_resolution_check",
        "import_rows",
        "resolution IS NULL OR resolution IN ('skip', 'import_anyway')",
    )
    op.execute(
        f"""
        UPDATE layers
        SET metadata = metadata || jsonb_build_object(
            'duplicate_detection',
            jsonb_build_object(
                'identity_properties', jsonb_build_array('callsign'),
                'coordinate_radius_m', 300
            )
        )
        WHERE slug = '{RADIO_SLUG}'
        """
    )


def downgrade() -> None:
    op.execute(
        f"UPDATE layers SET metadata = metadata - 'duplicate_detection' "
        f"WHERE slug = '{RADIO_SLUG}'"
    )
    op.drop_constraint("import_rows_resolution_check", "import_rows", type_="check")
    op.drop_column("import_rows", "resolved_at")
    op.drop_column("import_rows", "resolution")
    op.drop_column("import_rows", "candidate_matches")
