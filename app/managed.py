import json
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.geometry import validate_geometry, validate_properties
from app.models import Feature, FeatureProvenance, Layer
from app.schemas import FeatureWrite, LayerCreate, LayerUpdate


def create_layer(session: Session, payload: LayerCreate) -> Layer:
    layer = Layer(**payload.model_dump())
    session.add(layer)
    session.commit()
    session.refresh(layer)
    return layer


def update_layer(session: Session, layer_id: uuid.UUID, payload: LayerUpdate) -> Layer:
    layer = session.get(Layer, layer_id)
    if layer is None:
        raise HTTPException(status_code=404, detail="Layer not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(layer, field, value)
    session.commit()
    session.refresh(layer)
    return layer


def create_feature(
    session: Session, layer_id: uuid.UUID, payload: FeatureWrite
) -> Feature:
    layer = _managed_layer(session, layer_id)
    validate_geometry(payload.geometry, layer.geometry_types)
    validate_properties(payload.properties)
    feature = Feature(
        layer=layer,
        external_id=payload.external_id,
        geometry=func.ST_SetSRID(
            func.ST_GeomFromGeoJSON(json.dumps(payload.geometry)), 4326
        ),
        properties=payload.properties,
        status=payload.status,
        verified_at=payload.verified_at,
    )
    feature.provenance_records.append(
        FeatureProvenance(
            source_type=payload.source_type,
            source_name=payload.source_name,
            source_url=payload.source_url,
            source_record_id=payload.source_record_id,
            created_by="admin",
            metadata_={},
        )
    )
    session.add(feature)
    session.commit()
    session.refresh(feature)
    return feature


def update_feature(
    session: Session, feature_id: uuid.UUID, payload: FeatureWrite
) -> Feature:
    feature = session.get(Feature, feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    layer = _managed_layer(session, feature.layer_id)
    validate_geometry(payload.geometry, layer.geometry_types)
    validate_properties(payload.properties)
    feature.external_id = payload.external_id
    feature.geometry = func.ST_SetSRID(
        func.ST_GeomFromGeoJSON(json.dumps(payload.geometry)), 4326
    )
    feature.properties = payload.properties
    feature.status = payload.status
    feature.verified_at = payload.verified_at
    feature.archived_at = None if payload.status != "archived" else datetime.now(UTC)
    session.commit()
    session.refresh(feature)
    return feature


def archive_feature(session: Session, feature_id: uuid.UUID) -> None:
    feature = session.get(Feature, feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    _managed_layer(session, feature.layer_id)
    feature.status = "archived"
    feature.archived_at = datetime.now(UTC)
    session.commit()


def _managed_layer(session: Session, layer_id: uuid.UUID) -> Layer:
    layer = session.scalar(
        select(Layer).where(Layer.id == layer_id, Layer.mode == "managed")
    )
    if layer is None:
        raise HTTPException(status_code=404, detail="Managed layer not found")
    return layer
