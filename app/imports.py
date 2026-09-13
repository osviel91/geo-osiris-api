import csv
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.geometry import validate_geometry, validate_properties
from app.models import Feature, FeatureProvenance, ImportJob, ImportRow, Layer
from app.schemas import ImportCommit, ImportCreate, ImportRowSummary, ImportSummary


def stage_import(session: Session, payload: ImportCreate) -> ImportSummary:
    layer = _managed_layer(session, payload.layer_id)
    records = _parse_records(payload)
    job = ImportJob(
        layer=layer,
        filename=payload.filename,
        format=payload.format,
        row_count=0,
        invalid_count=0,
        candidate_count=0,
    )
    session.add(job)
    for row_number, record in enumerate(records, start=1):
        row = _stage_row(session, layer, job, row_number, record)
        job.rows.append(row)
        job.invalid_count += row.validation_error is not None
        job.candidate_count += bool(row.candidate_feature_ids)
    job.row_count = len(job.rows)
    session.commit()
    session.refresh(job)
    return _summary(job)


def get_import(session: Session, import_id: uuid.UUID) -> ImportSummary:
    job = _job(session, import_id)
    return _summary(job)


def commit_import(
    session: Session, import_id: uuid.UUID, payload: ImportCommit
) -> ImportSummary:
    job = _job(session, import_id)
    if job.status != "validated":
        raise HTTPException(status_code=409, detail="Import is no longer pending")
    if job.invalid_count or job.candidate_count:
        raise HTTPException(
            status_code=409,
            detail="Resolve invalid rows and duplicate candidates before committing",
        )
    for row in job.rows:
        feature = Feature(
            layer_id=job.layer_id,
            external_id=row.external_id,
            geometry=_geometry(row.geometry),
            properties=row.properties,
            status=payload.status,
        )
        feature.provenance_records.append(
            FeatureProvenance(
                source_type="import",
                source_name=job.filename,
                source_record_id=row.external_id,
                import_id=job.id,
                created_by="admin",
                metadata_={"row_number": row.row_number},
            )
        )
        session.add(feature)
    job.status = "committed"
    job.committed_at = datetime.now(UTC)
    session.commit()
    return _summary(job)


def cancel_import(session: Session, import_id: uuid.UUID) -> None:
    job = _job(session, import_id)
    if job.status != "validated":
        raise HTTPException(status_code=409, detail="Import is no longer pending")
    job.rows.clear()
    job.status = "cancelled"
    job.cancelled_at = datetime.now(UTC)
    session.commit()


def _stage_row(
    session: Session,
    layer: Layer,
    job: ImportJob,
    row_number: int,
    record: dict[str, Any],
) -> ImportRow:
    geometry = record.get("geometry")
    properties = record.get("properties", {})
    external_id = record.get("external_id")
    try:
        if not isinstance(geometry, dict) or not isinstance(properties, dict):
            raise HTTPException(status_code=422, detail="Invalid feature record")
        validate_geometry(geometry, layer.geometry_types)
        validate_properties(properties)
    except HTTPException as error:
        return ImportRow(
            row_number=row_number,
            external_id=external_id,
            geometry=geometry if isinstance(geometry, dict) else None,
            properties=properties if isinstance(properties, dict) else {},
            validation_error=str(error.detail),
            candidate_feature_ids=[],
        )
    return ImportRow(
        row_number=row_number,
        external_id=external_id,
        geometry=geometry,
        properties=properties,
        candidate_feature_ids=_candidate_ids(
            session, layer.id, external_id, properties
        ),
    )


def _parse_records(payload: ImportCreate) -> list[dict[str, Any]]:
    try:
        if payload.format == "geojson":
            document = json.loads(payload.content)
            if document.get("type") != "FeatureCollection":
                raise ValueError("GeoJSON must be a FeatureCollection")
            return [
                {
                    "external_id": feature.get("properties", {}).get("external_id"),
                    "geometry": feature.get("geometry"),
                    "properties": feature.get("properties", {}),
                }
                for feature in document["features"]
            ]
        return _parse_csv(payload.content, payload.csv_mapping)
    except (KeyError, TypeError, ValueError, csv.Error, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=422, detail=f"Invalid import: {error}"
        ) from error


def _parse_csv(content: str, mapping: dict[str, Any]) -> list[dict[str, Any]]:
    longitude = mapping.get("longitude", "longitude")
    latitude = mapping.get("latitude", "latitude")
    external_id = mapping.get("external_id", "external_id")
    property_columns = mapping.get("properties", {})
    if not isinstance(property_columns, dict):
        raise ValueError("CSV properties mapping must be an object")
    records = []
    for row in csv.DictReader(io.StringIO(content)):
        properties = (
            {name: row.get(column) for name, column in property_columns.items()}
            if property_columns
            else {
                key: value
                for key, value in row.items()
                if key not in {longitude, latitude, external_id}
            }
        )
        records.append(
            {
                "external_id": row.get(external_id) or None,
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row[longitude]), float(row[latitude])],
                },
                "properties": properties,
            }
        )
    return records


def _candidate_ids(
    session: Session, layer_id: uuid.UUID, external_id: str | None, properties: dict
) -> list[str]:
    matches = []
    if external_id:
        matches.append(Feature.external_id == external_id)
    callsign = properties.get("callsign")
    if callsign:
        matches.append(Feature.properties["callsign"].astext == str(callsign))
    if not matches:
        return []
    statement = (
        select(Feature.id)
        .where(
            Feature.layer_id == layer_id,
            Feature.archived_at.is_(None),
            or_(*matches),
        )
        .order_by(Feature.id)
    )
    return [str(feature_id) for feature_id in session.scalars(statement)]


def _geometry(geometry: dict[str, Any] | None) -> Any:
    assert geometry is not None
    from sqlalchemy import func

    return func.ST_SetSRID(func.ST_GeomFromGeoJSON(json.dumps(geometry)), 4326)


def _job(session: Session, import_id: uuid.UUID) -> ImportJob:
    job = session.scalar(
        select(ImportJob)
        .where(ImportJob.id == import_id)
        .options(selectinload(ImportJob.rows))
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    return job


def _managed_layer(session: Session, layer_id: uuid.UUID) -> Layer:
    layer = session.scalar(
        select(Layer).where(Layer.id == layer_id, Layer.mode == "managed")
    )
    if layer is None:
        raise HTTPException(status_code=404, detail="Managed layer not found")
    return layer


def _summary(job: ImportJob) -> ImportSummary:
    return ImportSummary(
        id=str(job.id),
        layer_id=str(job.layer_id),
        filename=job.filename,
        format=job.format,
        status=job.status,
        row_count=job.row_count,
        invalid_count=job.invalid_count,
        candidate_count=job.candidate_count,
        rows=[
            ImportRowSummary(
                row_number=row.row_number,
                validation_error=row.validation_error,
                candidate_feature_ids=row.candidate_feature_ids,
            )
            for row in sorted(job.rows, key=lambda row: row.row_number)
        ],
    )
