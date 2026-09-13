import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Feature, Layer
from app.pagination import clamp_limit, decode_cursor, encode_cursor
from app.schemas import (
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    GeoJSONFeatureCollectionPage,
    LayerSummary,
)


def list_layers(session: Session) -> list[LayerSummary]:
    statement = (
        select(Layer, func.count(Feature.id))
        .outerjoin(
            Feature, (Feature.layer_id == Layer.id) & (Feature.status == "published")
        )
        .where(Layer.enabled.is_(True))
        .group_by(Layer.id)
        .order_by(Layer.slug)
    )
    return [
        LayerSummary(
            id=str(layer.id),
            slug=layer.slug,
            name=layer.name,
            category=layer.category,
            mode=layer.mode,
            geometry_types=layer.geometry_types,
            enabled=layer.enabled,
            feature_count=count,
            revision=layer.revision,
            data_updated_at=layer.data_updated_at,
            updated_at=layer.updated_at,
        )
        for layer, count in session.execute(statement)
    ]


def list_compatibility_layers(session: Session) -> list[Layer]:
    return list(
        session.scalars(
            select(Layer).where(Layer.enabled.is_(True)).order_by(Layer.slug)
        )
    )


def get_layer_geojson(session: Session, slug: str) -> GeoJSONFeatureCollection:
    layer = session.scalar(
        select(Layer).where(Layer.slug == slug, Layer.enabled.is_(True))
    )
    if layer is None:
        raise HTTPException(status_code=404, detail="Layer not found")

    statement = (
        select(
            Feature.id,
            Feature.properties,
            Feature.status,
            Feature.updated_at,
            func.ST_AsGeoJSON(Feature.geometry).label("geometry_json"),
        )
        .where(
            Feature.layer_id == layer.id,
            Feature.status == "published",
            Feature.archived_at.is_(None),
        )
        .order_by(Feature.id)
    )
    features = [
        serialize_feature(layer, row) for row in session.execute(statement).mappings()
    ]
    return GeoJSONFeatureCollection(features=features)


def get_layer_features_page(
    session: Session,
    slug: str,
    limit: int,
    cursor: str | None,
    bbox: str | None,
    updated_since: datetime | None,
) -> GeoJSONFeatureCollectionPage:
    layer = session.scalar(
        select(Layer).where(Layer.slug == slug, Layer.enabled.is_(True))
    )
    if layer is None:
        raise HTTPException(status_code=404, detail="Layer not found")

    limit = clamp_limit(limit)
    after = decode_cursor(cursor, {"id"})["id"] if cursor else None
    statement = select(
        Feature.id,
        Feature.properties,
        Feature.status,
        Feature.updated_at,
        func.ST_AsGeoJSON(Feature.geometry).label("geometry_json"),
    ).where(
        Feature.layer_id == layer.id,
        Feature.status == "published",
        Feature.archived_at.is_(None),
    )
    if after is not None:
        statement = statement.where(Feature.id > _feature_uuid(after))
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = _parse_bbox(bbox)
        statement = statement.where(
            func.ST_Intersects(
                Feature.geometry,
                func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326),
            )
        )
    if updated_since is not None:
        statement = statement.where(Feature.updated_at >= updated_since)
    statement = statement.order_by(Feature.id).limit(limit + 1)

    rows = list(session.execute(statement).mappings())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor({"id": str(rows[-1]["id"])})
    return GeoJSONFeatureCollectionPage(
        features=[serialize_feature(layer, row) for row in rows],
        next_cursor=next_cursor,
    )


def _feature_uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Invalid cursor") from error


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(
            status_code=422, detail="bbox must be minLon,minLat,maxLon,maxLat"
        )
    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail="bbox values must be numbers"
        ) from error
    if not (
        -180 <= min_lon <= 180
        and -180 <= max_lon <= 180
        and -90 <= min_lat <= 90
        and -90 <= max_lat <= 90
    ):
        raise HTTPException(status_code=422, detail="bbox is outside WGS84 bounds")
    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(status_code=422, detail="bbox is inverted")
    return min_lon, min_lat, max_lon, max_lat


def serialize_feature(layer: Layer, row: dict[str, Any]) -> GeoJSONFeature:
    properties = {
        **row["properties"],
        "id": str(row["id"]),
        "layer": layer.slug,
        "category": layer.category,
        "status": row["status"],
        "updated_at": row["updated_at"].isoformat(),
    }
    return GeoJSONFeature(
        id=str(row["id"]),
        geometry=json.loads(row["geometry_json"]),
        properties=properties,
    )
