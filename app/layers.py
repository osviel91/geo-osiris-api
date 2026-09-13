import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Feature, Layer
from app.schemas import GeoJSONFeature, GeoJSONFeatureCollection, LayerSummary


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
