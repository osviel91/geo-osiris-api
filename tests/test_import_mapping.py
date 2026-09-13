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


def create_layer(slug: str) -> dict:
    response = client.post(
        "/api/v1/admin/layers",
        headers=HEADERS,
        json={
            "slug": slug,
            "name": slug,
            "category": "TEST",
            "mode": "managed",
            "geometry_types": ["Point"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def stage(layer_id: str, content: str, mapping: dict | None = None) -> dict:
    payload = {
        "layer_id": layer_id,
        "filename": "mapping.csv",
        "format": "csv",
        "content": content,
    }
    if mapping is not None:
        payload["csv_mapping"] = mapping
    response = client.post("/api/v1/admin/imports", headers=HEADERS, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_csv_mapping_is_normalized_persisted_and_reproducible() -> None:
    layer = create_layer("mapping")
    staged = stage(
        layer["id"],
        "lng,lat,id,network\n-3.7,40.4,EA4,BrandMeister\n",
        {
            "longitude": "lng",
            "latitude": "lat",
            "external_id": "id",
            "properties": {"network": "network"},
        },
    )

    assert staged["csv_headers"] == ["lng", "lat", "id", "network"]
    assert staged["csv_mapping"] == {
        "longitude": "lng",
        "latitude": "lat",
        "external_id": "id",
        "properties": {"network": "network"},
    }
    assert staged["mapping_version"] == "1"
    assert staged["valid_count"] == 1

    rows = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows", headers=HEADERS
    ).json()["items"]
    assert rows[0]["external_id"] == "EA4"
    assert rows[0]["properties"] == {"network": "BrandMeister"}
    assert rows[0]["geometry"] == {"type": "Point", "coordinates": [-3.7, 40.4]}


def test_csv_default_mapping_collects_remaining_columns() -> None:
    layer = create_layer("mapping-default")
    staged = stage(
        layer["id"], "longitude,latitude,callsign,frequency\n-3.7,40.4,EA4,145.5\n"
    )

    assert staged["csv_mapping"]["properties"] == {
        "callsign": "callsign",
        "frequency": "frequency",
    }
    assert staged["csv_mapping"]["external_id"] is None


def test_csv_row_level_errors_do_not_abort_import() -> None:
    layer = create_layer("mapping-errors")
    staged = stage(
        layer["id"],
        "longitude,latitude,callsign\n"
        "-3.7,40.4,OK\n"
        "-3.8,,MISSING\n"
        "abc,40.4,BADLON\n"
        "200,40.4,RANGE\n",
    )

    assert staged["row_count"] == 4
    assert staged["valid_count"] == 1
    assert staged["invalid_count"] == 3

    invalid = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows?state=invalid", headers=HEADERS
    ).json()["items"]
    assert [row["row_number"] for row in invalid] == [2, 3, 4]
    assert [row["validation_error"] for row in invalid] == [
        "Missing latitude value",
        "Invalid longitude value",
        "Coordinates are outside WGS84 bounds",
    ]

    blocked = client.post(
        f"/api/v1/admin/imports/{staged['id']}/commit",
        headers=HEADERS,
        json={"status": "published"},
    )
    assert blocked.status_code == 409


def test_csv_mapping_validation_rejects_bad_mappings() -> None:
    layer = create_layer("mapping-invalid")
    cases = [
        ("lng,lat\n-3.7,40.4\n", {"longitude": "missing", "latitude": "lat"}),
        (
            "longitude,latitude\n-3.7,40.4\n",
            {"longitude": "longitude", "latitude": "longitude"},
        ),
        (
            "longitude,latitude\n-3.7,40.4\n",
            {"longitude": "longitude", "latitude": "latitude", "properties": []},
        ),
        (
            "longitude,latitude\n-3.7,40.4\n",
            {
                "longitude": "longitude",
                "latitude": "latitude",
                "properties": {"x": "longitude"},
            },
        ),
    ]
    for content, mapping in cases:
        response = client.post(
            "/api/v1/admin/imports",
            headers=HEADERS,
            json={
                "layer_id": layer["id"],
                "filename": "bad.csv",
                "format": "csv",
                "content": content,
                "csv_mapping": mapping,
            },
        )
        assert response.status_code == 422, (mapping, response.text)


def test_import_row_limit(monkeypatch) -> None:
    monkeypatch.setattr("app.imports.MAX_IMPORT_ROWS", 2)
    layer = create_layer("mapping-rows")
    response = client.post(
        "/api/v1/admin/imports",
        headers=HEADERS,
        json={
            "layer_id": layer["id"],
            "filename": "rows.csv",
            "format": "csv",
            "content": "longitude,latitude\n1.0,1.0\n2.0,2.0\n3.0,3.0\n",
        },
    )
    assert response.status_code == 422


def test_csv_field_size_limit() -> None:
    layer = create_layer("mapping-field")
    response = client.post(
        "/api/v1/admin/imports",
        headers=HEADERS,
        json={
            "layer_id": layer["id"],
            "filename": "field.csv",
            "format": "csv",
            "content": "longitude,latitude,note\n1.0,2.0," + "x" * 70_000 + "\n",
        },
    )
    assert response.status_code == 422
