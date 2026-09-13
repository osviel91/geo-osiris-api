import csv
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.freshness import touch_layer_data
from app.geometry import validate_geometry, validate_properties
from app.models import Feature, FeatureProvenance, ImportJob, ImportRow, Layer
from app.schemas import ImportCommit, ImportCreate, ImportSummary

MAX_IMPORT_ROWS = 10_000
MAX_CSV_FIELD_CHARS = 64_000
MAPPING_VERSION = "1"

csv.field_size_limit(MAX_CSV_FIELD_CHARS)


def stage_import(session: Session, payload: ImportCreate) -> ImportSummary:
    layer = _managed_layer(session, payload.layer_id)
    records, headers, mapping = _parse_records(payload)
    if len(records) > MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=422, detail=f"Import exceeds {MAX_IMPORT_ROWS} rows"
        )
    job = ImportJob(
        layer=layer,
        filename=payload.filename,
        format=payload.format,
        row_count=0,
        invalid_count=0,
        candidate_count=0,
        csv_mapping=mapping,
        csv_headers=headers,
        mapping_version=MAPPING_VERSION,
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
    if payload.status == "published" and job.rows:
        touch_layer_data(session, job.layer_id)
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
    error = record.get("error")
    if error is None:
        try:
            if not isinstance(geometry, dict) or not isinstance(properties, dict):
                raise HTTPException(status_code=422, detail="Invalid feature record")
            validate_geometry(geometry, layer.geometry_types)
            validate_properties(properties)
        except HTTPException as exception:
            error = str(exception.detail)
    if error is not None:
        return ImportRow(
            row_number=row_number,
            external_id=external_id,
            geometry=geometry if isinstance(geometry, dict) else None,
            properties=properties if isinstance(properties, dict) else {},
            validation_error=error,
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


def _parse_records(
    payload: ImportCreate,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    try:
        if payload.format == "geojson":
            document = json.loads(payload.content)
            if not isinstance(document, dict) or document.get("type") != (
                "FeatureCollection"
            ):
                raise ValueError("GeoJSON must be a FeatureCollection")
            features = document["features"]
            if not isinstance(features, list):
                raise ValueError("GeoJSON features must be a list")
            records = [
                {
                    "external_id": feature.get("properties", {}).get("external_id"),
                    "geometry": feature.get("geometry"),
                    "properties": feature.get("properties", {}),
                }
                for feature in features
            ]
            return records, [], {}
        return _parse_csv(payload.content, payload.csv_mapping)
    except (KeyError, TypeError, ValueError, csv.Error, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=422, detail=f"Invalid import: {error}"
        ) from error


def _parse_csv(
    content: str, mapping: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(content))
    headers = list(reader.fieldnames or [])
    normalized = _normalize_csv_mapping(mapping, headers)
    records = [_csv_record(row, normalized) for row in reader]
    return records, headers, normalized


def _normalize_csv_mapping(
    mapping: dict[str, Any], headers: list[str]
) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        raise ValueError("csv_mapping must be an object")
    longitude = mapping.get("longitude") or "longitude"
    latitude = mapping.get("latitude") or "latitude"
    external_id = mapping.get("external_id") or None
    property_columns = mapping.get("properties")
    if property_columns is None:
        property_columns = {}
    if not isinstance(longitude, str) or not longitude:
        raise ValueError("longitude mapping must be a header name")
    if not isinstance(latitude, str) or not latitude:
        raise ValueError("latitude mapping must be a header name")
    if external_id is not None and (
        not isinstance(external_id, str) or not external_id
    ):
        raise ValueError("external_id mapping must be a header name")
    if not isinstance(property_columns, dict):
        raise ValueError("CSV properties mapping must be an object")
    if longitude == latitude:
        raise ValueError("longitude and latitude must map to different columns")
    for name, column in property_columns.items():
        if not isinstance(name, str) or not name:
            raise ValueError("CSV property names must be non-empty strings")
        if not isinstance(column, str) or not column:
            raise ValueError("CSV property columns must be header names")
        if column in {longitude, latitude}:
            raise ValueError("CSV property columns cannot reuse coordinate columns")
    for column in (longitude, latitude):
        if column not in headers:
            raise ValueError(f"CSV is missing mapped column '{column}'")
    if external_id is not None and external_id not in headers:
        raise ValueError(f"CSV is missing mapped column '{external_id}'")
    reserved = {longitude, latitude}
    if external_id:
        reserved.add(external_id)
    if property_columns:
        resolved = dict(property_columns)
        for column in resolved.values():
            if column not in headers:
                raise ValueError(f"CSV is missing mapped column '{column}'")
    else:
        resolved = {header: header for header in headers if header not in reserved}
    return {
        "longitude": longitude,
        "latitude": latitude,
        "external_id": external_id,
        "properties": resolved,
    }


def _csv_record(row: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    properties = {
        name: row.get(column) for name, column in mapping["properties"].items()
    }
    external_id = (
        row.get(mapping["external_id"]) or None if mapping["external_id"] else None
    )
    record: dict[str, Any] = {
        "external_id": external_id,
        "properties": properties,
        "geometry": None,
    }
    longitude_raw = row.get(mapping["longitude"])
    latitude_raw = row.get(mapping["latitude"])
    if longitude_raw in (None, ""):
        record["error"] = "Missing longitude value"
        return record
    if latitude_raw in (None, ""):
        record["error"] = "Missing latitude value"
        return record
    try:
        longitude = float(longitude_raw)
    except (TypeError, ValueError):
        record["error"] = "Invalid longitude value"
        return record
    try:
        latitude = float(latitude_raw)
    except (TypeError, ValueError):
        record["error"] = "Invalid latitude value"
        return record
    record["geometry"] = {
        "type": "Point",
        "coordinates": [longitude, latitude],
    }
    return record


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
        valid_count=max(job.row_count - job.invalid_count, 0),
        invalid_count=job.invalid_count,
        candidate_count=job.candidate_count,
        csv_mapping=job.csv_mapping,
        csv_headers=job.csv_headers,
        mapping_version=job.mapping_version,
    )
