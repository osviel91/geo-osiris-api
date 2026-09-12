from fastapi.testclient import TestClient

from app.main import TEST_FEATURES, FeatureCollection, app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_layers_lists_test_layer() -> None:
    response = client.get("/layers")

    assert response.status_code == 200
    assert response.json()["layers"] == [
        {
            "id": "test",
            "name": "Test Layer",
            "description": "Static validation layer",
            "endpoint": "/layers/test",
        }
    ]


def test_test_layer_is_valid_geojson() -> None:
    response = client.get("/layers/test")
    payload = response.json()

    assert response.status_code == 200
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) >= 1
    assert FeatureCollection.model_validate(payload).features == TEST_FEATURES
    for feature in payload["features"]:
        assert feature["geometry"]["type"] == "Point"
        longitude, latitude = feature["geometry"]["coordinates"]
        assert -180 <= longitude <= 180
        assert -90 <= latitude <= 90
