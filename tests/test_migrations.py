import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="requires a PostGIS test database",
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    return config


def _count(session: Session, table: str, where: str, params: dict) -> int:
    return session.scalar(text(f"SELECT count(*) FROM {table} WHERE {where}"), params)


def test_migration_12_downgrade_removes_only_seeded_data() -> None:
    config = _alembic_config()
    command.downgrade(config, "20260914_11")
    command.upgrade(config, "head")

    with Session(engine) as session:
        seeded_layer_id = session.scalar(
            text("SELECT id FROM layers WHERE slug = 'protected-natural-areas-es'")
        )
    assert seeded_layer_id is not None

    unrelated_layer_id = uuid.uuid4()
    unrelated_feature_id = uuid.uuid4()
    miteco_feature_id = uuid.uuid4()
    layer_params = {"layer_id": seeded_layer_id}
    unrelated_params = {"layer_id": unrelated_layer_id}

    with Session(engine) as session:
        session.execute(
            text(
                "INSERT INTO layers (id, slug, name, category, mode, "
                "geometry_types, enabled, style, metadata) VALUES (:id, :slug, "
                "'Unrelated', 'TEST', 'managed', '[\"Point\"]'::jsonb, true, "
                "'{}'::jsonb, '{}'::jsonb)"
            ),
            {"id": unrelated_layer_id, "slug": f"unrelated-{unrelated_layer_id}"},
        )
        session.execute(
            text(
                "INSERT INTO features (id, layer_id, external_id, geometry, "
                "properties, status) VALUES (:id, :layer_id, 'unrelated-1', "
                "ST_SetSRID(ST_GeomFromText('POINT(0 0)'), 4326), '{}'::jsonb, "
                "'published')"
            ),
            {"id": unrelated_feature_id, "layer_id": unrelated_layer_id},
        )
        session.execute(
            text(
                "INSERT INTO feature_provenance (id, feature_id, source_type, "
                "created_by, metadata) VALUES (:id, :feature_id, 'external', "
                "'test', '{}'::jsonb)"
            ),
            {"id": uuid.uuid4(), "feature_id": unrelated_feature_id},
        )
        session.execute(
            text(
                "INSERT INTO features (id, layer_id, external_id, geometry, "
                "properties, status) VALUES (:id, :layer_id, 'miteco-1', "
                "ST_SetSRID(ST_GeomFromText('POINT(0 0)'), 4326), '{}'::jsonb, "
                "'published')"
            ),
            {"id": miteco_feature_id, "layer_id": seeded_layer_id},
        )
        session.execute(
            text(
                "INSERT INTO feature_provenance (id, feature_id, source_type, "
                "created_by, metadata) VALUES (:id, :feature_id, 'external', "
                "'sync', '{}'::jsonb)"
            ),
            {"id": uuid.uuid4(), "feature_id": miteco_feature_id},
        )
        session.commit()

    command.downgrade(config, "20260914_11")

    with Session(engine) as session:
        assert _count(session, "layers", "id = :layer_id", layer_params) == 0
        assert (
            _count(session, "external_sources", "layer_id = :layer_id", layer_params)
            == 0
        )
        assert _count(session, "features", "layer_id = :layer_id", layer_params) == 0
        assert (
            _count(
                session,
                "feature_provenance",
                "feature_id = :feature_id",
                {"feature_id": miteco_feature_id},
            )
            == 0
        )
        assert _count(session, "layers", "id = :layer_id", unrelated_params) == 1
        assert (
            _count(session, "features", "layer_id = :layer_id", unrelated_params) == 1
        )
        assert (
            _count(
                session,
                "feature_provenance",
                "feature_id = :feature_id",
                {"feature_id": unrelated_feature_id},
            )
            == 1
        )

    command.upgrade(config, "head")

    with Session(engine) as session:
        assert _count(session, "layers", "id = :layer_id", layer_params) == 1
        assert (
            _count(session, "external_sources", "layer_id = :layer_id", layer_params)
            == 1
        )
