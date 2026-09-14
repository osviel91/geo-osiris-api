import json
import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from geoalchemy2 import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import Feature, FeatureProvenance, Layer

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="requires a PostGIS test database",
)

client = TestClient(app)
PUBLISH_HEADERS = {"Authorization": "Bearer publish-token"}


@pytest.fixture(autouse=True)
def empty_database():
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE import_approvals, import_rows, imports, external_sources, "
                "feature_provenance, "
                "features, layers CASCADE"
            )
        )
    yield
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE import_approvals, import_rows, imports, external_sources, "
                "feature_provenance, "
                "features, layers CASCADE"
            )
        )


@pytest.fixture(autouse=True)
def scoped_tokens(monkeypatch):
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("GEO_APPROVE_TOKEN", "approve-token")
    monkeypatch.setenv("GEO_PUBLISH_TOKEN", "publish-token")


def commit(import_id: str, status: str = "published"):
    headers = {"Authorization": "Bearer test-token"}
    assert (
        client.post(
            f"/api/v1/admin/imports/{import_id}/approval-request",
            headers=headers,
            json={"status": status},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/admin/imports/{import_id}/approval",
            headers={"Authorization": "Bearer approve-token"},
            json={"decision": "approve"},
        ).status_code
        == 200
    )
    return client.post(
        f"/api/v1/admin/imports/{import_id}/commit",
        headers=PUBLISH_HEADERS,
        json={"status": status},
    )


def test_persisted_layer_serializes_to_public_and_compatibility_geojson() -> None:
    layer_id = uuid.uuid4()
    feature_id = uuid.uuid4()
    with Session(engine) as session:
        layer = Layer(
            id=layer_id,
            slug="test-persisted",
            name="Persisted Test Layer",
            description="Stored in PostGIS",
            category="TEST",
            mode="managed",
            geometry_types=["Point"],
            style={},
            metadata_={},
        )
        feature = Feature(
            id=feature_id,
            layer=layer,
            geometry=WKTElement("POINT(-3.7038 40.4168)", srid=4326),
            properties={"name": "Stored point"},
            status="published",
            verified_at=datetime.now(UTC),
        )
        feature.provenance_records.extend(
            [
                FeatureProvenance(
                    source_type="manual", created_by="test", metadata_={}
                ),
                FeatureProvenance(
                    source_type="import", created_by="test", metadata_={}
                ),
            ]
        )
        session.add(feature)
        session.commit()

    layers = client.get("/api/v1/layers")
    compatibility_layers = client.get("/layers")
    public = client.get("/api/v1/layers/test-persisted")
    compatibility = client.get("/layers/test-persisted")

    assert layers.status_code == 200
    assert layers.json()[0]["feature_count"] == 1
    assert (
        compatibility_layers.json()["layers"][1]["endpoint"] == "/layers/test-persisted"
    )
    assert public.status_code == 200
    assert public.json() == compatibility.json()
    assert public.json()["features"][0]["id"] == str(feature_id)
    assert public.json()["features"][0]["geometry"] == {
        "type": "Point",
        "coordinates": [-3.7038, 40.4168],
    }
    assert public.json()["features"][0]["properties"]["layer"] == "test-persisted"
    assert compatibility_layers.json() == {
        "layers": [
            {
                "id": "test",
                "name": "Test Layer",
                "description": "Static validation layer",
                "endpoint": "/layers/test",
                "revision": 0,
                "data_updated_at": None,
            },
            {
                "id": "test-persisted",
                "name": "Persisted Test Layer",
                "description": "Stored in PostGIS",
                "endpoint": "/layers/test-persisted",
                "revision": 0,
                "data_updated_at": None,
            },
        ]
    }

    with Session(engine) as session:
        feature = session.get(Feature, feature_id)
        assert feature is not None
        assert len(feature.provenance_records) == 2


def test_archived_features_are_not_public() -> None:
    with Session(engine) as session:
        layer = Layer(
            slug="archived-test",
            name="Archived",
            category="TEST",
            mode="managed",
            geometry_types=["Point"],
            style={},
            metadata_={},
        )
        layer.features.extend(
            [
                Feature(
                    geometry=WKTElement("POINT(1 1)", srid=4326),
                    properties={},
                    status="published",
                ),
                Feature(
                    geometry=WKTElement("POINT(2 2)", srid=4326),
                    properties={},
                    status="archived",
                    archived_at=datetime.now(UTC),
                ),
            ]
        )
        session.add(layer)
        session.commit()

    response = client.get("/api/v1/layers/archived-test")

    assert response.status_code == 200
    assert len(response.json()["features"]) == 1


