import os
from email.message import Message
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import ExternalSource, Feature, Layer
from app.sources import ADAPTERS, NormalizedFeature, register_adapter

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="requires a PostGIS test database",
)

client = TestClient(app)


def test_aemet_json_accepts_latin1_without_a_charset(monkeypatch) -> None:
    import app.aemet as aemet

    class Response(BytesIO):
        headers = Message()

    monkeypatch.setattr(
        aemet,
        "urlopen",
        lambda *_args, **_kwargs: Response(b'{"nombre":"ALICANTE \xd3"}'),
    )

    assert aemet._request_json("https://offline.fixture") == {"nombre": "ALICANTE Ó"}


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


class FixtureAdapter:
    def __init__(self, records: list[dict]) -> None:
        self.records = records

    def fetch(self, source: ExternalSource) -> list[dict]:
        return self.records

    def normalize(self, record: dict, source: ExternalSource) -> NormalizedFeature:
        if "id" not in record:
            raise ValueError("Fixture record has no ID")
        return NormalizedFeature(
            external_id=record["id"],
            source_record_id=record["id"],
            geometry=record["geometry"],
            properties=record["properties"],
        )


def test_external_source_sync_is_idempotent_and_preserves_last_good_data(
    monkeypatch,
) -> None:
    adapter = FixtureAdapter(
        [
            {
                "id": "station-1",
                "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
                "properties": {"name": "Original"},
            }
        ]
    )
    register_adapter("fixture", adapter)
    try:
        with Session(engine) as session:
            layer = Layer(
                slug="external-fixture",
                name="External fixture",
                category="TEST",
                mode="external",
                geometry_types=["Point"],
                style={},
                metadata_={},
            )
            source = ExternalSource(
                layer=layer,
                slug="external-fixture",
                adapter="fixture",
                dataset_id="fixture-v1",
                status="never",
            )
            session.add(source)
            session.commit()
            source_id = source.id

        monkeypatch.setenv("ADMIN_API_TOKEN", "test-token")
        headers = {"Authorization": "Bearer test-token"}
        assert client.post(f"/api/v1/admin/sources/{source_id}/sync").status_code == 401
        first = client.post(f"/api/v1/admin/sources/{source_id}/sync", headers=headers)
        assert first.json()["status"] == "success"
        assert (
            client.get("/api/v1/layers/external-fixture").json()["features"][0][
                "properties"
            ]["name"]
            == "Original"
        )

        assert (
            client.post(
                f"/api/v1/admin/sources/{source_id}/sync", headers=headers
            ).json()["status"]
            == "success"
        )
        with Session(engine) as session:
            feature = session.scalar(select(Feature))
            assert feature is not None
            assert len(feature.provenance_records) == 1

        adapter.records = [{"geometry": {"type": "Point", "coordinates": [1, 1]}}]
        failed = client.post(
            f"/api/v1/admin/sources/{source_id}/sync", headers=headers
        ).json()
        assert failed["status"] == "failed"
        assert failed["last_success_at"] is not None
        assert failed["last_error"]
        assert (
            client.get("/api/v1/layers/external-fixture").json()["features"][0][
                "properties"
            ]["name"]
            == "Original"
        )
    finally:
        ADAPTERS.pop("fixture", None)


def test_external_sync_updates_layer_revision(monkeypatch) -> None:
    adapter = FixtureAdapter(
        [
            {
                "id": "station-1",
                "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
                "properties": {"name": "Original"},
            }
        ]
    )
    register_adapter("freshness-fixture", adapter)
    try:
        with Session(engine) as session:
            layer = Layer(
                slug="external-freshness",
                name="External freshness",
                category="TEST",
                mode="external",
                geometry_types=["Point"],
                style={},
                metadata_={},
            )
            source = ExternalSource(
                layer=layer,
                slug="external-freshness",
                adapter="freshness-fixture",
                dataset_id="fixture-v1",
                status="never",
            )
            session.add(source)
            session.commit()
            source_id, layer_id = source.id, layer.id

        monkeypatch.setenv("ADMIN_API_TOKEN", "test-token")
        headers = {"Authorization": "Bearer test-token"}
        endpoint = f"/api/v1/admin/sources/{source_id}/sync"

        def revision() -> int:
            with Session(engine) as session:
                persisted = session.get(Layer, layer_id)
                assert persisted is not None
                return persisted.revision

        assert client.post(endpoint, headers=headers).json()["status"] == "success"
        assert revision() == 1
        assert client.post(endpoint, headers=headers).json()["status"] == "success"
        assert revision() == 1

        adapter.records = [
            {
                "id": "station-1",
                "geometry": {"type": "Point", "coordinates": [-3.8, 40.5]},
                "properties": {"name": "Updated"},
            }
        ]
        assert client.post(endpoint, headers=headers).json()["status"] == "success"
        assert revision() == 2

        adapter.records = []
        assert client.post(endpoint, headers=headers).json()["status"] == "success"
        assert revision() == 3
    finally:
        ADAPTERS.pop("freshness-fixture", None)


