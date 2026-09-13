import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import ExternalSource, Feature, Layer

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


def create_layer(slug: str, mode: str = "managed", **overrides) -> dict:
    payload = {
        "slug": slug,
        "name": slug,
        "category": "TEST",
        "mode": mode,
        "geometry_types": ["Point"],
        **overrides,
    }
    response = client.post("/api/v1/admin/layers", headers=HEADERS, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def create_feature(layer_id: str, lon: float, lat: float, **overrides) -> dict:
    payload = {
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": overrides.pop("properties", {}),
        "status": overrides.pop("status", "published"),
        **overrides,
    }
    response = client.post(
        f"/api/v1/admin/layers/{layer_id}/features", headers=HEADERS, json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_admin_layers_paginate_by_slug_with_opaque_cursor() -> None:
    for slug in ("alpha", "bravo", "charlie"):
        create_layer(slug)

    first = client.get("/api/v1/admin/layers?limit=2", headers=HEADERS).json()
    assert [item["slug"] for item in first["items"]] == ["alpha", "bravo"]
    assert first["next_cursor"]

    second = client.get(
        f"/api/v1/admin/layers?limit=2&cursor={first['next_cursor']}",
        headers=HEADERS,
    ).json()
    assert [item["slug"] for item in second["items"]] == ["charlie"]
    assert second["next_cursor"] is None

    assert client.get("/api/v1/admin/layers", headers=HEADERS).json()["items"]
    assert (
        client.get(
            "/api/v1/admin/layers?cursor=not-base64!!", headers=HEADERS
        ).status_code
        == 422
    )
    assert (
        client.get("/api/v1/admin/layers?limit=0", headers=HEADERS).status_code == 422
    )


def test_admin_features_paginate_and_report_provenance() -> None:
    layer = create_layer("feature-page")
    created = [
        create_feature(layer["id"], 1.0 + index / 100, 40.0, properties={"n": index})
        for index in range(3)
    ]

    page = client.get(
        f"/api/v1/admin/layers/{layer['id']}/features?limit=2", headers=HEADERS
    ).json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]

    rest = client.get(
        f"/api/v1/admin/layers/{layer['id']}/features"
        f"?limit=2&cursor={page['next_cursor']}",
        headers=HEADERS,
    ).json()
    assert len(rest["items"]) == 1
    assert rest["next_cursor"] is None

    seen = {item["id"] for item in page["items"]} | {
        item["id"] for item in rest["items"]
    }
    assert seen == {item["id"] for item in created}

    detail = client.get(
        f"/api/v1/admin/features/{created[0]['id']}", headers=HEADERS
    ).json()
    assert detail["geometry"] == {"type": "Point", "coordinates": [1.0, 40.0]}
    assert len(detail["provenance"]) == 1
    assert detail["provenance"][0]["source_type"] == "manual"
    assert detail["provenance"][0]["created_by"] == "admin"


def test_admin_import_rows_paginate_and_filter_by_state() -> None:
    layer = create_layer("import-page")
    staged = client.post(
        "/api/v1/admin/imports",
        headers=HEADERS,
        json={
            "layer_id": layer["id"],
            "filename": "mixed.csv",
            "format": "csv",
            "content": (
                "longitude,latitude,callsign\n-3.7,40.4,VALID-1\n200,40.4,BAD-1\n"
            ),
        },
    ).json()

    invalid = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows?state=invalid", headers=HEADERS
    ).json()
    assert [row["row_number"] for row in invalid["items"]] == [2]
    assert invalid["items"][0]["validation_error"]

    valid = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows?state=valid", headers=HEADERS
    ).json()
    assert [row["row_number"] for row in valid["items"]] == [1]

    first = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows?limit=1", headers=HEADERS
    ).json()
    assert [row["row_number"] for row in first["items"]] == [1]
    assert first["next_cursor"]
    second = client.get(
        f"/api/v1/admin/imports/{staged['id']}/rows?limit=1"
        f"&cursor={first['next_cursor']}",
        headers=HEADERS,
    ).json()
    assert [row["row_number"] for row in second["items"]] == [2]

    summary = client.get(
        f"/api/v1/admin/imports/{staged['id']}", headers=HEADERS
    ).json()
    assert "rows" not in summary
    assert summary["valid_count"] == 1
    assert summary["invalid_count"] == 1


