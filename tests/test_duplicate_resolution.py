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


def stage(layer_id: str, content: str, mapping: dict | None = None, **extra) -> dict:
    payload = {
        "layer_id": layer_id,
        "filename": "duplicates.csv",
        "format": "csv",
        "content": content,
    }
    if mapping is not None:
        payload["csv_mapping"] = mapping
    payload.update(extra)
    response = client.post("/api/v1/admin/imports", headers=HEADERS, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def rows(import_id: str) -> list[dict]:
    response = client.get(f"/api/v1/admin/imports/{import_id}/rows", headers=HEADERS)
    return response.json()["items"]


def import_detail(import_id: str) -> dict:
    response = client.get(f"/api/v1/admin/imports/{import_id}", headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def resolve(import_id: str, row_number: int, resolution: str) -> dict:
    response = client.post(
        f"/api/v1/admin/imports/{import_id}/rows/{row_number}/resolution",
        headers=HEADERS,
        json={"resolution": resolution},
    )
    assert response.status_code == 200, response.text
    return response.json()


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
        headers=PUBLISH_HEADERS,
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
    assert commit(skipped["id"]).status_code == 200
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
    assert commit(forced["id"]).status_code == 200
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
    assert commit(clean["id"]).status_code == 200
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


def test_import_resolution_aggregates_track_candidate_state() -> None:
    layer = create_layer(
        "dup-aggregate", duplicate_detection={"identity_properties": ["callsign"]}
    )
    create_feature(layer["id"], -3.7, 40.4, properties={"callsign": "A"})
    create_feature(layer["id"], -3.8, 40.5, properties={"callsign": "B"})

    clean = stage(layer["id"], "longitude,latitude,callsign\n-1.0,40.0,UNIQUE\n")
    detail = import_detail(clean["id"])
    assert detail["candidate_count"] == 0
    assert detail["resolved_candidate_count"] == 0
    assert detail["unresolved_candidate_count"] == 0

    staged = stage(
        layer["id"], "longitude,latitude,callsign\n-3.7,40.4,A\n-3.8,40.5,B\n"
    )
    detail = import_detail(staged["id"])
    assert detail["candidate_count"] == 2
    assert detail["resolved_candidate_count"] == 0
    assert detail["unresolved_candidate_count"] == 2

    resolve(staged["id"], 1, "skip")
    detail = import_detail(staged["id"])
    assert detail["candidate_count"] == 2
    assert detail["resolved_candidate_count"] == 1
    assert detail["unresolved_candidate_count"] == 1

    resolve(staged["id"], 2, "skip")
    detail = import_detail(staged["id"])
    assert detail["resolved_candidate_count"] == 2
    assert detail["unresolved_candidate_count"] == 0


def test_skip_and_import_anyway_both_count_as_resolved() -> None:
    layer = create_layer(
        "dup-both-resolved", duplicate_detection={"identity_properties": ["callsign"]}
    )
    create_feature(layer["id"], -3.7, 40.4, properties={"callsign": "A"})
    create_feature(layer["id"], -3.8, 40.5, properties={"callsign": "B"})
    staged = stage(
        layer["id"], "longitude,latitude,callsign\n-3.7,40.4,A\n-3.8,40.5,B\n"
    )
    resolve(staged["id"], 1, "skip")
    resolve(staged["id"], 2, "import_anyway")
    detail = import_detail(staged["id"])
    assert detail["resolved_candidate_count"] == 2
    assert detail["unresolved_candidate_count"] == 0


def test_cancelled_import_retains_resolution_state() -> None:
    layer = create_layer(
        "dup-cancel-resolved", duplicate_detection={"identity_properties": ["callsign"]}
    )
    create_feature(layer["id"], -3.7, 40.4, properties={"callsign": "A"})
    create_feature(layer["id"], -3.8, 40.5, properties={"callsign": "B"})
    staged = stage(
        layer["id"], "longitude,latitude,callsign\n-3.7,40.4,A\n-3.8,40.5,B\n"
    )
    resolve(staged["id"], 1, "skip")
    resolve(staged["id"], 2, "import_anyway")
    assert (
        client.delete(
            f"/api/v1/admin/imports/{staged['id']}", headers=HEADERS
        ).status_code
        == 200
    )
    detail = import_detail(staged["id"])
    assert detail["status"] == "cancelled"
    assert detail["resolved_candidate_count"] == 2
    assert detail["unresolved_candidate_count"] == 0
    stored = rows(staged["id"])
    assert [row["resolution"] for row in stored] == ["skip", "import_anyway"]


def test_commit_rejects_unresolved_candidates_independently() -> None:
    layer = create_layer(
        "dup-independent", duplicate_detection={"identity_properties": ["callsign"]}
    )
    create_feature(layer["id"], -3.7, 40.4, properties={"callsign": "A"})
    staged = stage(layer["id"], "longitude,latitude,callsign\n-3.7,40.4,A\n")
    detail = import_detail(staged["id"])
    assert detail["invalid_count"] == 0
    assert detail["unresolved_candidate_count"] == 1
    blocked = client.post(
        f"/api/v1/admin/imports/{staged['id']}/approval-request",
        headers=HEADERS,
        json={"status": "published"},
    )
    assert blocked.status_code == 409
    assert "duplicate" in blocked.json()["detail"].lower()


def test_import_provenance_source_round_trip() -> None:
    layer = create_layer("import-provenance")
    staged = stage(
        layer["id"],
        "longitude,latitude,callsign\n-3.7,40.4,EA1\n",
        source_name="URE Madrid repeater directory",
        source_url="https://example.test/ure",
    )
    detail = import_detail(staged["id"])
    assert detail["source_name"] == "URE Madrid repeater directory"
    assert detail["source_url"] == "https://example.test/ure"

    assert commit(staged["id"]).status_code == 200
    features = client.get(
        f"/api/v1/admin/layers/{layer['id']}/features", headers=HEADERS
    ).json()["items"]
    provenance = client.get(
        f"/api/v1/admin/features/{features[0]['id']}", headers=HEADERS
    ).json()["provenance"]
    assert provenance[0]["source_name"] == "URE Madrid repeater directory"
    assert provenance[0]["source_url"] == "https://example.test/ure"
    assert provenance[0]["import_id"] == staged["id"]


def test_import_provenance_falls_back_to_filename() -> None:
    layer = create_layer("import-provenance-fallback")
    staged = stage(layer["id"], "longitude,latitude,callsign\n-3.7,40.4,EA1\n")
    detail = import_detail(staged["id"])
    assert detail["source_name"] is None
    assert detail["source_url"] is None
    assert commit(staged["id"]).status_code == 200
    features = client.get(
        f"/api/v1/admin/layers/{layer['id']}/features", headers=HEADERS
    ).json()["items"]
    provenance = client.get(
        f"/api/v1/admin/features/{features[0]['id']}", headers=HEADERS
    ).json()["provenance"]
    assert provenance[0]["source_name"] == "duplicates.csv"
    assert provenance[0]["source_url"] is None


COMPOSITE_CONFIG = {
    "identity_groups": [["callsign", "rx_frequency_mhz"]],
    "spatial": {"radius_m": 300, "require_identity_signal": True},
}


def test_composite_identity_group_matches_all_properties() -> None:
    layer = create_layer("dup-composite", duplicate_detection=COMPOSITE_CONFIG)
    existing = create_feature(
        layer["id"],
        -3.7,
        40.4,
        properties={"callsign": "EA1", "rx_frequency_mhz": 145.725},
    )
    staged = stage(
        layer["id"],
        "longitude,latitude,callsign,rx_frequency_mhz\n-3.7,40.4,EA1,145.725\n",
        {
            "properties": {
                "callsign": "callsign",
                "rx_frequency_mhz": {"column": "rx_frequency_mhz", "type": "number"},
            }
        },
    )
    assert staged["candidate_count"] == 1
    match = rows(staged["id"])[0]["candidate_matches"][0]
    assert match["feature_id"] == existing["id"]
    assert {reason["type"] for reason in match["reasons"]} == {
        "property_exact",
        "spatial_proximity",
    }
    assert {
        reason["property"]
        for reason in match["reasons"]
        if reason["type"] == "property_exact"
    } == {"callsign", "rx_frequency_mhz"}


def test_composite_identity_group_rejects_different_frequency() -> None:
    layer = create_layer("dup-composite-freq", duplicate_detection=COMPOSITE_CONFIG)
    create_feature(
        layer["id"],
        -3.7,
        40.4,
        properties={"callsign": "EA1", "rx_frequency_mhz": 145.725},
    )
    staged = stage(
        layer["id"],
        "longitude,latitude,callsign,rx_frequency_mhz\n-3.7,40.4,EA1,438.5\n",
        {
            "properties": {
                "callsign": "callsign",
                "rx_frequency_mhz": {"column": "rx_frequency_mhz", "type": "number"},
            }
        },
    )
    assert staged["candidate_count"] == 0


def test_spatial_requires_identity_signal() -> None:
    layer = create_layer("dup-spatial-identity", duplicate_detection=COMPOSITE_CONFIG)
    create_feature(
        layer["id"],
        -3.7,
        40.4,
        properties={"callsign": "EA1", "rx_frequency_mhz": 145.725},
    )
    staged = stage(
        layer["id"],
        "longitude,latitude,callsign,rx_frequency_mhz\n-3.7,40.4,EA2,438.5\n",
        {
            "properties": {
                "callsign": "callsign",
                "rx_frequency_mhz": {"column": "rx_frequency_mhz", "type": "number"},
            }
        },
    )
    assert staged["candidate_count"] == 0


def test_external_id_match_triggers_without_identity_group() -> None:
    layer = create_layer("dup-extid-v2", duplicate_detection=COMPOSITE_CONFIG)
    existing = create_feature(
        layer["id"],
        10.0,
        10.0,
        external_id="ext-9",
        properties={"callsign": "OTHER", "rx_frequency_mhz": 1.0},
    )
    staged = stage(
        layer["id"],
        "longitude,latitude,external_id,callsign,rx_frequency_mhz\n"
        "-3.7,40.4,ext-9,EA1,145.725\n",
        {
            "external_id": "external_id",
            "properties": {
                "callsign": "callsign",
                "rx_frequency_mhz": {"column": "rx_frequency_mhz", "type": "number"},
            },
        },
    )
    assert staged["candidate_count"] == 1
    match = rows(staged["id"])[0]["candidate_matches"][0]
    assert match["feature_id"] == existing["id"]
    assert [reason["type"] for reason in match["reasons"]] == ["external_id"]


def test_multiple_identity_groups() -> None:
    layer = create_layer(
        "dup-groups",
        duplicate_detection={
            "identity_groups": [
                ["callsign", "rx_frequency_mhz"],
                ["locator"],
            ],
            "spatial": {"radius_m": 300, "require_identity_signal": True},
        },
    )
    existing = create_feature(
        layer["id"],
        10.0,
        10.0,
        properties={"callsign": "X", "rx_frequency_mhz": 1.0, "locator": "IN70XX"},
    )
    staged = stage(
        layer["id"],
        "longitude,latitude,callsign,rx_frequency_mhz,locator\n-3.7,40.4,Y,2.0,IN70XX\n",
        {
            "properties": {
                "callsign": "callsign",
                "rx_frequency_mhz": {"column": "rx_frequency_mhz", "type": "number"},
                "locator": "locator",
            }
        },
    )
    assert staged["candidate_count"] == 1
    match = rows(staged["id"])[0]["candidate_matches"][0]
    assert match["feature_id"] == existing["id"]
    assert [reason["property"] for reason in match["reasons"]] == ["locator"]


def test_identity_group_ignores_null_or_missing_properties() -> None:
    layer = create_layer("dup-null-incoming", duplicate_detection=COMPOSITE_CONFIG)
    create_feature(
        layer["id"],
        -3.7,
        40.4,
        properties={"callsign": "EA1", "rx_frequency_mhz": 145.725},
    )
    empty_incoming = stage(
        layer["id"],
        "longitude,latitude,callsign,rx_frequency_mhz\n-3.7,40.4,EA1,\n",
        {
            "properties": {
                "callsign": "callsign",
                "rx_frequency_mhz": {"column": "rx_frequency_mhz", "type": "number"},
            }
        },
    )
    assert empty_incoming["candidate_count"] == 0

    layer2 = create_layer("dup-null-existing", duplicate_detection=COMPOSITE_CONFIG)
    create_feature(layer2["id"], 10.0, 10.0, properties={"callsign": "EA1"})
    missing_existing = stage(
        layer2["id"],
        "longitude,latitude,callsign,rx_frequency_mhz\n10.0,10.0,EA1,145.725\n",
        {
            "properties": {
                "callsign": "callsign",
                "rx_frequency_mhz": {"column": "rx_frequency_mhz", "type": "number"},
            }
        },
    )
    assert missing_existing["candidate_count"] == 0


def test_identity_group_number_vs_string_semantics() -> None:
    layer = create_layer(
        "dup-number-string",
        duplicate_detection={"identity_groups": [["code"]]},
    )
    numeric = create_feature(layer["id"], 1.0, 1.0, properties={"code": 42})
    text = create_feature(layer["id"], 2.0, 2.0, properties={"code": "42"})

    as_number = stage(
        layer["id"],
        "longitude,latitude,code\n1.0,1.0,42\n",
        {"properties": {"code": {"column": "code", "type": "number"}}},
    )
    assert as_number["candidate_count"] == 1
    numeric_match = rows(as_number["id"])[0]["candidate_matches"][0]
    assert numeric_match["feature_id"] == numeric["id"]

    as_string = stage(
        layer["id"],
        "longitude,latitude,code\n2.0,2.0,42\n",
        {"properties": {"code": {"column": "code", "type": "string"}}},
    )
    assert as_string["candidate_count"] == 1
    assert rows(as_string["id"])[0]["candidate_matches"][0]["feature_id"] == text["id"]


def test_v1_config_still_allows_spatial_only_candidate() -> None:
    layer = create_layer(
        "dup-v1-spatial",
        duplicate_detection={
            "identity_properties": ["callsign"],
            "coordinate_radius_m": 300,
        },
    )
    create_feature(layer["id"], -3.7, 40.4, properties={"callsign": "OTHER"})
    staged = stage(layer["id"], "longitude,latitude,callsign\n-3.7,40.4,EA1\n")
    assert staged["candidate_count"] == 1
    reasons = rows(staged["id"])[0]["candidate_matches"][0]["reasons"]
    assert [reason["type"] for reason in reasons] == ["spatial_proximity"]


def test_generic_non_radio_identity_group() -> None:
    layer = create_layer(
        "dup-generic",
        duplicate_detection={
            "identity_groups": [["sensor_id", "reading_type"]],
            "spatial": {"radius_m": 50, "require_identity_signal": True},
        },
    )
    create_feature(
        layer["id"],
        -3.7,
        40.4,
        properties={"sensor_id": "S1", "reading_type": "temperature"},
    )
    different_type = stage(
        layer["id"],
        "longitude,latitude,sensor_id,reading_type\n-3.7,40.4,S1,humidity\n",
        {"properties": {"sensor_id": "sensor_id", "reading_type": "reading_type"}},
    )
    assert different_type["candidate_count"] == 0

    same_type = stage(
        layer["id"],
        "longitude,latitude,sensor_id,reading_type\n-3.7,40.4,S1,temperature\n",
        {"properties": {"sensor_id": "sensor_id", "reading_type": "reading_type"}},
    )
    assert same_type["candidate_count"] == 1
