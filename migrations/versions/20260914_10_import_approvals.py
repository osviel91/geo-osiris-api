"""Add approval-gated import publication.

Revision ID: 20260914_10
Revises: 20260913_09
Create Date: 2026-09-14 00:00:00
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_10"
down_revision: str | None = "20260913_09"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "import_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("requested_status", sa.String(length=20), nullable=False),
        sa.Column("requester", sa.String(length=100), nullable=False),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "state", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column("approver", sa.String(length=100)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executor", sa.String(length=100)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.Text()),
        sa.CheckConstraint(
            "requested_status IN ('draft', 'published')",
            name="import_approvals_requested_status_check",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'approved', 'rejected', 'expired', "
            "'stale', 'executed', 'failed')",
            name="import_approvals_state_check",
        ),
        sa.ForeignKeyConstraint(["import_id"], ["imports.id"]),
    )
    op.create_index("import_approvals_import_id", "import_approvals", ["import_id"])
    op.create_index(
        "import_approvals_one_active_per_import",
        "import_approvals",
        ["import_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('pending', 'approved')"),
    )


def downgrade() -> None:
    op.drop_table("import_approvals")