def test_admin_imports_paginate_newest_first() -> None:
    layer = create_layer("import-list")
    for index in range(3):
        client.post(
            "/api/v1/admin/imports",
            headers=HEADERS,
            json={
                "layer_id": layer["id"],
                "filename": f"{index}.csv",
                "format": "csv",
                "content": f"longitude,latitude\n{index}.0,40.0\n",
            },
        )

    first = client.get(
        f"/api/v1/admin/imports?layer_id={layer['id']}&limit=2", headers=HEADERS
    ).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"]
    second = client.get(
        f"/api/v1/admin/imports?layer_id={layer['id']}&limit=2"
        f"&cursor={first['next_cursor']}",
        headers=HEADERS,
    ).json()
    assert len(second["items"]) == 1
    ids = [item["id"] for item in first["items"] + second["items"]]
    assert len(set(ids)) == 3


def test_admin_sources_list_and_detail() -> None:
    with Session(engine) as session:
        layer = Layer(
            slug="source-layer",
            name="Source layer",
            category="TEST",
            mode="external",
            geometry_types=["Point"],
            style={},
            metadata_={},
        )
        session.add(
            ExternalSource(
                layer=layer,
                slug="source-layer",
                adapter="fixture",
                dataset_id="fixture-v1",
                status="never",
            )
        )
        session.commit()
        source_id = layer.external_sources[0].id

    listing = client.get("/api/v1/admin/sources", headers=HEADERS).json()
    assert [item["slug"] for item in listing["items"]] == ["source-layer"]
    detail = client.get(f"/api/v1/admin/sources/{source_id}", headers=HEADERS).json()
    assert detail["adapter"] == "fixture"
    assert detail["enabled"] is True


def test_public_features_paginate_bbox_and_updated_since() -> None:
    layer = create_layer("public-page")
    for index in range(3):
        create_feature(layer["id"], 1.0 + index, 40.0, properties={"n": index})

    page = client.get("/api/v1/layers/public-page/features?limit=2").json()
    assert len(page["features"]) == 2
    assert page["next_cursor"]
    rest = client.get(
        f"/api/v1/layers/public-page/features?limit=2&cursor={page['next_cursor']}"
    ).json()
    assert len(rest["features"]) == 1
    assert rest["next_cursor"] is None

    bbox = client.get(
        "/api/v1/layers/public-page/features?bbox=1.5,39.0,2.5,41.0"
    ).json()
    assert [feature["properties"]["n"] for feature in bbox["features"]] == [1]

    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    empty = client.get(
        "/api/v1/layers/public-page/features", params={"updated_since": future}
    ).json()
    assert empty["features"] == []

    assert client.get("/api/v1/layers/public-page/features?bbox=bad").status_code == 422

    compatibility = client.get("/layers/public-page").json()
    assert len(compatibility["features"]) == 3
    assert "next_cursor" not in compatibility


def test_external_layers_reject_managed_writes() -> None:
    layer = create_layer("external-owner", mode="external")
    with Session(engine) as session:
        feature = Feature(
            layer_id=uuid.UUID(layer["id"]),
            external_id="ext-1",
            geometry=WKTElement("POINT(1 1)", srid=4326),
            properties={},
            status="published",
        )
        session.add(feature)
        session.commit()
        feature_id = feature.id

    create = client.post(
        f"/api/v1/admin/layers/{layer['id']}/features",
        headers=HEADERS,
        json={
            "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
            "properties": {},
            "status": "published",
        },
    )
    assert create.status_code == 404

    update = client.patch(
        f"/api/v1/admin/features/{feature_id}",
        headers=HEADERS,
        json={
            "geometry": {"type": "Point", "coordinates": [2.0, 2.0]},
            "properties": {},
            "status": "published",
        },
    )
    assert update.status_code == 404

    archive = client.delete(f"/api/v1/admin/features/{feature_id}", headers=HEADERS)
    assert archive.status_code == 404

    staged = client.post(
        "/api/v1/admin/imports",
        headers=HEADERS,
        json={
            "layer_id": layer["id"],
            "filename": "external.csv",
            "format": "csv",
            "content": "longitude,latitude\n1.0,1.0\n",
        },
    )
    assert staged.status_code == 404
