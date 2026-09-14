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


@pytest.fixture(autouse=True)
def admin_token(monkeypatch):
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
    monkeypatch.setenv("GEO_APPROVE_TOKEN", "approve-token")
    monkeypatch.setenv("GEO_PUBLISH_TOKEN", "publish-token")


def commit(import_id: str, status: str = "published"):
    assert (
        client.post(
            f"/api/v1/admin/imports/{import_id}/approval-request",
            headers=HEADERS,
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


def create_layer(slug: str, metadata: dict | None = None) -> dict:
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
        "lng,lat,id,network,empty\n-3.7,40.4,EA4,BrandMeister,\n",
        {
            "longitude": "lng",
            "latitude": "lat",
            "external_id": "id",
            "properties": {"network": "network", "empty": "empty"},
        },
    )

    assert staged["csv_headers"] == ["lng", "lat", "id", "network", "empty"]
    assert staged["csv_mapping"] == {
        "longitude": "lng",
        "latitude": "lat",
        "external_id": "id",
        "properties": {"network": "network", "empty": "empty"},
    }
    assert staged["mapping_version"] == "1"
    assert staged["valid_count"] == 1

    rows = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows", headers=HEADERS
    ).json()["items"]
    assert rows[0]["external_id"] == "EA4"
    assert rows[0]["properties"] == {"network": "BrandMeister", "empty": ""}
    assert rows[0]["geometry"] == {"type": "Point", "coordinates": [-3.7, 40.4]}


def test_typed_csv_mapping_converts_primitives_and_is_reproducible() -> None:
    layer = create_layer("mapping-typed")
    mapping = {
        "longitude": "lng",
        "latitude": "lat",
        "external_id": "callsign",
        "properties": {
            "callsign": {"column": "callsign", "type": "string"},
            "modes": {"column": "modes", "type": "json"},
            "rx_frequency_mhz": {"column": "frequency", "type": "number"},
            "dmr_color_code": {"column": "color_code", "type": "integer"},
            "enabled": {"column": "enabled", "type": "boolean"},
            "optional": {"column": "optional", "type": "number"},
        },
    }
    staged = stage(
        layer["id"],
        "lng,lat,callsign,modes,frequency,color_code,enabled,optional\n"
        '-3.7,40.4,EA4,"[""FM"", ""DMR""]",145.5,1,true,\n',
        mapping,
    )

    assert staged["mapping_version"] == "2"
    assert staged["csv_mapping"] == mapping
    read_staged = client.get(
        f"/api/v1/admin/imports/{staged['id']}", headers=HEADERS
    ).json()
    assert read_staged["mapping_version"] == "2"
    assert read_staged["csv_mapping"] == mapping
    row = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows", headers=HEADERS
    ).json()["items"][0]
    assert row["properties"] == {
        "callsign": "EA4",
        "modes": ["FM", "DMR"],
        "rx_frequency_mhz": 145.5,
        "dmr_color_code": 1,
        "enabled": True,
        "optional": None,
    }
    committed = commit(staged["id"])
    assert committed.status_code == 200, committed.text
    assert committed.json()["mapping_version"] == "2"
    assert committed.json()["status"] == "committed"
    assert committed.json()["resolved_candidate_count"] == 0
    assert committed.json()["unresolved_candidate_count"] == 0
    assert committed.json()["committed_at"] is not None
    read_committed = client.get(
        f"/api/v1/admin/imports/{staged['id']}", headers=HEADERS
    ).json()
    assert read_committed["mapping_version"] == "2"
    assert read_committed["csv_mapping"] == mapping
    properties = client.get("/api/v1/layers/mapping-typed").json()["features"][0][
        "properties"
    ]
    assert {name: properties[name] for name in row["properties"]} == row["properties"]
    assert isinstance(properties["rx_frequency_mhz"], float)
    assert isinstance(properties["dmr_color_code"], int)
    assert isinstance(properties["modes"], list)
    assert isinstance(properties["enabled"], bool)
    assert properties["optional"] is None


def test_typed_numeric_identity_property_matches_existing_candidate() -> None:
    layer = create_layer(
        "mapping-typed-identity",
        {"duplicate_detection": {"identity_properties": ["some_numeric_id"]}},
    )
    existing = client.post(
        f"/api/v1/admin/layers/{layer['id']}/features",
        headers=HEADERS,
        json={
            "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
            "properties": {"some_numeric_id": 42},
            "status": "published",
        },
    )
    assert existing.status_code == 200, existing.text
    staged = stage(
        layer["id"],
        "longitude,latitude,some_numeric_id\n-3.8,40.5,42\n",
        {
            "properties": {
                "some_numeric_id": {"column": "some_numeric_id", "type": "number"}
            }
        },
    )

    assert staged["candidate_count"] == 1
    row = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows", headers=HEADERS
    ).json()["items"][0]
    assert row["candidate_feature_ids"] == [existing.json()["id"]]
    assert row["candidate_matches"][0]["reasons"] == [
        {"type": "property_exact", "property": "some_numeric_id", "value": 42.0}
    ]
    resolved = client.post(
        f"/api/v1/admin/imports/{staged['id']}/rows/1/resolution",
        headers=HEADERS,
        json={"resolution": "import_anyway"},
    )
    assert resolved.status_code == 200, resolved.text
    committed = commit(staged["id"])
    assert committed.status_code == 200, committed.text


def test_typed_csv_mapping_converts_json_and_empty_cells_to_null() -> None:
    layer = create_layer("mapping-json")
    staged = stage(
        layer["id"],
        "longitude,latitude,modes,details,empty\n"
        '-3.7,40.4,"[""FM"", ""DMR""]","{""site"": ""A""}",\n',
        {
            "properties": {
                "modes": {"column": "modes", "type": "json"},
                "details": {"column": "details", "type": "json"},
                "empty": {"column": "empty", "type": "string"},
            }
        },
    )

    row = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows", headers=HEADERS
    ).json()["items"][0]
    assert row["properties"] == {
        "modes": ["FM", "DMR"],
        "details": {"site": "A"},
        "empty": None,
    }


@pytest.mark.parametrize(
    ("property_type", "value", "error"),
    [
        ("number", "abc", "Invalid number value for property 'value'"),
        ("json", "[not json]", "Invalid JSON value for property 'value'"),
    ],
)
def test_typed_csv_conversion_errors_are_row_level(
    property_type: str, value: str, error: str
) -> None:
    layer = create_layer(f"mapping-invalid-{property_type}")
    staged = stage(
        layer["id"],
        f"longitude,latitude,value\n-3.7,40.4,{value}\n",
        {"properties": {"value": {"column": "value", "type": property_type}}},
    )

    assert staged["valid_count"] == 0
    assert staged["invalid_count"] == 1
    invalid = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows?state=invalid", headers=HEADERS
    ).json()["items"]
    assert invalid[0]["validation_error"] == error


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
        headers=PUBLISH_HEADERS,
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
