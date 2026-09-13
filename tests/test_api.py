from fastapi.testclient import TestClient

from app.main import TEST_FEATURES, app
from app.schemas import StaticFeatureCollection

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_checks_database(monkeypatch) -> None:
    monkeypatch.setattr("app.main.is_ready", lambda: True)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_service_unavailable_for_database_failure(monkeypatch) -> None:
    monkeypatch.setattr("app.main.is_ready", lambda: False)

    health = client.get("/health")
    ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 503


def test_layers_lists_test_layer(monkeypatch) -> None:
    monkeypatch.setattr("app.main.list_compatibility_layers", lambda session: [])

    response = client.get("/layers")

    assert response.status_code == 200
    assert response.json()["layers"] == [
        {
            "id": "test",
            "name": "Test Layer",
            "description": "Static validation layer",
            "endpoint": "/layers/test",
            "revision": 0,
            "data_updated_at": None,
        }
    ]


def test_test_layer_is_valid_geojson() -> None:
    response = client.get("/layers/test")
    payload = response.json()

    assert response.status_code == 200
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) >= 1
    assert StaticFeatureCollection.model_validate(payload).features == TEST_FEATURES
    for feature in payload["features"]:
        assert feature["geometry"]["type"] == "Point"
        longitude, latitude = feature["geometry"]["coordinates"]
        assert -180 <= longitude <= 180
        assert -90 <= latitude <= 90