def test_external_ids_are_unique_per_layer_but_nullable() -> None:
    with Session(engine) as session:
        first = Layer(
            slug="first",
            name="First",
            category="TEST",
            mode="managed",
            geometry_types=["Point"],
            style={},
            metadata_={},
        )
        second = Layer(
            slug="second",
            name="Second",
            category="TEST",
            mode="managed",
            geometry_types=["Point"],
            style={},
            metadata_={},
        )
        session.add_all([first, second])
        session.flush()
        session.add_all(
            [
                Feature(
                    layer=first,
                    external_id="same",
                    geometry=WKTElement("POINT(1 1)", srid=4326),
                    properties={},
                ),
                Feature(
                    layer=second,
                    external_id="same",
                    geometry=WKTElement("POINT(2 2)", srid=4326),
                    properties={},
                ),
                Feature(
                    layer=first,
                    geometry=WKTElement("POINT(3 3)", srid=4326),
                    properties={},
                ),
                Feature(
                    layer=first,
                    geometry=WKTElement("POINT(4 4)", srid=4326),
                    properties={},
                ),
            ]
        )
        session.commit()
        session.add(
            Feature(
                layer=first,
                external_id="same",
                geometry=WKTElement("POINT(5 5)", srid=4326),
                properties={},
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_admin_manages_and_archives_generic_radio_features(monkeypatch) -> None:
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
    headers = {"Authorization": "Bearer test-token"}
    layer = client.post(
        "/api/v1/admin/layers",
        headers=headers,
        json={
            "slug": "managed-radio",
            "name": "Managed radio",
            "category": "AMATEUR_RADIO",
            "mode": "managed",
            "geometry_types": ["Point"],
        },
    )
    assert layer.status_code == 200
    layer_id = layer.json()["id"]

    updated_layer = client.patch(
        f"/api/v1/admin/layers/{layer_id}",
        headers=headers,
        json={"name": "Managed radio updated"},
    )
    assert updated_layer.json()["name"] == "Managed radio updated"

    feature = client.post(
        f"/api/v1/admin/layers/{layer_id}/features",
        headers=headers,
        json={
            "external_id": "demo-managed-1",
            "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
            "properties": {"callsign": "DEMO-MANAGED", "frequency_mhz": 145.5},
            "status": "published",
        },
    )
    assert feature.status_code == 200
    feature_id = feature.json()["id"]

    updated_feature = client.patch(
        f"/api/v1/admin/features/{feature_id}",
        headers=headers,
        json={
            "external_id": "demo-managed-1",
            "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
            "properties": {"callsign": "DEMO-MANAGED", "frequency_mhz": 145.6},
            "status": "published",
        },
    )
    assert updated_feature.status_code == 200
    public = client.get("/api/v1/layers/managed-radio").json()
    assert public["features"][0]["properties"]["frequency_mhz"] == 145.6

    archived = client.delete(f"/api/v1/admin/features/{feature_id}", headers=headers)
    assert archived.status_code == 200
    assert client.get("/api/v1/layers/managed-radio").json()["features"] == []


def _freshness(layer_id: str) -> tuple[int, datetime | None]:
    with Session(engine) as session:
        layer = session.get(Layer, uuid.UUID(layer_id))
        assert layer is not None
        return layer.revision, layer.data_updated_at


def test_layer_freshness_tracks_published_data_only(monkeypatch) -> None:
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
    headers = {"Authorization": "Bearer test-token"}
    layer_id = client.post(
        "/api/v1/admin/layers",
        headers=headers,
        json={
            "slug": "freshness",
            "name": "Freshness",
            "category": "TEST",
            "mode": "managed",
            "geometry_types": ["Point"],
        },
    ).json()["id"]

    assert _freshness(layer_id) == (0, None)

    assert (
        client.patch(
            f"/api/v1/admin/layers/{layer_id}",
            headers=headers,
            json={"name": "Renamed", "style": {"marker": "dot"}},
        ).status_code
        == 200
    )
    assert _freshness(layer_id) == (0, None)

    draft = client.post(
        f"/api/v1/admin/layers/{layer_id}/features",
        headers=headers,
        json={
            "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
            "properties": {"callsign": "FRESH-1"},
            "status": "draft",
        },
    ).json()
    assert _freshness(layer_id) == (0, None)

    feature_id = draft["id"]
    assert (
        client.patch(
            f"/api/v1/admin/features/{feature_id}",
            headers=headers,
            json={
                "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
                "properties": {"callsign": "FRESH-1"},
                "status": "published",
            },
        ).status_code
        == 200
    )
    revision, updated_at = _freshness(layer_id)
    assert revision == 1
    assert updated_at is not None

    assert (
        client.patch(
            f"/api/v1/admin/features/{feature_id}",
            headers=headers,
            json={
                "geometry": {"type": "Point", "coordinates": [-3.8, 40.5]},
                "properties": {"callsign": "FRESH-1"},
                "status": "published",
            },
        ).status_code
        == 200
    )
    assert _freshness(layer_id)[0] == 2

    assert (
        client.delete(
            f"/api/v1/admin/features/{feature_id}", headers=headers
        ).status_code
        == 200
    )
    assert _freshness(layer_id)[0] == 3

    draft_import = client.post(
        "/api/v1/admin/imports",
        headers=headers,
        json={
            "layer_id": layer_id,
            "filename": "draft.csv",
            "format": "csv",
            "content": "longitude,latitude,callsign\n-3.9,40.6,FRESH-2\n",
        },
    ).json()
    assert commit(draft_import["id"], "draft").status_code == 200
    assert _freshness(layer_id)[0] == 3

    published_import = client.post(
        "/api/v1/admin/imports",
        headers=headers,
        json={
            "layer_id": layer_id,
            "filename": "published.csv",
            "format": "csv",
            "content": "longitude,latitude,callsign\n-4.0,40.7,FRESH-3\n",
        },
    ).json()
    assert commit(published_import["id"]).status_code == 200
    assert _freshness(layer_id)[0] == 4


def test_geojson_staging_validates_and_cancels_without_creating_features(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
    headers = {"Authorization": "Bearer test-token"}
    layer = client.post(
        "/api/v1/admin/layers",
        headers=headers,
        json={
            "slug": "geojson-staging",
            "name": "GeoJSON staging",
            "category": "TEST",
            "mode": "managed",
            "geometry_types": ["Point"],
        },
    ).json()
    staged = client.post(
        "/api/v1/admin/imports",
        headers=headers,
        json={
            "layer_id": layer["id"],
            "filename": "repeaters.geojson",
            "format": "geojson",
            "content": json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [-3.7, 40.4],
                            },
                            "properties": {"callsign": "DEMO-STAGED"},
                        },
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [200, 40.4],
                            },
                            "properties": {},
                        },
                    ],
                }
            ),
        },
    )

    assert staged.status_code == 200
    assert staged.json()["row_count"] == 2
    assert staged.json()["invalid_count"] == 1
    assert client.get("/api/v1/layers/geojson-staging").json()["features"] == []

    assert (
        client.delete(
            f"/api/v1/admin/imports/{staged.json()['id']}", headers=headers
        ).status_code
        == 200
    )
    cancelled = client.get(
        f"/api/v1/admin/imports/{staged.json()['id']}", headers=headers
    ).json()
    assert cancelled["status"] == "cancelled"
    assert (
        len(
            client.get(
                f"/api/v1/admin/imports/{staged.json()['id']}/rows",
                headers=headers,
            ).json()["items"]
        )
        == 2
    )


