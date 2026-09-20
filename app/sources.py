import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.freshness import touch_layer_data
from app.geometry import (
    canonical_geometry_repair,
    validate_geometry,
    validate_properties,
)
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


class GeometryRepairError(ValueError):
    def __init__(self, message: str, counts: dict[str, int]) -> None:
        super().__init__(message)
        self.counts = counts


class SourceAdapter(Protocol):
    def fetch(self, source: ExternalSource) -> list[dict[str, Any]]: ...

    def normalize(
        self, record: dict[str, Any], source: ExternalSource
    ) -> NormalizedFeature: ...


ADAPTERS: dict[str, SourceAdapter] = {}


def register_adapter(name: str, adapter: SourceAdapter) -> None:
    ADAPTERS[name] = adapter


def sync_source(session: Session, source_id: uuid.UUID) -> ExternalSource:
    source, _ = sync_source_report(session, source_id)
    return source


def sync_source_report(
    session: Session, source_id: uuid.UUID
) -> tuple[ExternalSource, dict[str, int]]:
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
            counts = _reconcile(session, source, normalized)
    except Exception as error:
        source.status = "failed"
        source.last_error = str(error)[:2_000]
        session.commit()
        validation_counts = getattr(error, "counts", {})
        return source, {
            "created": 0,
            "updated": 0,
            "archived": 0,
            "unchanged": 0,
            "reactivated": 0,
            "valid_as_received": validation_counts.get("valid_as_received", 0),
            "repaired": validation_counts.get("repaired", 0),
            "rejected": validation_counts.get("rejected", 0),
        }

    source.status = "success"
    source.last_success_at = datetime.now(UTC)
    source.last_error = None
    session.commit()
    return source, counts


def _reconcile(
    session: Session, source: ExternalSource, records: list[NormalizedFeature]
) -> dict[str, int]:
    if len({record.external_id for record in records}) != len(records):
        raise ValueError("Upstream source contains duplicate record IDs")
    records, validation_counts = _prepare_records(session, source, records)
    incoming = {record.external_id: record for record in records}
    existing = {
        feature.external_id: feature
        for feature in session.scalars(
            select(Feature)
            .where(Feature.layer_id == source.layer_id)
            .options(selectinload(Feature.provenance_records))
        )
    }
    owned = {
        external_id: feature
        for external_id, feature in existing.items()
        if _owned_by_source(feature, source)
    }
    for external_id in incoming:
        previous = existing.get(external_id)
        if previous is not None and not _owned_by_source(previous, source):
            raise ValueError(
                f"External record ID '{external_id}' conflicts with a feature "
                "not owned by this source"
            )
    counts = {
        "created": 0,
        "updated": 0,
        "archived": 0,
        "unchanged": 0,
        "reactivated": 0,
        **validation_counts,
    }
    data_changed = False
    for external_id, record in incoming.items():
        previous = owned.pop(external_id, None)
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
            data_changed = True
            counts["created"] += 1
            continue
        feature = previous
        changed = (
            not session.scalar(
                select(func.ST_Equals(feature.geometry, _geometry(record.geometry)))
            )
            or feature.properties != record.properties
            or feature.status != "published"
            or feature.archived_at is not None
        )
        was_archived = previous.archived_at is not None or previous.status == "archived"
        if changed:
            feature.geometry = _geometry(record.geometry)
            feature.properties = record.properties
            feature.status = "published"
            feature.archived_at = None
            _provenance(feature, source, record)
            data_changed = True
            counts["reactivated" if was_archived else "updated"] += 1
        else:
            counts["unchanged"] += 1
    for feature in owned.values():
        if feature.archived_at is None:
            feature.status = "archived"
            feature.archived_at = datetime.now(UTC)
            data_changed = True
            counts["archived"] += 1
    if data_changed:
        touch_layer_data(session, source.layer_id)
    return counts


def _prepare_records(
    session: Session, source: ExternalSource, records: list[NormalizedFeature]
) -> tuple[list[NormalizedFeature], dict[str, int]]:
    repair = canonical_geometry_repair(
        (source.adapter_config or {}).get("geometry_repair")
    )
    prepared: list[NormalizedFeature] = []
    counts = {"valid_as_received": 0, "repaired": 0, "rejected": 0}
    for record in records:
        validate_geometry(record.geometry, source.layer.geometry_types)
        validate_properties(record.properties)
        if repair is None:
            counts["valid_as_received"] += 1
            prepared.append(record)
            continue
        valid, reason, geometry_type, repaired_valid, geometry = session.execute(
            text(
                """
                WITH input AS (
                    SELECT ST_SetSRID(
                        ST_GeomFromGeoJSON(:geometry), 4326
                    ) AS geom
                ), checked AS (
                    SELECT geom, ST_IsValid(geom) AS valid,
                        ST_IsValidReason(geom) AS reason
                    FROM input
                ), candidate AS (
                    SELECT *, CASE WHEN valid THEN geom ELSE ST_MakeValid(geom) END
                        AS repaired
                    FROM checked
                )
                SELECT valid, reason, ST_GeometryType(repaired),
                    ST_IsValid(repaired), ST_AsGeoJSON(repaired)
                FROM candidate
                """
            ),
            {"geometry": json.dumps(record.geometry)},
        ).one()
        if valid:
            counts["valid_as_received"] += 1
            prepared.append(record)
            continue
        allowed = {f"ST_{name}" for name in source.layer.geometry_types}
        if (
            repair["method"] != "make_valid"
            or not repaired_valid
            or geometry_type not in allowed
        ):
            counts["rejected"] += 1
            raise GeometryRepairError(
                f"Geometry is invalid and could not be repaired: {reason}",
                counts.copy(),
            )
        counts["repaired"] += 1
        metadata = dict(record.metadata or {})
        metadata["geometry_repair"] = {
            "method": repair["method"],
            "original_valid": False,
            "original_reason": reason,
        }
        prepared.append(
            NormalizedFeature(
                external_id=record.external_id,
                geometry=json.loads(geometry),
                properties=record.properties,
                source_record_id=record.source_record_id,
                source_url=record.source_url,
                observed_at=record.observed_at,
                metadata=metadata,
            )
        )
    return prepared, counts


def _owned_by_source(feature: Feature, source: ExternalSource) -> bool:
    provenance = feature.provenance_records
    return bool(provenance) and all(
        record.source_type == "external" and record.source_name == source.slug
        for record in provenance
    )


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
