"""Mark sources created through the agent source gate."""

import sqlalchemy as sa
from alembic import op

revision = "20260919_02"
down_revision = "20260919_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "external_sources",
        sa.Column(
            "agent_managed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("external_sources", "agent_managed")
