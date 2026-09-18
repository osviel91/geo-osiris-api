import os
import uuid

import pytest
from fastapi.testclient import TestClient
from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine
from app.main import app
from app.models import Feature

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
                "TRUNCATE import_approvals, import_rows, imports, external_sources, "
                "feature_provenance, features, layers CASCADE"
            )
        )
    yield


@pytest.fixture(autouse=True)
def admin_token(monkeypatch):
    monkeypatch.setenv("GEO_ADMIN_TOKEN", "test-token")


def create_layer(slug: str, geometry_types: list[str]) -> str:
    response = client.post(
        "/api/v1/admin/layers",
        headers=HEADERS,
        json={
            "slug": slug,
            "name": slug,
            "category": "TEST",
            "mode": "managed",
            "geometry_types": geometry_types,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def insert_feature(layer_id: str, wkt: str, properties: dict | None = None) -> str:
    with Session(engine) as session:
        feature = Feature(
            layer_id=uuid.UUID(layer_id),
            geometry=WKTElement(wkt, srid=4326),
            properties=properties or {},
            status="published",
        )
        session.add(feature)
        session.commit()
        return str(feature.id)


def _square_ring(offset: float = 0.0, points_per_edge: int = 50) -> list[tuple]:
    ring = [(offset, 0.0)]
    for i in range(1, points_per_edge + 1):
        ring.append((offset + i / points_per_edge, 0.0))
    for i in range(1, points_per_edge + 1):
        ring.append((offset + 1.0, i / points_per_edge))
    for i in range(1, points_per_edge + 1):
        ring.append((offset + 1.0 - i / points_per_edge, 1.0))
    for i in range(1, points_per_edge + 1):
        ring.append((offset, 1.0 - i / points_per_edge))
    return ring


def _ring_wkt(ring: list[tuple]) -> str:
    return ", ".join(f"{x} {y}" for x, y in ring)


def polygon_wkt(offset: float = 0.0) -> str:
    return f"POLYGON(({_ring_wkt(_square_ring(offset))}))"


def multipolygon_wkt() -> str:
    first = _ring_wkt(_square_ring(0.0))
    second = _ring_wkt(_square_ring(2.0))
    return f"MULTIPOLYGON((({first})), (({second})))"


def stored_geometry(feature_id: str) -> tuple[int, str]:
    with Session(engine) as session:
        return session.execute(
            text(
                "SELECT ST_NPoints(geometry), ST_AsText(geometry) FROM features "
                "WHERE id = :id"
            ),
            {"id": feature_id},
        ).one()


def test_precision_bounds() -> None:
    layer_id = create_layer("precision", ["Point"])
    insert_feature(layer_id, "POINT(1.123456789 40.987654321)")

    for good in ("0", "9"):
        assert (
            client.get(
                f"/api/v1/layers/precision/features?precision={good}"
            ).status_code
            == 200
        )
    for bad in ("-1", "10", "abc", "1.5"):
        response = client.get(f"/api/v1/layers/precision/features?precision={bad}")
        assert response.status_code == 422, bad


def test_precision_controls_returned_coordinates() -> None:
    layer_id = create_layer("precision-coords", ["Point"])
    insert_feature(layer_id, "POINT(1.123456789 40.987654321)")

    default = client.get("/api/v1/layers/precision-coords/features").json()
    assert default["features"][0]["geometry"]["coordinates"] == pytest.approx(
        [1.123456789, 40.987654321]
    )

    coarse = client.get("/api/v1/layers/precision-coords/features?precision=2").json()
    assert coarse["features"][0]["geometry"]["coordinates"] == pytest.approx(
        [1.12, 40.99]
    )


def test_simplify_bounds_and_nan() -> None:
    layer_id = create_layer("simplify", ["Polygon"])
    insert_feature(layer_id, polygon_wkt())

    for good in ("0", "0.001"):
        assert (
            client.get(f"/api/v1/layers/simplify/features?simplify={good}").status_code
            == 200
        )
    for bad in ("-0.1", "2", "abc", "nan", "inf", "-inf"):
        response = client.get(f"/api/v1/layers/simplify/features?simplify={bad}")
        assert response.status_code == 422, bad


def test_simplify_reduces_geometry_without_touching_storage() -> None:
    layer_id = create_layer("simplify-effect", ["Polygon"])
    feature_id = insert_feature(layer_id, polygon_wkt())
    before = stored_geometry(feature_id)

    page = client.get(
        "/api/v1/layers/simplify-effect/features?simplify=0.001&precision=6"
    ).json()
    returned = page["features"][0]["geometry"]["coordinates"][0]
    assert len(returned) < 20

    assert stored_geometry(feature_id) == before


def test_geometry_types_and_simplify_noop_for_points() -> None:
    layer_id = create_layer("mixed", ["Point", "Polygon", "MultiPolygon"])
    insert_feature(layer_id, "POINT(1.5 40.5)")
    insert_feature(layer_id, polygon_wkt())
    insert_feature(layer_id, multipolygon_wkt())

    page = client.get("/api/v1/layers/mixed/features?simplify=0.001&precision=6").json()
    by_type = {feature["geometry"]["type"]: feature for feature in page["features"]}
    assert set(by_type) == {"Point", "Polygon", "MultiPolygon"}
    assert by_type["Point"]["geometry"]["coordinates"] == pytest.approx([1.5, 40.5])
    assert len(by_type["Polygon"]["geometry"]["coordinates"][0]) < 20
    assert len(by_type["MultiPolygon"]["geometry"]["coordinates"]) == 2


def test_bbox_presentation_and_pagination_combined() -> None:
    layer_id = create_layer("combo", ["Polygon"])
    ids = [insert_feature(layer_id, polygon_wkt(offset)) for offset in (0.0, 2.0, 4.0)]

    first = client.get(
        "/api/v1/layers/combo/features"
        "?bbox=-0.5,-0.5,10.5,1.5&limit=2&simplify=0.001&precision=6"
    ).json()
    assert len(first["features"]) == 2
    assert first["next_cursor"]

    rest = client.get(
        "/api/v1/layers/combo/features"
        f"?bbox=-0.5,-0.5,10.5,1.5&limit=2&cursor={first['next_cursor']}"
        "&simplify=0.001&precision=6"
    ).json()
    assert len(rest["features"]) == 1
    assert rest["next_cursor"] is None
    assert {f["id"] for f in first["features"] + rest["features"]} == set(ids)


def test_updated_since_works_with_presentation_params() -> None:
    layer_id = create_layer("freshness", ["Polygon"])
    insert_feature(layer_id, polygon_wkt())

    response = client.get(
        "/api/v1/layers/freshness/features",
        params={
            "updated_since": "2999-01-01T00:00:00Z",
            "simplify": 0.001,
            "precision": 6,
        },
    )
    assert response.status_code == 200
    assert response.json()["features"] == []


def test_gzip_negotiation() -> None:
    layer_id = create_layer("gzip", ["Polygon"])
    insert_feature(layer_id, polygon_wkt())

    compressed = client.get(
        "/api/v1/layers/gzip/features", headers={"Accept-Encoding": "gzip"}
    )
    assert compressed.status_code == 200
    assert compressed.headers.get("content-encoding") == "gzip"
    assert len(compressed.json()["features"]) == 1

    identity = client.get(
        "/api/v1/layers/gzip/features", headers={"Accept-Encoding": "identity"}
    )
    assert identity.headers.get("content-encoding") is None

    small = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert small.headers.get("content-encoding") is None
