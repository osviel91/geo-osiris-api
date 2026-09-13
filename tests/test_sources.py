import os

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
