import uuid
from json import JSONDecodeError
from urllib.error import HTTPError

import pytest

from app.geojson_source import GeoJSONAdapter
from app.models import ExternalSource


def source(config: dict, endpoint: str = "https://data.example.test/features.geojson"):
    return ExternalSource(
        layer_id=uuid.uuid4(),
        slug="public-fixture",
        adapter="geojson",
        dataset_id="fixture-v1",
        endpoint=endpoint,
        adapter_config=config,
        status="never",
    )


def test_geojson_adapter_fetches_and_normalizes_mapped_properties(monkeypatch) -> None:
    adapter = GeoJSONAdapter()
    fixture = source(
        {"id_property": "station_id", "properties": {"name": "label", "kind": "type"}}
    )
    monkeypatch.setattr(
        "app.geojson_source._request_json",
        lambda *_args, **_kwargs: {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
                    "properties": {
                        "station_id": "station-1",
                        "label": "Madrid",
                        "type": "sensor",
                        "discard": "not stored",
                    },
                }
            ],
        },
    )

    records = adapter.fetch(fixture)
    normalized = adapter.normalize(records[0], fixture)

    assert normalized.external_id == "station-1"
    assert normalized.geometry == {"type": "Point", "coordinates": [-3.7, 40.4]}
    assert normalized.properties == {"name": "Madrid", "kind": "sensor"}
    assert normalized.source_url == fixture.endpoint


def test_geojson_adapter_uses_feature_id_and_rejects_invalid_configuration() -> None:
    adapter = GeoJSONAdapter()
    record = {
        "type": "Feature",
        "id": 12,
        "geometry": {"type": "Point", "coordinates": [1, 2]},
        "properties": {"name": "Fixture"},
    }

    assert (
        adapter.normalize(record, source({"properties": {"name": "name"}})).external_id
        == "12"
    )
    with pytest.raises(ValueError, match="HTTPS"):
        adapter.fetch(
            source({"properties": {}}, "http://example.test/features.geojson")
        )
    with pytest.raises(ValueError, match="must map"):
        adapter.normalize(record, source({"properties": ["name"]}))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"type": "FeatureCollection", "features": {}},
        {"type": "Feature", "features": []},
    ],
)
def test_geojson_adapter_rejects_non_feature_collections(
    payload: object, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.geojson_source._request_json", lambda *_args, **_kwargs: payload
    )

    with pytest.raises(ValueError, match="FeatureCollection"):
        GeoJSONAdapter().fetch(source({"properties": {}}))


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timeout"),
        HTTPError("https://data.example.test", 503, "unavailable", {}, None),
        JSONDecodeError("bad JSON", "{", 1),
    ],
)
def test_geojson_adapter_propagates_fetch_failures(
    error: Exception, monkeypatch
) -> None:
    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr("app.geojson_source._request_json", fail)

    with pytest.raises(type(error)):
        GeoJSONAdapter().fetch(source({"properties": {}}))


def test_geojson_adapter_rejects_missing_ids_and_invalid_geometries() -> None:
    adapter = GeoJSONAdapter()
    fixture = source({"id_property": "source_id", "properties": {}})

    with pytest.raises(ValueError, match="configured ID"):
        adapter.normalize(
            {"type": "Feature", "geometry": {"type": "Point"}, "properties": {}},
            fixture,
        )
    with pytest.raises(ValueError, match="invalid Feature"):
        adapter.normalize(
            {"type": "Feature", "geometry": None, "properties": {"source_id": "a"}},
            fixture,
        )


def test_geojson_adapter_applies_configured_timeout(monkeypatch) -> None:
    seen: dict[str, int] = {}

    def fake(_url: str, timeout: int):
        seen["timeout"] = timeout
        return {"type": "FeatureCollection", "features": []}

    monkeypatch.setattr("app.geojson_source._request_json", fake)

    GeoJSONAdapter().fetch(source({"properties": {}, "timeout_seconds": 60}))

    assert seen["timeout"] == 60


@pytest.mark.parametrize("timeout", [0, 121, "60", True, 1.5])
def test_geojson_adapter_rejects_out_of_range_timeout(timeout: object) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        GeoJSONAdapter().fetch(source({"properties": {}, "timeout_seconds": timeout}))
