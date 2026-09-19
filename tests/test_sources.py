import os
from email.message import Message
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from geoalchemy2 import WKTElement
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import ExternalSource, Feature, FeatureProvenance, Layer
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
                "TRUNCATE import_approvals, import_rows, imports, external_sources, "
                "feature_provenance, "
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

        monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
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

        monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
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


def test_external_sync_updates_archives_and_reactivates_without_duplicates(
    monkeypatch,
) -> None:
    adapter = FixtureAdapter(
        [
            {
                "id": "one",
                "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
                "properties": {"name": "Original"},
            },
            {
                "id": "two",
                "geometry": {"type": "Point", "coordinates": [-3.8, 40.5]},
                "properties": {"name": "To archive"},
            },
        ]
    )
    register_adapter("reconcile-fixture", adapter)
    try:
        with Session(engine) as session:
            layer = Layer(
                slug="external-reconcile",
                name="External reconcile",
                category="TEST",
                mode="external",
                geometry_types=["Point"],
                style={},
                metadata_={},
            )
            source = ExternalSource(
                layer=layer,
                slug="external-reconcile",
                adapter="reconcile-fixture",
                dataset_id="fixture-v1",
                status="never",
            )
            session.add(source)
            session.commit()
            source_id, layer_id = source.id, layer.id

        monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
        endpoint = f"/api/v1/admin/sources/{source_id}/sync"
        headers = {"Authorization": "Bearer test-token"}
        assert client.post(endpoint, headers=headers).json()["status"] == "success"
        with Session(engine) as session:
            original_ids = {
                feature.external_id: feature.id
                for feature in session.scalars(select(Feature)).all()
            }

        adapter.records = [
            {
                "id": "one",
                "geometry": {"type": "Point", "coordinates": [-3.6, 40.3]},
                "properties": {"name": "Updated"},
            },
            {
                "id": "three",
                "geometry": {"type": "Point", "coordinates": [-3.9, 40.6]},
                "properties": {"name": "New"},
            },
        ]
        assert client.post(endpoint, headers=headers).json()["status"] == "success"
        with Session(engine) as session:
            features = {
                feature.external_id: feature
                for feature in session.scalars(select(Feature)).all()
            }
            assert len(features) == 3
            assert features["one"].id == original_ids["one"]
            assert features["one"].properties["name"] == "Updated"
            assert features["two"].status == "archived"

        adapter.records.append(
            {
                "id": "two",
                "geometry": {"type": "Point", "coordinates": [-3.8, 40.5]},
                "properties": {"name": "Reappeared"},
            }
        )
        assert client.post(endpoint, headers=headers).json()["status"] == "success"
        with Session(engine) as session:
            features = {
                feature.external_id: feature
                for feature in session.scalars(select(Feature)).all()
            }
            assert len(features) == 3
            assert features["two"].id == original_ids["two"]
            assert features["two"].status == "published"
            assert features["two"].archived_at is None
            layer = session.get(Layer, layer_id)
            source = session.get(ExternalSource, source_id)
            assert layer is not None and source is not None
            layer.enabled = False
            session.commit()

        assert client.post(endpoint, headers=headers).json()["status"] == "success"
        with Session(engine) as session:
            source = session.get(ExternalSource, source_id)
            assert source is not None
            source.enabled = False
            session.commit()
        assert client.post(endpoint, headers=headers).status_code == 409
    finally:
        ADAPTERS.pop("reconcile-fixture", None)


