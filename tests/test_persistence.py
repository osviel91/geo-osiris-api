import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import Feature, FeatureProvenance, Layer

pytestmark = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="requires a PostGIS test database",
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_database():
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE feature_provenance, features, layers CASCADE")
        )
    yield
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE feature_provenance, features, layers CASCADE")
        )


def test_persisted_layer_serializes_to_public_and_compatibility_geojson() -> None:
    layer_id = uuid.uuid4()
    feature_id = uuid.uuid4()
    with Session(engine) as session:
        layer = Layer(
            id=layer_id,
            slug="test-persisted",
            name="Persisted Test Layer",
            description="Stored in PostGIS",
            category="TEST",
            mode="managed",
            geometry_types=["Point"],
            style={},
            metadata_={},
        )
        feature = Feature(
            id=feature_id,
            layer=layer,
            geometry=WKTElement("POINT(-3.7038 40.4168)", srid=4326),
            properties={"name": "Stored point"},
            status="published",
            verified_at=datetime.now(UTC),
        )
        feature.provenance_records.extend(
            [
                FeatureProvenance(
                    source_type="manual", created_by="test", metadata_={}
                ),
                FeatureProvenance(
                    source_type="import", created_by="test", metadata_={}
                ),
            ]
        )
        session.add(feature)
        session.commit()

    layers = client.get("/api/v1/layers")
    compatibility_layers = client.get("/layers")
    public = client.get("/api/v1/layers/test-persisted")
    compatibility = client.get("/layers/test-persisted")

    assert layers.status_code == 200
    assert layers.json()[0]["feature_count"] == 1
    assert (
        compatibility_layers.json()["layers"][1]["endpoint"] == "/layers/test-persisted"
    )
    assert public.status_code == 200
    assert public.json() == compatibility.json()
    assert public.json()["features"][0]["id"] == str(feature_id)
    assert public.json()["features"][0]["geometry"] == {
        "type": "Point",
        "coordinates": [-3.7038, 40.4168],
    }
    assert public.json()["features"][0]["properties"]["layer"] == "test-persisted"

    with Session(engine) as session:
        feature = session.get(Feature, feature_id)
        assert feature is not None
        assert len(feature.provenance_records) == 2
