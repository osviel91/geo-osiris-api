"""Seed the MITECO protected-natural-areas external source.

Revision ID: 20260914_12
Revises: 20260914_11
Create Date: 2026-09-14 00:00:00
"""

import uuid
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_12"
down_revision: str | None = "20260914_11"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LAYER_ID = uuid.uuid5(uuid.NAMESPACE_URL, "osiris:protected-natural-areas-es")
SOURCE_ID = uuid.uuid5(
    uuid.NAMESPACE_URL, "osiris:source:miteco-protected-natural-areas"
)
ENDPOINT = (
    "https://geoserver.iepnb.es/geoserver/ENP/enp/wfs?service=WFS&version=2.0.0"
    "&request=GetFeature&typeNames=ENP:enp&outputFormat=application/json"
)
ATTRIBUTION = (
    "IEPNB / Ministerio para la Transición Ecológica y el Reto Demográfico (MITECO)"
)
ADAPTER_CONFIG = {
    "id_property": "id_espacio_proteg",
    # This WFS snapshot is ~55 MB and takes ~17 s, so the 20 s default is too tight.
    "timeout_seconds": 60,
    "properties": {
        "nombre": "nombre",
        "designacion": "designacion",
        "ambito": "ambito",
        "nombre_organismo": "nombre_organismo",
        "nombre_categoria_iucn": "nombre_categoria_iucn",
        "superficie_oficial": "superficie_oficial",
        "anio_alta": "anio_alta",
        "anio_baja": "anio_baja",
        "es_oficial": "es_oficial",
        "id_ref_es": "id_ref_es",
    },
}


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
        sa.column("adapter_config", postgresql.JSONB),
        sa.column("enabled", sa.Boolean),
        sa.column("status", sa.String),
    )
    op.bulk_insert(
        layers,
        [
            {
                "id": LAYER_ID,
                "slug": "protected-natural-areas-es",
                "name": "Protected Natural Areas — Spain",
                "description": (
                    "Authoritative protected natural areas published by MITECO / IEPNB."
                ),
                "category": "ENVIRONMENT",
                "mode": "external",
                "geometry_types": ["MultiPolygon"],
                "enabled": True,
                "style": {},
                "metadata": {
                    "provider": ATTRIBUTION,
                    "dataset": "Protected Natural Areas",
                    "attribution": ATTRIBUTION,
                    "reuse": (
                        "Reuse requires source citation; no dataset-specific SPDX "
                        "or CC identifier was published by the service."
                    ),
                },
            }
        ],
    )
    op.bulk_insert(
        sources,
        [
            {
                "id": SOURCE_ID,
                "layer_id": LAYER_ID,
                "slug": "miteco-protected-natural-areas",
                "adapter": "geojson",
                "dataset_id": "miteco-iepnb-protected-natural-areas",
                "endpoint": ENDPOINT,
                "adapter_config": ADAPTER_CONFIG,
                "enabled": True,
                "status": "never",
            }
        ],
    )


def downgrade() -> None:
    # Dependency-safe, scoped to the seeded layer only. feature_provenance has
    # no ON DELETE CASCADE, so it must be removed before the features it cites.
    connection = op.get_bind()
    params = {"layer_id": LAYER_ID}
    connection.execute(
        sa.text(
            "DELETE FROM feature_provenance WHERE feature_id IN "
            "(SELECT id FROM features WHERE layer_id = :layer_id)"
        ),
        params,
    )
    connection.execute(
        sa.text("DELETE FROM features WHERE layer_id = :layer_id"), params
    )
    connection.execute(
        sa.text("DELETE FROM external_sources WHERE layer_id = :layer_id"), params
    )
    connection.execute(sa.text("DELETE FROM layers WHERE id = :layer_id"), params)