def test_external_sync_only_updates_archives_and_reactivates_owned_features(
    monkeypatch,
) -> None:
    adapter = FixtureAdapter(
        [
            {
                "id": "owned-update",
                "geometry": {"type": "Point", "coordinates": [1, 1]},
                "properties": {"name": "Original"},
            },
            {
                "id": "owned-archive",
                "geometry": {"type": "Point", "coordinates": [2, 2]},
                "properties": {"name": "Archive me"},
            },
        ]
    )
    register_adapter("ownership-fixture", adapter)
    try:
        with Session(engine) as session:
            layer = Layer(
                slug="external-ownership",
                name="External ownership",
                category="TEST",
                mode="external",
                geometry_types=["Point"],
                style={},
                metadata_={},
            )
            source = ExternalSource(
                layer=layer,
                slug="external-ownership",
                adapter="ownership-fixture",
                dataset_id="fixture-v1",
                status="never",
            )
            session.add(source)
            session.commit()
            source_id, layer_id = source.id, layer.id

        monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
        headers = {"Authorization": "Bearer test-token"}
        endpoint = f"/api/v1/admin/sources/{source_id}/sync"
        assert client.post(endpoint, headers=headers).json()["status"] == "success"

        with Session(engine) as session:
            layer = session.get(Layer, layer_id)
            assert layer is not None
            manual = Feature(
                layer_id=layer_id,
                external_id="manual-keep",
                geometry=WKTElement("POINT(3 3)", srid=4326),
                properties={"owner": "manual"},
                status="published",
            )
            manual.provenance_records.append(
                FeatureProvenance(source_type="manual", created_by="admin")
            )
            imported = Feature(
                layer_id=layer_id,
                external_id="import-keep",
                geometry=WKTElement("POINT(4 4)", srid=4326),
                properties={"owner": "import"},
                status="published",
            )
            imported.provenance_records.append(
                FeatureProvenance(source_type="import", created_by="admin")
            )
            session.add_all([manual, imported])
            session.commit()

        adapter.records = [
            {
                "id": "owned-update",
                "geometry": {"type": "Point", "coordinates": [1.1, 1.1]},
                "properties": {"name": "Updated"},
            }
        ]
        assert client.post(endpoint, headers=headers).json()["status"] == "success"

        with Session(engine) as session:
            features = {
                feature.external_id: feature
                for feature in session.scalars(select(Feature)).all()
            }
            assert features["owned-update"].properties["name"] == "Updated"
            assert features["owned-archive"].status == "archived"
            assert features["manual-keep"].status == "published"
            assert features["import-keep"].status == "published"

        adapter.records.append(
            {
                "id": "owned-archive",
                "geometry": {"type": "Point", "coordinates": [2, 2]},
                "properties": {"name": "Reactivated"},
            }
        )
        assert client.post(endpoint, headers=headers).json()["status"] == "success"

        with Session(engine) as session:
            feature = session.scalar(
                select(Feature).where(Feature.external_id == "owned-archive")
            )
            assert feature is not None
            assert feature.status == "published"
            assert feature.archived_at is None
    finally:
        ADAPTERS.pop("ownership-fixture", None)


def test_hard_deleted_external_feature_is_recreated_by_next_sync(monkeypatch) -> None:
    adapter = FixtureAdapter(
        [
            {
                "id": "recreated",
                "geometry": {"type": "Point", "coordinates": [5, 5]},
                "properties": {"name": "Recreated"},
            }
        ]
    )
    register_adapter("recreate-fixture", adapter)
    try:
        with Session(engine) as session:
            layer = Layer(
                slug="external-recreate",
                name="External recreate",
                category="TEST",
                mode="external",
                geometry_types=["Point"],
                style={},
                metadata_={},
            )
            source = ExternalSource(
                layer=layer,
                slug="external-recreate",
                adapter="recreate-fixture",
                dataset_id="fixture-v1",
                status="never",
            )
            session.add(source)
            session.commit()
            source_id = source.id

        monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
        headers = {"Authorization": "Bearer test-token"}
        sync_endpoint = f"/api/v1/admin/sources/{source_id}/sync"
        assert client.post(sync_endpoint, headers=headers).json()["status"] == "success"

        with Session(engine) as session:
            feature = session.scalar(
                select(Feature).where(
                    Feature.layer_id == source.layer_id,
                    Feature.external_id == "recreated",
                )
            )
            assert feature is not None
            feature_id = feature.id

        deleted = client.post(
            f"/api/v1/admin/features/{feature_id}/hard-delete",
            headers=headers,
            json={"confirm_recreated_on_sync": True},
        )
        assert deleted.status_code == 200
        assert client.post(sync_endpoint, headers=headers).json()["status"] == "success"

        with Session(engine) as session:
            recreated = session.scalar(
                select(Feature).where(
                    Feature.layer_id == source.layer_id,
                    Feature.external_id == "recreated",
                )
            )
            assert recreated is not None
            assert recreated.status == "published"
    finally:
        ADAPTERS.pop("recreate-fixture", None)


