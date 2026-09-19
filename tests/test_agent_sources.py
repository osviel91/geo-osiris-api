import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent_sources import canonical_proposal, preflight, validate_dataset
from app.database import engine
from app.main import app

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in __import__("os").environ,
    reason="requires PostGIS",
)


@pytest.fixture(autouse=True)
def empty_database():
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE import_approvals, import_rows, imports, external_sources, "
                "feature_provenance, features, layers, lifecycle_events CASCADE"
            )
        )
    yield


def proposal(**overrides):
    value = {
        "endpoint": "https://data.example.test:443/features.json",
        "slug": "agent-example",
        "name": "Agent example",
        "description": "Test source",
        "category": "TEST",
        "geometry_types": ["Point"],
        "dataset_id": "example-v1",
        "id_property": "id",
        "properties": {"name": "name"},
        "timeout_seconds": 10,
    }
    value.update(overrides)
    return value


def dataset(features=None):
    return {
        "type": "FeatureCollection",
        "features": features
        if features is not None
        else [
            {
                "type": "Feature",
                "id": "one",
                "geometry": {"type": "Point", "coordinates": [1, 2]},
                "properties": {"id": "one", "name": "One"},
            }
        ],
    }


def test_preflight_is_deterministic_and_does_not_use_database(monkeypatch):
    monkeypatch.setattr(
        "app.agent_sources._validate_url",
        lambda _: ("data.example.test", ["203.0.113.10"]),
    )
    monkeypatch.setattr(
        "app.agent_sources.fetch_dataset",
        lambda *_: (
            dataset(),
            {
                "hostname": "data.example.test",
                "addresses": ["203.0.113.10"],
                "bytes": 200,
            },
        ),
    )
    first = preflight(proposal())
    second = preflight(proposal())
    assert first.fingerprint == second.fingerprint
    assert first.summary["feature_count"] == 1


@pytest.mark.parametrize(
    "value",
    [
        {"endpoint": "http://data.example.test:443/features.json"},
        {"endpoint": "https://data.example.test:8443/features.json"},
        {"endpoint": "https://user:pass@data.example.test/features.json"},
        {"endpoint": "https://data.example.test/features.json#fragment"},
        {"endpoint": "https://localhost/features.json"},
    ],
)
def test_preflight_rejects_unsafe_endpoints(value):
    with pytest.raises(ValueError):
        canonical_proposal(proposal(**value))


def test_validate_dataset_rejects_duplicate_ids_and_missing_mapping():
    with pytest.raises(ValueError, match="duplicate"):
        validate_dataset(
            proposal(), dataset([dataset()["features"][0], dataset()["features"][0]])
        )
    feature = dataset()["features"][0].copy()
    feature["properties"] = {"id": "one"}
    with pytest.raises(ValueError, match="missing"):
        validate_dataset(proposal(), dataset([feature]))


def test_validate_dataset_rejects_type_and_geometry_errors():
    feature = dataset()["features"][0].copy()
    feature["geometry"] = {"type": "LineString", "coordinates": [[1, 2], [2, 3]]}
    with pytest.raises((ValueError, HTTPException)):
        validate_dataset(proposal(), dataset([feature]))


def test_limits_are_enforced(monkeypatch):
    monkeypatch.setattr(
        "app.agent_sources._validate_url",
        lambda _: ("data.example.test", ["203.0.113.10"]),
    )
    with pytest.raises(ValueError, match="32"):
        canonical_proposal(proposal(properties={str(i): "field" for i in range(33)}))
    with pytest.raises(ValueError, match="100"):
        canonical_proposal(proposal(name="x" * 101))


def test_stage_validation_auth_and_zero_db_mutation(monkeypatch):
    monkeypatch.setenv("GEO_STAGE_TOKEN", "stage-token")
    monkeypatch.setenv("GEO_READ_TOKEN", "read-token")
    from app.agent_sources import PreflightResult

    monkeypatch.setattr(
        "app.agent_sources._validate_url",
        lambda _: ("data.example.test", ["203.0.113.10"]),
    )
    normalized = canonical_proposal(proposal())
    result = PreflightResult(
        normalized, dataset(), "a" * 64, {"feature_count": 1}, ["warning"]
    )
    monkeypatch.setattr("app.main.preflight", lambda _: result)
    client = TestClient(app)
    payload = proposal()
    response = client.post(
        "/api/v1/admin/agent/sources/validate",
        headers={"Authorization": "Bearer stage-token"},
        json=payload,
    )
    assert response.status_code == 200
    assert response.json()["fingerprint"] == "a" * 64
    assert (
        client.post(
            "/api/v1/admin/agent/sources/validate",
            headers={"Authorization": "Bearer read-token"},
            json=payload,
        ).status_code
        == 403
    )
    assert (
        client.post("/api/v1/admin/agent/sources/validate", json=payload).status_code
        == 401
    )
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        assert session.scalar(text("SELECT count(*) FROM layers")) == 0


def test_agent_creation_sync_and_interval_gate(monkeypatch):
    monkeypatch.setenv("GEO_STAGE_TOKEN", "stage-token")
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "admin-token")
    from app.agent_sources import PreflightResult

    monkeypatch.setattr(
        "app.agent_sources._validate_url",
        lambda _: ("data.example.test", ["203.0.113.10"]),
    )
    normalized = canonical_proposal(proposal())
    result = PreflightResult(normalized, dataset(), "a" * 64, {"feature_count": 1}, [])
    monkeypatch.setattr("app.main.preflight", lambda _: result)
    client = TestClient(app)
    created = client.post(
        "/api/v1/admin/agent/sources",
        headers={"Authorization": "Bearer stage-token"},
        json={"proposal": proposal(), "fingerprint": "a" * 64},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["agent_managed"] is True and body["enabled"] is False
    source_id = body["id"]
    enabled = client.post(
        f"/api/v1/admin/sources/{source_id}/enable",
        headers={"Authorization": "Bearer admin-token"},
    )
    assert enabled.status_code == 200
    monkeypatch.setattr("app.geojson_source._request_json", lambda *_: dataset())
    synced = client.post(
        f"/api/v1/admin/agent/sources/{source_id}/sync",
        headers={"Authorization": "Bearer stage-token"},
    )
    assert synced.status_code == 200
    assert synced.json()["created"] == 1
    assert (
        client.post(
            f"/api/v1/admin/agent/sources/{source_id}/sync",
            headers={"Authorization": "Bearer stage-token"},
        ).status_code
        == 429
    )
    from sqlalchemy.orm import Session

    with Session(engine) as session:
        assert (
            session.scalar(
                text("SELECT enabled FROM layers WHERE slug = 'agent-example'")
            )
            is False
        )
