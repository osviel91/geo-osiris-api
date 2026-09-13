"""Seed the managed amateur-radio repeaters demonstration layer.

Revision ID: 20260913_02
Revises: 20260913_01
Create Date: 2026-09-13 00:00:00
"""

from typing import Sequence

from alembic import op

revision: str = "20260913_02"
down_revision: str | None = "20260913_01"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LAYER_ID = "6bb2ee13-a3e4-4a1a-a029-17fc983a01e1"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO layers (id, slug, name, description, category, mode,
                            geometry_types, enabled, style, metadata)
        VALUES ('{LAYER_ID}', 'amateur-radio-repeaters-es',
                'Amateur radio repeaters (demo)',
                'Clearly labelled demonstration records for the managed-layer flow.',
                'AMATEUR_RADIO', 'managed', '["Point"]'::jsonb, true,
                '{{}}'::jsonb, '{{"dataset_status":"demo"}}'::jsonb)
        """
    )
    op.execute(
        f"""
        INSERT INTO features (id, layer_id, external_id, geometry, properties, status,
                              verified_at)
        VALUES
          ('c5b19e6c-0e47-4c57-90e1-bb00f1e10001', '{LAYER_ID}', 'demo-ea4-madrid',
           ST_SetSRID(ST_GeomFromText('POINT(-3.7038 40.4168)'), 4326),
           jsonb_build_object(
             'name', 'Demo EA4 Madrid repeater', 'callsign', 'DEMO-EA4',
             'frequency_mhz', 145.725, 'record_status', 'demo'),
           'published', now()),
          ('c5b19e6c-0e47-4c57-90e1-bb00f1e10002', '{LAYER_ID}', 'demo-ea3-barcelona',
           ST_SetSRID(ST_GeomFromText('POINT(2.1734 41.3851)'), 4326),
           jsonb_build_object(
             'name', 'Demo EA3 Barcelona repeater', 'callsign', 'DEMO-EA3',
             'frequency_mhz', 438.850, 'record_status', 'demo'),
           'published', now())
        """
    )
    op.execute(
        """
        INSERT INTO feature_provenance (id, feature_id, source_type, source_name,
                                        created_by, confidence, metadata)
        VALUES
          ('ae710692-8993-4d73-bb24-44c65c5f0001',
           'c5b19e6c-0e47-4c57-90e1-bb00f1e10001', 'manual', 'demo seed',
           'migration', 'demo', '{"record_status":"demo"}'::jsonb),
          ('ae710692-8993-4d73-bb24-44c65c5f0002',
           'c5b19e6c-0e47-4c57-90e1-bb00f1e10002', 'manual', 'demo seed',
           'migration', 'demo', '{"record_status":"demo"}'::jsonb)
        """
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM layers WHERE id = '{LAYER_ID}'")
