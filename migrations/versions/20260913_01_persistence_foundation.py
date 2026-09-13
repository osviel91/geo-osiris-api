"""Create the Geo Hub persistence foundation.

Revision ID: 20260913_01
Revises:
Create Date: 2026-09-13 00:00:00
"""

from typing import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_01"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "layers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("geometry_types", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("style", postgresql.JSONB(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.CheckConstraint("mode IN ('managed', 'external')", name="layers_mode_check"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_layers_slug", "layers", ["slug"])
    op.create_table(
        "features",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("layer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column(
            "geometry",
            geoalchemy2.Geometry(
                geometry_type="GEOMETRY", srid=4326, spatial_index=False
            ),
            nullable=False,
        ),
        sa.Column("properties", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'stale', 'archived')",
            name="features_status_check",
        ),
        sa.ForeignKeyConstraint(["layer_id"], ["layers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "layer_id", "external_id", name="features_layer_external_id_key"
        ),
    )
    op.create_index("ix_features_layer_id", "features", ["layer_id"])
    op.create_index(
        "features_geometry_gix", "features", ["geometry"], postgresql_using="gist"
    )
    op.create_table(
        "feature_provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_record_id", sa.String(length=200), nullable=True),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.String(length=50), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('manual', 'import', 'agent', 'external')",
            name="feature_provenance_source_type_check",
        ),
        sa.ForeignKeyConstraint(["feature_id"], ["features.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feature_provenance_feature_id", "feature_provenance", ["feature_id"]
    )


def downgrade() -> None:
    op.drop_table("feature_provenance")
    op.drop_table("features")
    op.drop_table("layers")
