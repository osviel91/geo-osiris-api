"""Add the AEMET observation-stations source.

Revision ID: 20260913_05
Revises: 20260913_04
Create Date: 2026-09-13 00:00:00
"""

import uuid
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_05"
down_revision: str | None = "20260913_04"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LAYER_ID = uuid.uuid5(uuid.NAMESPACE_URL, "osiris:aemet-observation-stations")
SOURCE_ID = uuid.uuid5(uuid.NAMESPACE_URL, "osiris:source:aemet-observation-stations")
ENDPOINT = (
    "https://opendata.aemet.es/opendata/api/valores/climatologicos/"
    "inventarioestaciones/todasestaciones/"
)


def upgrade() -> None:
    layers = sa.table(
        "layers",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("category", sa.String),
        sa.column("mode", sa.String),
        sa.column("geometry_types", postgresql.JSONB),
        sa.column("enabled", sa.Boolean),
        sa.column("style", postgresql.JSONB),
        sa.column("metadata", postgresql.JSONB),
    )
    sources = sa.table(
        "external_sources",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("layer_id", postgresql.UUID(as_uuid=True)),
        sa.column("slug", sa.String),
        sa.column("adapter", sa.String),
        sa.column("dataset_id", sa.String),
        sa.column("endpoint", sa.Text),
        sa.column("enabled", sa.Boolean),
        sa.column("status", sa.String),
    )
    op.bulk_insert(
        layers,
        [
            {
                "id": LAYER_ID,
                "slug": "aemet-observation-stations",
                "name": "AEMET Observation Stations",
                "description": "AEMET weather observation station infrastructure",
                "category": "WEATHER_INFRASTRUCTURE",
                "mode": "external",
                "geometry_types": ["Point"],
                "enabled": True,
                "style": {},
                "metadata": {"provider": "AEMET", "dataset": "station-inventory"},
            }
        ],
    )
    op.bulk_insert(
        sources,
        [
            {
                "id": SOURCE_ID,
                "layer_id": LAYER_ID,
                "slug": "aemet-observation-stations",
                "adapter": "aemet_stations",
                "dataset_id": "aemet-opendata-station-inventory",
                "endpoint": ENDPOINT,
                "enabled": True,
                "status": "never",
            }
        ],
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM external_sources WHERE id = :id"), {"id": SOURCE_ID}
    )
    connection.execute(sa.text("DELETE FROM layers WHERE id = :id"), {"id": LAYER_ID})
