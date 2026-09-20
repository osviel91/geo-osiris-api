import uuid
from json import JSONDecodeError
from urllib.error import HTTPError

import pytest

from app.agent_sources import canonical_proposal, preflight
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


def feature(record_id: str) -> dict:
    return {
        "type": "Feature",
        "id": record_id,
        "geometry": {"type": "Point", "coordinates": [1, 2]},
        "properties": {},
    }


def pagination() -> dict:
    return {
        "type": "offset",
        "limit_param": "count",
        "offset_param": "startIndex",
        "page_size": 2,
        "max_pages": 5,
    }


def test_geojson_adapter_collects_pages_and_stops_on_short_page(monkeypatch) -> None:
    calls: list[str] = []
    pages = {
        0: [feature("one"), feature("two")],
        2: [feature("three")],
    }

    def request(url: str, _timeout: int):
        calls.append(url)
        offset = int(url.split("startIndex=")[1])
        return {"type": "FeatureCollection", "features": pages[offset]}

    monkeypatch.setattr("app.geojson_source._request_json", request)
    records = GeoJSONAdapter().fetch(
        source({"properties": {}, "pagination": pagination()})
    )

    assert [record["id"] for record in records] == ["one", "two", "three"]
    assert len(calls) == 2
    assert all("count=2" in call for call in calls)


def test_geojson_adapter_accepts_empty_final_page(monkeypatch) -> None:
    def request(url: str, _timeout: int):
        offset = int(url.split("startIndex=")[1])
        return {
            "type": "FeatureCollection",
            "features": [feature("one"), feature("two")] if offset == 0 else [],
        }

    monkeypatch.setattr("app.geojson_source._request_json", request)
    records = GeoJSONAdapter().fetch(
        source({"properties": {}, "pagination": pagination()})
    )
    assert len(records) == 2


def test_geojson_adapter_rejects_duplicate_ids_across_pages(monkeypatch) -> None:
    def request(url: str, _timeout: int):
        offset = int(url.split("startIndex=")[1])
        return {
            "type": "FeatureCollection",
            "features": [feature("one"), feature("two")]
            if offset == 0
            else [feature("two")],
        }

    monkeypatch.setattr("app.geojson_source._request_json", request)
    with pytest.raises(ValueError, match="duplicate"):
        GeoJSONAdapter().fetch(
            source(
                {
                    "id_property": None,
                    "properties": {},
                    "pagination": pagination(),
                }
            )
        )


def test_geojson_adapter_fails_when_max_pages_are_all_full(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.geojson_source._request_json",
        lambda *_args: {
            "type": "FeatureCollection",
            "features": [feature("one"), feature("two")],
        },
    )
    with pytest.raises(ValueError, match="pagination limit"):
        GeoJSONAdapter().fetch(
            source(
                {
                    "properties": {},
                    "pagination": {**pagination(), "max_pages": 2},
                }
            )
        )


def test_geojson_adapter_propagates_later_page_size_failure(monkeypatch) -> None:
    def request(url: str, _timeout: int):
        if "startIndex=0" in url:
            return {
                "type": "FeatureCollection",
                "features": [feature("one"), feature("two")],
            }
        raise ValueError("GeoJSON response exceeds 64 MiB")

    monkeypatch.setattr("app.geojson_source._request_json", request)
    with pytest.raises(ValueError, match="64 MiB"):
        GeoJSONAdapter().fetch(
            source({"properties": {}, "pagination": pagination()})
        )


@pytest.mark.parametrize(
    "bad_pagination",
    [
        {"type": "cursor"},
        {
            "type": "offset",
            "limit_param": "1bad",
            "offset_param": "startIndex",
            "page_size": 2,
            "max_pages": 5,
        },
        {
            "type": "offset",
            "limit_param": "count",
            "offset_param": "count",
            "page_size": 2,
            "max_pages": 5,
        },
        {
            "type": "offset",
            "limit_param": "count",
            "offset_param": "startIndex",
            "page_size": 0,
            "max_pages": 5,
        },
        {
            "type": "offset",
            "limit_param": "count",
            "offset_param": "startIndex",
            "page_size": 2,
            "max_pages": 101,
        },
    ],
)
def test_geojson_adapter_rejects_unbounded_or_unsafe_pagination(bad_pagination) -> None:
    with pytest.raises(ValueError, match="pagination"):
        GeoJSONAdapter().fetch(source({"properties": {}, "pagination": bad_pagination}))


def test_pagination_is_part_of_agent_fingerprint(monkeypatch) -> None:
    proposal = {
        "endpoint": "https://data.example.test/features.geojson",
        "slug": "public-fixture",
        "name": "Public fixture",
        "category": "TEST",
        "geometry_types": ["Point"],
        "dataset_id": "fixture-v1",
        "properties": {},
        "pagination": pagination(),
    }
    monkeypatch.setattr(
        "app.agent_sources._validate_url",
        lambda _: ("data.example.test", ["203.0.113.1"]),
    )
    monkeypatch.setattr(
        "app.agent_sources.fetch_dataset",
        lambda *_args: (
            {"type": "FeatureCollection", "features": [feature("one")]},
            {"hostname": "data.example.test", "addresses": ["203.0.113.1"], "bytes": 1},
        ),
    )
    first = preflight(proposal)
    changed = {**proposal, "pagination": {**pagination(), "page_size": 3}}
    second = preflight(changed)
    assert first.fingerprint != second.fingerprint
    assert canonical_proposal(changed)["pagination"]["page_size"] == 3


@pytest.mark.parametrize("timeout", [0, 121, "60", True, 1.5])
def test_geojson_adapter_rejects_out_of_range_timeout(timeout: object) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        GeoJSONAdapter().fetch(source({"properties": {}, "timeout_seconds": timeout}))
