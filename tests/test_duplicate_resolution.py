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
        f"/api/v1/admin/imports/{staged['id']}/commit",
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

    assert (
        client.post(
            f"/api/v1/admin/imports/{staged['id']}/commit",
            headers=HEADERS,
            json={"status": "published"},
        ).status_code
        == 200
    )
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
    assert (
        client.post(
            f"/api/v1/admin/imports/{staged['id']}/commit",
            headers=HEADERS,
            json={"status": "published"},
        ).status_code
        == 200
    )
    features = client.get(
        f"/api/v1/admin/layers/{layer['id']}/features", headers=HEADERS
    ).json()["items"]
    provenance = client.get(
        f"/api/v1/admin/features/{features[0]['id']}", headers=HEADERS
    ).json()["provenance"]
    assert provenance[0]["source_name"] == "duplicates.csv"
    assert provenance[0]["source_url"] is None
