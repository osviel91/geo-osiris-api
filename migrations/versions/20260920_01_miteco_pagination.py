"""Enable bounded offset pagination for the seeded MITECO source."""

from typing import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260920_01"
down_revision: str | None = "20260919_02"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        text(
            "UPDATE external_sources SET adapter_config = adapter_config || "
            "CAST(:pagination AS jsonb) WHERE slug = :slug"
        ).bindparams(
            pagination='{"pagination":{"type":"offset","limit_param":"count",'
            '"offset_param":"startIndex","page_size":250,"max_pages":20}}',
            slug="miteco-protected-natural-areas",
        )
    )


def downgrade() -> None:
    op.execute(
        text(
            "UPDATE external_sources SET adapter_config = adapter_config - "
            "'pagination' WHERE slug = :slug"
        ).bindparams(slug="miteco-protected-natural-areas")
    )
