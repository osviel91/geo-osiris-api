import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import engine
from app.main import app

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="requires a PostGIS test database",
)

client = TestClient(app)
HEADERS = {"Authorization": "Bearer test-token"}


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


@pytest.fixture(autouse=True)
def admin_token(monkeypatch):
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-token")


def create_layer(slug: str, **metadata) -> dict:
    response = client.post(
        "/api/v1/admin/layers",
        headers=HEADERS,
        json={
            "slug": slug,
            "name": slug,
            "category": "TEST",
            "mode": "managed",
            "geometry_types": ["Point"],
            "metadata_": metadata,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_feature(
    layer_id: str,
    longitude: float,
    latitude: float,
    external_id: str | None = None,
    properties: dict | None = None,
) -> dict:
    payload = {
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": properties or {},
        "status": "published",
    }
    if external_id is not None:
        payload["external_id"] = external_id
    response = client.post(
        f"/api/v1/admin/layers/{layer_id}/features", headers=HEADERS, json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


def stage(layer_id: str, content: str, mapping: dict | None = None) -> dict:
    payload = {
        "layer_id": layer_id,
        "filename": "duplicates.csv",
        "format": "csv",
        "content": content,
    }
    if mapping is not None:
        payload["csv_mapping"] = mapping
    response = client.post("/api/v1/admin/imports", headers=HEADERS, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def rows(import_id: str) -> list[dict]:
    response = client.get(f"/api/v1/admin/imports/{import_id}/rows", headers=HEADERS)
    return response.json()["items"]


def test_candidate_matches_expose_generic_reasons() -> None:
    layer = create_layer(
        "dup-reasons",
        duplicate_detection={
            "identity_properties": ["callsign"],
            "coordinate_radius_m": 300,
        },
    )
    existing = create_feature(
        layer["id"], -3.7, 40.4, external_id="ext-1", properties={"callsign": "EA1"}
    )
    staged = stage(
        layer["id"],
        "longitude,latitude,external_id,callsign\n-3.7,40.4,ext-1,EA1\n",
        {"external_id": "external_id", "properties": {"callsign": "callsign"}},
    )

    assert staged["candidate_count"] == 1
    match = rows(staged["id"])[0]["candidate_matches"][0]
    assert match["feature_id"] == existing["id"]
    assert {reason["type"] for reason in match["reasons"]} == {
        "external_id",
        "property_exact",
        "spatial_proximity",
    }
    proximity = next(
        reason for reason in match["reasons"] if reason["type"] == "spatial_proximity"
    )
    assert proximity["threshold_m"] == 300
    assert proximity["distance_m"] == 0.0
    assert match["summary"]["external_id"] == "ext-1"
    assert match["summary"]["status"] == "published"


def test_duplicate_engine_requires_explicit_configuration() -> None:
    layer = create_layer("dup-plain")
    create_feature(layer["id"], -3.7, 40.4, properties={"callsign": "EA1"})
    staged = stage(layer["id"], "longitude,latitude,callsign\n-3.7,40.4,EA1\n")
    assert staged["candidate_count"] == 0


def test_candidate_matches_are_bounded() -> None:
    layer = create_layer(
        "dup-bounded", duplicate_detection={"identity_properties": ["callsign"]}
    )
    for index in range(6):
        create_feature(
            layer["id"], 1.0 + index / 1000, 40.0, properties={"callsign": "SAME"}
        )
    staged = stage(layer["id"], "longitude,latitude,callsign\n1.0,40.0,SAME\n")
    assert len(rows(staged["id"])[0]["candidate_matches"]) == 5


def test_resolution_skip_and_import_anyway_control_commit() -> None:
    layer = create_layer(
        "dup-resolve", duplicate_detection={"identity_properties": ["callsign"]}
    )
    create_feature(layer["id"], -3.7, 40.4, properties={"callsign": "DUP"})
    public = "/api/v1/layers/dup-resolve"

    skipped = stage(layer["id"], "longitude,latitude,callsign\n-3.7,40.4,DUP\n")
    blocked = client.post(
        f"/api/v1/admin/imports/{skipped['id']}/commit",
        headers=HEADERS,
        json={"status": "published"},
    )
    assert blocked.status_code == 409
    resolved = client.post(
        f"/api/v1/admin/imports/{skipped['id']}/rows/1/resolution",
        headers=HEADERS,
        json={"resolution": "skip"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolution"] == "skip"
    assert resolved.json()["resolved_at"] is not None
    assert (
        client.post(
            f"/api/v1/admin/imports/{skipped['id']}/commit",
            headers=HEADERS,
            json={"status": "published"},
        ).status_code
        == 200
    )
    assert len(client.get(public).json()["features"]) == 1

    forced = stage(layer["id"], "longitude,latitude,callsign\n-3.7,40.4,DUP\n")
    assert (
        client.post(
            f"/api/v1/admin/imports/{forced['id']}/rows/1/resolution",
            headers=HEADERS,
            json={"resolution": "import_anyway"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/admin/imports/{forced['id']}/commit",
            headers=HEADERS,
            json={"status": "published"},
        ).status_code
        == 200
    )
    assert len(client.get(public).json()["features"]) == 2


def test_resolution_requires_candidates_and_validated_import() -> None:
    layer = create_layer(
        "dup-invalid", duplicate_detection={"identity_properties": ["callsign"]}
    )
    clean = stage(layer["id"], "longitude,latitude,callsign\n-3.7,40.4,UNIQUE\n")
    no_candidates = client.post(
        f"/api/v1/admin/imports/{clean['id']}/rows/1/resolution",
        headers=HEADERS,
        json={"resolution": "skip"},
    )
    assert no_candidates.status_code == 409
    assert (
        client.post(
            f"/api/v1/admin/imports/{clean['id']}/commit",
            headers=HEADERS,
            json={"status": "published"},
        ).status_code
        == 200
    )
    after_commit = client.post(
        f"/api/v1/admin/imports/{clean['id']}/rows/1/resolution",
        headers=HEADERS,
        json={"resolution": "skip"},
    )
    assert after_commit.status_code == 409
    assert (
        client.post(
            f"/api/v1/admin/imports/{clean['id']}/rows/1/resolution",
            headers=HEADERS,
            json={"resolution": "merge"},
        ).status_code
        == 422
    )


def test_feature_edit_appends_provenance() -> None:
    layer = create_layer("edit-provenance")
    feature = create_feature(layer["id"], 1.0, 1.0, properties={"a": 1})
    detail = client.get(
        f"/api/v1/admin/features/{feature['id']}", headers=HEADERS
    ).json()
    assert len(detail["provenance"]) == 1

    assert (
        client.patch(
            f"/api/v1/admin/features/{feature['id']}",
            headers=HEADERS,
            json={
                "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
                "properties": {"a": 2},
                "status": "published",
            },
        ).status_code
        == 200
    )
    detail = client.get(
        f"/api/v1/admin/features/{feature['id']}", headers=HEADERS
    ).json()
    assert len(detail["provenance"]) == 2
    edit = detail["provenance"][1]
    assert edit["metadata_"]["action"] == "edit"
    assert "properties" in edit["metadata_"]["changed"]