@pytest.mark.parametrize(
    ("source_type", "source_name"),
    [("manual", None), ("import", None), ("external", "other-source")],
)
def test_external_sync_rejects_non_owned_external_id_collisions(
    monkeypatch, source_type: str, source_name: str | None
) -> None:
    adapter = FixtureAdapter(
        [
            {
                "id": "collision",
                "geometry": {"type": "Point", "coordinates": [9, 9]},
                "properties": {"name": "Incoming"},
            }
        ]
    )
    register_adapter("collision-fixture", adapter)
    try:
        with Session(engine) as session:
            layer = Layer(
                slug=f"collision-{source_type}",
                name="Collision",
                category="TEST",
                mode="external",
                geometry_types=["Point"],
                style={},
                metadata_={},
            )
            source = ExternalSource(
                layer=layer,
                slug=f"collision-{source_type}",
                adapter="collision-fixture",
                dataset_id="fixture-v1",
                status="never",
            )
            feature = Feature(
                layer=layer,
                external_id="collision",
                geometry=WKTElement("POINT(8 8)", srid=4326),
                properties={"name": "Protected"},
                status="published",
            )
            feature.provenance_records.append(
                FeatureProvenance(
                    source_type=source_type,
                    source_name=source_name,
                    created_by="test",
                )
            )
            session.add_all([source, feature])
            session.commit()
            source_id, feature_id = source.id, feature.id

        monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
        response = client.post(
            f"/api/v1/admin/sources/{source_id}/sync",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "failed"
        assert "not owned by this source" in response.json()["last_error"]

        with Session(engine) as session:
            feature = session.get(Feature, feature_id)
            assert feature is not None
            assert feature.properties == {"name": "Protected"}
            assert feature.status == "published"
    finally:
        ADAPTERS.pop("collision-fixture", None)


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
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
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


def test_external_sync_updates_geometry_only_change(monkeypatch) -> None:
    adapter = FixtureAdapter(
        [
            {
                "id": "station-1",
                "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
                "properties": {"name": "Same"},
            }
        ]
    )
    register_adapter("geometry-fixture", adapter)
    try:
        with Session(engine) as session:
            layer = Layer(
                slug="external-geometry",
                name="External geometry",
                category="TEST",
                mode="external",
                geometry_types=["Point"],
                style={},
                metadata_={},
            )
            source = ExternalSource(
                layer=layer,
                slug="external-geometry",
                adapter="geometry-fixture",
                dataset_id="fixture-v1",
                status="never",
            )
            session.add(source)
            session.commit()
            source_id, layer_id = source.id, layer.id

        monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
        endpoint = f"/api/v1/admin/sources/{source_id}/sync"
        headers = {"Authorization": "Bearer test-token"}
        assert client.post(endpoint, headers=headers).json()["status"] == "success"
        with Session(engine) as session:
            original = session.scalar(select(Feature))
            assert original is not None
            original_id = original.id

        adapter.records = [
            {
                "id": "station-1",
                "geometry": {"type": "Point", "coordinates": [-3.9, 40.6]},
                "properties": {"name": "Same"},
            }
        ]
        assert client.post(endpoint, headers=headers).json()["status"] == "success"
        with Session(engine) as session:
            feature = session.scalar(
                select(Feature).where(Feature.layer_id == layer_id)
            )
            assert feature is not None
            assert feature.id == original_id
            assert len(feature.provenance_records) == 2
        assert client.get("/api/v1/layers/external-geometry").json()["features"][0][
            "geometry"
        ]["coordinates"] == [-3.9, 40.6]
    finally:
        ADAPTERS.pop("geometry-fixture", None)


def test_external_sync_rejects_duplicate_ids_and_preserves_last_good(
    monkeypatch,
) -> None:
    adapter = FixtureAdapter(
        [
            {
                "id": "one",
                "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
                "properties": {"name": "Original"},
            }
        ]
    )
    register_adapter("duplicate-fixture", adapter)
    try:
        with Session(engine) as session:
            layer = Layer(
                slug="external-duplicate",
                name="External duplicate",
                category="TEST",
                mode="external",
                geometry_types=["Point"],
                style={},
                metadata_={},
            )
            source = ExternalSource(
                layer=layer,
                slug="external-duplicate",
                adapter="duplicate-fixture",
                dataset_id="fixture-v1",
                status="never",
            )
            session.add(source)
            session.commit()
            source_id, layer_id = source.id, layer.id

        monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")
        endpoint = f"/api/v1/admin/sources/{source_id}/sync"
        headers = {"Authorization": "Bearer test-token"}
        assert client.post(endpoint, headers=headers).json()["status"] == "success"

        adapter.records = [
            {
                "id": "one",
                "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
                "properties": {"name": "Original"},
            },
            {
                "id": "one",
                "geometry": {"type": "Point", "coordinates": [-3.8, 40.5]},
                "properties": {"name": "Duplicate"},
            },
        ]
        failed = client.post(endpoint, headers=headers).json()
        assert failed["status"] == "failed"
        assert "duplicate" in failed["last_error"]
        with Session(engine) as session:
            features = list(
                session.scalars(select(Feature).where(Feature.layer_id == layer_id))
            )
            assert len(features) == 1
            assert features[0].status == "published"
            assert features[0].properties["name"] == "Original"
            assert len(features[0].provenance_records) == 1
    finally:
        ADAPTERS.pop("duplicate-fixture", None)
