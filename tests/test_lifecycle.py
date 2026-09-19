import os
import uuid

import pytest
from fastapi.testclient import TestClient
from geoalchemy2 import WKTElement
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import (
    ExternalSource,
    Feature,
    FeatureProvenance,
    Layer,
    LifecycleEvent,
)

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="requires a PostGIS test database",
)

client = TestClient(app)
HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def empty_database(monkeypatch):
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE lifecycle_events, import_approvals, import_rows, imports, "
                "external_sources, feature_provenance, features, layers CASCADE"
            )
        )
    yield


def create_layer(slug: str, *, metadata: dict | None = None) -> dict:
    response = client.post(
        "/api/v1/admin/layers",
        headers=HEADERS,
        json={
            "slug": slug,
            "name": slug,
            "category": "TEST",
            "mode": "managed",
            "geometry_types": ["Point"],
            "metadata_": metadata or {},
        },
    )
    assert response.status_code == 200
    return response.json()


def create_feature(layer_id: str, *, external_id: str = "feature-1") -> str:
    response = client.post(
        f"/api/v1/admin/layers/{layer_id}/features",
        headers=HEADERS,
        json={
            "external_id": external_id,
            "geometry": {"type": "Point", "coordinates": [1, 2]},
            "properties": {"name": external_id},
            "status": "published",
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_feature_archive_restore_hard_delete_and_audit() -> None:
    layer = create_layer("lifecycle-feature")
    feature_id = create_feature(layer["id"])

    detail = client.get(f"/api/v1/admin/features/{feature_id}", headers=HEADERS)
    assert detail.json()["ownership"] == "manual"
    assert detail.json()["source"] is None

    archived = client.post(
        f"/api/v1/admin/features/{feature_id}/archive", headers=HEADERS
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.get("/api/v1/layers/lifecycle-feature").json()["features"] == []

    restored = client.post(
        f"/api/v1/admin/features/{feature_id}/restore", headers=HEADERS
    )
    assert restored.status_code == 200
    assert client.get("/api/v1/layers/lifecycle-feature").json()["features"]

    deleted = client.post(
        f"/api/v1/admin/features/{feature_id}/hard-delete",
        headers=HEADERS,
        json={},
    )
    assert deleted.status_code == 200
    with Session(engine) as session:
        assert session.get(Feature, uuid.UUID(feature_id)) is None
        events = session.scalars(
            select(LifecycleEvent)
            .where(LifecycleEvent.entity_id == uuid.UUID(feature_id))
            .order_by(LifecycleEvent.occurred_at, LifecycleEvent.id)
        ).all()
        assert [event.action for event in events] == [
            "archive",
            "restore",
            "hard_delete",
        ]
        assert events[-1].actor == "geo-admin"
        assert events[-1].resulting_state == {"deleted": True}


def test_external_feature_warning_and_hard_delete_confirmation() -> None:
    with Session(engine) as session:
        layer = Layer(
            slug="lifecycle-external",
            name="Lifecycle external",
            category="TEST",
            mode="external",
            geometry_types=["Point"],
            style={},
            metadata_={},
        )
        source = ExternalSource(
            layer=layer,
            slug="lifecycle-source",
            adapter="fixture",
            dataset_id="fixture-v1",
        )
        feature = Feature(
            layer=layer,
            external_id="source-1",
            geometry=WKTElement("POINT(1 2)", srid=4326),
            properties={"name": "source"},
            status="published",
        )
        feature.provenance_records.append(
            FeatureProvenance(
                source_type="external",
                source_name=source.slug,
                source_record_id="source-1",
                created_by="sync",
            )
        )
        session.add_all([source, feature])
        session.commit()
        feature_id = str(feature.id)
        source_id = str(source.id)

    detail = client.get(f"/api/v1/admin/features/{feature_id}", headers=HEADERS).json()
    assert detail["ownership"] == "external"
    assert detail["source"] == {"slug": "lifecycle-source", "record_id": "source-1"}
    assert "may recreate" in detail["deletion_warning"]

    archive = client.post(
        f"/api/v1/admin/features/{feature_id}/archive", headers=HEADERS
    )
    assert archive.status_code == 200
    restore = client.post(
        f"/api/v1/admin/features/{feature_id}/restore", headers=HEADERS
    )
    assert restore.status_code == 200
    blocked = client.post(
        f"/api/v1/admin/features/{feature_id}/hard-delete",
        headers=HEADERS,
        json={},
    )
    assert blocked.status_code == 409
    deleted = client.post(
        f"/api/v1/admin/features/{feature_id}/hard-delete",
        headers=HEADERS,
        json={"confirm_recreated_on_sync": True},
    )
    assert deleted.status_code == 200
    assert (
        client.get(f"/api/v1/admin/sources/{source_id}", headers=HEADERS).status_code
        == 200
    )


def test_layer_disable_enable_empty_delete_and_disposable_cascade() -> None:
    metadata = {"lifecycle": {"disposable": True}}
    empty = create_layer("lifecycle-empty", metadata=metadata)
    assert (
        client.post(
            f"/api/v1/admin/layers/{empty['id']}/disable", headers=HEADERS
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/admin/layers/{empty['id']}/enable", headers=HEADERS
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/admin/layers/{empty['id']}/disable", headers=HEADERS
        ).status_code
        == 200
    )
    assert (
        client.request(
            "DELETE",
            f"/api/v1/admin/layers/{empty['id']}",
            headers=HEADERS,
            json={"confirmation": "DELETE EMPTY LAYER"},
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/admin/layers/{empty['id']}", headers=HEADERS).status_code
        == 404
    )

    populated = create_layer("lifecycle-populated", metadata=metadata)
    create_feature(populated["id"])
    assert (
        client.request(
            "DELETE",
            f"/api/v1/admin/layers/{populated['id']}",
            headers=HEADERS,
            json={"confirmation": "DELETE EMPTY LAYER"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/admin/layers/{populated['id']}/disable", headers=HEADERS
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/admin/layers/{populated['id']}/cascade-delete",
            headers=HEADERS,
            json={"confirmation": "DELETE DISPOSABLE LAYER"},
        ).status_code
        == 200
    )
    with Session(engine) as session:
        assert (
            session.scalar(
                select(LifecycleEvent).where(
                    LifecycleEvent.action == "cascade_delete",
                    LifecycleEvent.entity_id == uuid.UUID(populated["id"]),
                )
            )
            is not None
        )


def test_source_disable_enable_preserves_data_and_does_not_sync() -> None:
    with Session(engine) as session:
        layer = Layer(
            slug="lifecycle-source-layer",
            name="Lifecycle source layer",
            category="TEST",
            mode="external",
            geometry_types=["Point"],
            style={},
            metadata_={},
        )
        source = ExternalSource(
            layer=layer,
            slug="lifecycle-source-toggle",
            adapter="fixture",
            dataset_id="fixture-v1",
        )
        session.add(source)
        session.commit()
        source_id = str(source.id)

    disabled = client.post(
        f"/api/v1/admin/sources/{source_id}/disable", headers=HEADERS
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert (
        client.post(
            f"/api/v1/admin/sources/{source_id}/sync", headers=HEADERS
        ).status_code
        == 409
    )
    enabled = client.post(f"/api/v1/admin/sources/{source_id}/enable", headers=HEADERS)
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    with Session(engine) as session:
        source = session.get(ExternalSource, uuid.UUID(source_id))
        assert source is not None
        assert source.status == "never"
