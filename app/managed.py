import json
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.freshness import touch_layer_data
from app.geometry import validate_geometry, validate_properties
from app.models import Feature, FeatureProvenance, Layer
from app.schemas import FeaturePatch, FeatureWrite, LayerCreate, LayerUpdate


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
    if payload.status == "published":
        touch_layer_data(session, layer.id)
    session.commit()
    session.refresh(feature)
    return feature


def patch_feature(
    session: Session, feature_id: uuid.UUID, payload: FeaturePatch
) -> Feature:
    feature = session.get(Feature, feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    layer = _managed_layer(session, feature.layer_id)
    fields = payload.model_fields_set
    previous_status = feature.status
    changed: list[str] = []

    if "status" in fields and payload.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Use the feature archive lifecycle action",
        )
    if "status" in fields and previous_status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Use the feature restore lifecycle action",
        )

    if "geometry" in fields and payload.geometry is not None:
        validate_geometry(payload.geometry, layer.geometry_types)
        feature.geometry = func.ST_SetSRID(
            func.ST_GeomFromGeoJSON(json.dumps(payload.geometry)), 4326
        )
        changed.append("geometry")

    if "properties" in fields and payload.properties is not None:
        merged = dict(feature.properties or {})
        for key, value in payload.properties.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        validate_properties(merged)
        if merged != (feature.properties or {}):
            feature.properties = merged
            changed.append("properties")

    if "external_id" in fields and payload.external_id != feature.external_id:
        feature.external_id = payload.external_id
        changed.append("external_id")

    if (
        "status" in fields
        and payload.status is not None
        and payload.status != feature.status
    ):
        feature.status = payload.status
        changed.append("status")

    if "verified_at" in fields and payload.verified_at != feature.verified_at:
        feature.verified_at = payload.verified_at
        changed.append("verified_at")

    if feature.status == "archived":
        if previous_status != "archived":
            feature.archived_at = datetime.now(UTC)
    else:
        feature.archived_at = None

    feature.provenance_records.append(
        FeatureProvenance(
            source_type=payload.source_type or "manual",
            source_name=payload.source_name,
            source_url=payload.source_url,
            source_record_id=payload.source_record_id,
            created_by="admin",
            metadata_={"action": "edit", "changed": changed, "actor": "admin"},
        )
    )
    if previous_status == "published" or feature.status == "published":
        touch_layer_data(session, feature.layer_id)
    session.commit()
    session.refresh(feature)
    return feature


def archive_feature(session: Session, feature_id: uuid.UUID) -> None:
    feature = session.get(Feature, feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    _managed_layer(session, feature.layer_id)
    was_published = feature.status == "published"
    feature.status = "archived"
    feature.archived_at = datetime.now(UTC)
    if was_published:
        touch_layer_data(session, feature.layer_id)
    session.commit()


def _managed_layer(session: Session, layer_id: uuid.UUID) -> Layer:
    layer = session.scalar(
        select(Layer).where(Layer.id == layer_id, Layer.mode == "managed")
    )
    if layer is None:
        raise HTTPException(status_code=404, detail="Managed layer not found")
    return layer
