"""Add append-only lifecycle audit events.

Revision ID: 20260919_01
Revises: 20260914_12
"""

import uuid
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260919_01"
down_revision: str | None = "20260914_12"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_events",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
        ),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("previous_state", postgresql.JSONB(), nullable=False),
        sa.Column("resulting_state", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_lifecycle_events_entity_id", "lifecycle_events", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_lifecycle_events_entity_id", table_name="lifecycle_events")
    op.drop_table("lifecycle_events")