def test_csv_import_reports_candidates_then_commits_to_public_geojson(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
    headers = {"Authorization": "Bearer test-token"}
    layer = client.post(
        "/api/v1/admin/layers",
        headers=headers,
        json={
            "slug": "csv-staging",
            "name": "CSV staging",
            "category": "TEST",
            "mode": "managed",
            "geometry_types": ["Point"],
            "metadata_": {"duplicate_detection": {"identity_properties": ["callsign"]}},
        },
    ).json()
    existing = client.post(
        f"/api/v1/admin/layers/{layer['id']}/features",
        headers=headers,
        json={
            "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
            "properties": {"callsign": "DEMO-DUPLICATE"},
            "status": "published",
        },
    ).json()
    candidates = client.post(
        "/api/v1/admin/imports",
        headers=headers,
        json={
            "layer_id": layer["id"],
            "filename": "candidate.csv",
            "format": "csv",
            "content": "longitude,latitude,callsign\n-3.7,40.4,DEMO-DUPLICATE\n",
        },
    )

    assert candidates.json()["candidate_count"] == 1
    candidate_rows = client.get(
        f"/api/v1/admin/imports/{candidates.json()['id']}/rows", headers=headers
    ).json()
    assert candidate_rows["items"][0]["candidate_feature_ids"] == [existing["id"]]
    assert (
        client.post(
            f"/api/v1/admin/imports/{candidates.json()['id']}/commit",
            headers=PUBLISH_HEADERS,
            json={"status": "published"},
        ).status_code
        == 409
    )

    clean = client.post(
        "/api/v1/admin/imports",
        headers=headers,
        json={
            "layer_id": layer["id"],
            "filename": "clean.csv",
            "format": "csv",
            "content": "longitude,latitude,callsign\n-3.8,40.5,DEMO-IMPORTED\n",
        },
    )
    committed = commit(clean.json()["id"])

    assert committed.json()["status"] == "committed"
    public = client.get("/api/v1/layers/csv-staging").json()
    assert {feature["properties"]["callsign"] for feature in public["features"]} == {
        "DEMO-DUPLICATE",
        "DEMO-IMPORTED",
    }
    assert "/layers/csv-staging" in [
        layer["endpoint"] for layer in client.get("/layers").json()["layers"]
    ]


def _managed_layer_with_feature(monkeypatch, headers, status="published"):
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
    layer = client.post(
        "/api/v1/admin/layers",
        headers=headers,
        json={
            "slug": f"patch-{uuid.uuid4().hex[:8]}",
            "name": "Patch layer",
            "category": "TEST",
            "mode": "managed",
            "geometry_types": ["Point"],
        },
    ).json()
    feature = client.post(
        f"/api/v1/admin/layers/{layer['id']}/features",
        headers=headers,
        json={
            "external_id": "patch-1",
            "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
            "properties": {"callsign": "PATCH-1", "frequency_mhz": 145.5},
            "status": status,
        },
    ).json()
    return layer, feature


def _provenance_count(feature_id: str) -> int:
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(FeatureProvenance)
            .where(FeatureProvenance.feature_id == uuid.UUID(feature_id))
        )


