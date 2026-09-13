import json
import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from geoalchemy2 import WKTElement
from sqlalchemy import text
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


@pytest.fixture(autouse=True)
def empty_database():
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE import_rows, imports, external_sources, feature_provenance, "
                "features, layers CASCADE"
            )
        )
    yield
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE import_rows, imports, external_sources, feature_provenance, "
                "features, layers CASCADE"
            )
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
            },
            {
                "id": "test-persisted",
                "name": "Persisted Test Layer",
                "description": "Stored in PostGIS",
                "endpoint": "/layers/test-persisted",
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
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-token")
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


def test_geojson_staging_validates_and_cancels_without_creating_features(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-token")
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
    assert (
        client.get(
            f"/api/v1/admin/imports/{staged.json()['id']}", headers=headers
        ).json()["rows"]
        == []
    )


def test_csv_import_reports_candidates_then_commits_to_public_geojson(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-token")
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
    assert candidates.json()["rows"][0]["candidate_feature_ids"] == [existing["id"]]
    assert (
        client.post(
            f"/api/v1/admin/imports/{candidates.json()['id']}/commit",
            headers=headers,
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
    committed = client.post(
        f"/api/v1/admin/imports/{clean.json()['id']}/commit",
        headers=headers,
        json={"status": "published"},
    )

    assert committed.json()["status"] == "committed"
    public = client.get("/api/v1/layers/csv-staging").json()
    assert {feature["properties"]["callsign"] for feature in public["features"]} == {
        "DEMO-DUPLICATE",
        "DEMO-IMPORTED",
    }
    assert "/layers/csv-staging" in [
        layer["endpoint"] for layer in client.get("/layers").json()["layers"]
    ]
