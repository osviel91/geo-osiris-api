import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.geometry import validate_geometry, validate_properties
from app.models import ExternalSource, Feature, FeatureProvenance


@dataclass
class NormalizedFeature:
    external_id: str
    geometry: dict[str, Any]
    properties: dict[str, Any]
    source_record_id: str
    source_url: str | None = None
    observed_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class SourceAdapter(Protocol):
    def fetch(self, source: ExternalSource) -> list[dict[str, Any]]: ...

    def normalize(
        self, record: dict[str, Any], source: ExternalSource
    ) -> NormalizedFeature: ...


ADAPTERS: dict[str, SourceAdapter] = {}


def register_adapter(name: str, adapter: SourceAdapter) -> None:
    ADAPTERS[name] = adapter


def sync_source(session: Session, source_id: uuid.UUID) -> ExternalSource:
    source = session.scalar(
        select(ExternalSource)
        .where(ExternalSource.id == source_id)
        .options(selectinload(ExternalSource.layer))
    )
    if source is None:
        raise HTTPException(status_code=404, detail="External source not found")
    if not source.enabled:
        raise HTTPException(status_code=409, detail="External source is disabled")
    if not session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:source))"),
        {"source": source.slug},
    ):
        session.rollback()
        raise HTTPException(
            status_code=409, detail="External source sync is already running"
        )

    source.last_attempt_at = datetime.now(UTC)
    try:
        adapter = ADAPTERS[source.adapter]
        with session.begin_nested():
            records = adapter.fetch(source)
            normalized = [adapter.normalize(record, source) for record in records]
            _reconcile(session, source, normalized)
    except Exception as error:
        source.status = "failed"
        source.last_error = str(error)[:2_000]
        session.commit()
        return source

    source.status = "success"
    source.last_success_at = datetime.now(UTC)
    source.last_error = None
    session.commit()
    return source


def _reconcile(
    session: Session, source: ExternalSource, records: list[NormalizedFeature]
) -> None:
    incoming = {record.external_id: record for record in records}
    if len(incoming) != len(records):
        raise ValueError("Upstream source contains duplicate record IDs")
    for record in records:
        validate_geometry(record.geometry, source.layer.geometry_types)
        validate_properties(record.properties)
    rows = session.execute(
        select(
            Feature,
            func.ST_AsGeoJSON(Feature.geometry).label("geometry_json"),
        ).where(Feature.layer_id == source.layer_id)
    ).all()
    existing = {
        feature.external_id: (feature, geometry_json) for feature, geometry_json in rows
    }
    for external_id, record in incoming.items():
        previous = existing.pop(external_id, None)
        if previous is None:
            feature = Feature(
                layer_id=source.layer_id,
                external_id=external_id,
                geometry=_geometry(record.geometry),
                properties=record.properties,
                status="published",
            )
            session.add(feature)
            _provenance(feature, source, record)
            continue
        feature, geometry_json = previous
        changed = (
            json.loads(geometry_json) != record.geometry
            or feature.properties != record.properties
            or feature.status != "published"
            or feature.archived_at is not None
        )
        if changed:
            feature.geometry = _geometry(record.geometry)
            feature.properties = record.properties
            feature.status = "published"
            feature.archived_at = None
            _provenance(feature, source, record)
    for feature, _ in existing.values():
        if feature.archived_at is None:
            feature.status = "archived"
            feature.archived_at = datetime.now(UTC)


def _provenance(
    feature: Feature, source: ExternalSource, record: NormalizedFeature
) -> None:
    feature.provenance_records.append(
        FeatureProvenance(
            source_type="external",
            source_name=source.slug,
            source_url=record.source_url or source.endpoint,
            source_record_id=record.source_record_id,
            created_by="sync",
            observed_at=record.observed_at,
            metadata_={"dataset_id": source.dataset_id, **(record.metadata or {})},
        )
    )


def _geometry(geometry: dict[str, Any]) -> Any:
    return func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(geometry)), 4326)