def _stored(feature_id: str) -> tuple[dict, str, object]:
    with Session(engine) as session:
        feature = session.get(Feature, uuid.UUID(feature_id))
        assert feature is not None
        geometry = session.scalar(select(func.ST_AsText(feature.geometry)))
        return dict(feature.properties), feature.status, geometry


def test_patch_single_property_merges_and_preserves_others(monkeypatch) -> None:
    headers = {"Authorization": "Bearer test-token"}
    _, feature = _managed_layer_with_feature(monkeypatch, headers)

    response = client.patch(
        f"/api/v1/admin/features/{feature['id']}",
        headers=headers,
        json={"properties": {"frequency_mhz": 145.6}},
    )

    assert response.status_code == 200
    properties, status, _ = _stored(feature["id"])
    assert properties == {"callsign": "PATCH-1", "frequency_mhz": 145.6}
    assert status == "published"


def test_patch_null_removes_property(monkeypatch) -> None:
    headers = {"Authorization": "Bearer test-token"}
    _, feature = _managed_layer_with_feature(monkeypatch, headers)

    assert (
        client.patch(
            f"/api/v1/admin/features/{feature['id']}",
            headers=headers,
            json={"properties": {"frequency_mhz": None}},
        ).status_code
        == 200
    )
    properties, _, _ = _stored(feature["id"])
    assert properties == {"callsign": "PATCH-1"}


def test_patch_omitted_status_and_geometry_are_preserved(monkeypatch) -> None:
    headers = {"Authorization": "Bearer test-token"}
    _, feature = _managed_layer_with_feature(monkeypatch, headers, status="published")
    _, _, geometry_before = _stored(feature["id"])

    response = client.patch(
        f"/api/v1/admin/features/{feature['id']}",
        headers=headers,
        json={"properties": {"callsign": "PATCH-1"}},
    )

    assert response.status_code == 200
    _, status, geometry_after = _stored(feature["id"])
    assert status == "published"
    assert geometry_after == geometry_before
    assert response.json()["status"] == "published"


def test_patch_explicit_status_transition_still_works(monkeypatch) -> None:
    headers = {"Authorization": "Bearer test-token"}
    _, feature = _managed_layer_with_feature(monkeypatch, headers, status="draft")

    response = client.patch(
        f"/api/v1/admin/features/{feature['id']}",
        headers=headers,
        json={"status": "published"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "published"
    assert _stored(feature["id"])[1] == "published"


def test_patch_appends_one_provenance_and_retains_history(monkeypatch) -> None:
    headers = {"Authorization": "Bearer test-token"}
    _, feature = _managed_layer_with_feature(monkeypatch, headers)
    before = _provenance_count(feature["id"])

    client.patch(
        f"/api/v1/admin/features/{feature['id']}",
        headers=headers,
        json={
            "properties": {"frequency_mhz": 145.6},
            "source_name": "Phase 5C administrative normalization",
            "source_record_id": "repe144_N.php:PATCH-1:145.5000",
        },
    )

    assert _provenance_count(feature["id"]) == before + 1
    with Session(engine) as session:
        edit = session.scalar(
            select(FeatureProvenance).where(
                FeatureProvenance.feature_id == uuid.UUID(feature["id"]),
                FeatureProvenance.metadata_["action"].astext == "edit",
            )
        )
        assert edit is not None
        assert edit.metadata_["changed"] == ["properties"]
        assert edit.metadata_["actor"] == "admin"
        assert edit.source_name == "Phase 5C administrative normalization"
        assert _provenance_count(feature["id"]) == before + 1


def test_patch_invalid_partial_payload_returns_422(monkeypatch) -> None:
    headers = {"Authorization": "Bearer test-token"}
    _, feature = _managed_layer_with_feature(monkeypatch, headers)

    assert (
        client.patch(
            f"/api/v1/admin/features/{feature['id']}",
            headers=headers,
            json={"status": "not-a-status"},
        ).status_code
        == 422
    )