def test_aemet_station_sync_uses_offline_provider_data_and_preserves_last_good(
    monkeypatch,
) -> None:
    import app.aemet as aemet

    station = {
        "indicativo": "3195",
        "nombre": "ZARAGOZA",
        "provincia": "ZARAGOZA",
        "altitud": "263",
        "latitud": "412842N",
        "longitud": "0013733W",
        "fnac": "1940-01-01",
        "fint": "2024-03-01T12:00:00Z",
    }
    records = [station]

    def request_json(url: str):
        if "inventarioestaciones" in url:
            assert "api_key=offline-key" in url
            return {"datos": "https://offline.fixture/aemet-stations"}
        return records

    monkeypatch.setenv("AEMET_API_KEY", "offline-key")
    monkeypatch.setattr(aemet, "_request_json", request_json)
    monkeypatch.setenv("ADMIN_API_TOKEN", "test-token")
    with Session(engine) as session:
        layer = Layer(
            slug="aemet-fixture",
            name="AEMET fixture",
            category="WEATHER_INFRASTRUCTURE",
            mode="external",
            geometry_types=["Point"],
            style={},
            metadata_={},
        )
        source = ExternalSource(
            layer=layer,
            slug="aemet-fixture",
            adapter="aemet_stations",
            dataset_id="aemet-opendata-station-inventory",
            endpoint=aemet.DEFAULT_ENDPOINT,
            status="never",
        )
        session.add(source)
        session.commit()
        source_id, layer_id = source.id, layer.id

    headers = {"Authorization": "Bearer test-token"}
    endpoint = f"/api/v1/admin/sources/{source_id}/sync"
    first = client.post(endpoint, headers=headers)
    assert first.json()["status"] == "success"
    assert first.json()["last_success_at"] is not None
    public = client.get("/api/v1/layers/aemet-fixture").json()
    assert public["features"][0]["properties"]["station_type"] == (
        "weather_observation_station"
    )
    assert public["features"][0]["geometry"]["coordinates"] == pytest.approx(
        [-1.6258333333333332, 41.47833333333333]
    )

    assert client.post(endpoint, headers=headers).json()["status"] == "success"
    with Session(engine) as session:
        feature = session.scalar(select(Feature).where(Feature.layer_id == layer_id))
        assert feature is not None
        assert len(feature.provenance_records) == 1
        provenance = feature.provenance_records[0]
        assert provenance.source_record_id == "3195"
        assert provenance.observed_at is not None
        assert provenance.imported_at is not None
        assert provenance.metadata_["dataset_id"] == "aemet-opendata-station-inventory"
        assert (
            provenance.metadata_["source_timestamps"]["fint"] == "2024-03-01T12:00:00Z"
        )

    records = [{**station, "nombre": "ZARAGOZA UPDATED", "longitud": "0014000W"}]
    changed = client.post(endpoint, headers=headers)
    assert changed.json()["status"] == "success"
    assert (
        client.get("/api/v1/layers/aemet-fixture").json()["features"][0]["properties"][
            "name"
        ]
        == "ZARAGOZA UPDATED"
    )
    with Session(engine) as session:
        feature = session.scalar(select(Feature).where(Feature.layer_id == layer_id))
        assert feature is not None
        assert len(feature.provenance_records) == 2

    records = []
    assert client.post(endpoint, headers=headers).json()["status"] == "success"
    assert client.get("/api/v1/layers/aemet-fixture").json()["features"] == []

    records = [station]
    assert client.post(endpoint, headers=headers).json()["status"] == "success"
    records = [{"indicativo": "3195", "nombre": "Malformed"}]
    malformed = client.post(endpoint, headers=headers).json()
    assert malformed["status"] == "failed"
    assert (
        client.get("/api/v1/layers/aemet-fixture").json()["features"][0]["properties"][
            "name"
        ]
        == "ZARAGOZA"
    )

    def timeout(_: str):
        raise TimeoutError("offline timeout")

    monkeypatch.setattr(aemet, "_request_json", timeout)
    timed_out = client.post(endpoint, headers=headers).json()
    assert timed_out["status"] == "failed"
    assert "offline timeout" in timed_out["last_error"]
    assert (
        client.get("/api/v1/layers/aemet-fixture").json()["features"][0]["properties"][
            "name"
        ]
        == "ZARAGOZA"
    )
