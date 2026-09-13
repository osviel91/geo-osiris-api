import csv
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from geoalchemy2 import Geography
from sqlalchemy import func, literal, or_, select
from sqlalchemy.orm import Session, selectinload

from app.freshness import touch_layer_data
from app.geometry import validate_geometry, validate_properties
from app.models import Feature, FeatureProvenance, ImportJob, ImportRow, Layer
from app.schemas import (
    ImportCommit,
    ImportCreate,
    ImportRowResolution,
    ImportSummary,
)

MAX_IMPORT_ROWS = 10_000
MAX_CSV_FIELD_CHARS = 64_000
MAX_CANDIDATES_PER_ROW = 5
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
        source_name=payload.source_name,
        source_url=payload.source_url,
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
    if job.invalid_count:
        raise HTTPException(
            status_code=409, detail="Resolve invalid rows before committing"
        )
    unresolved = [
        row for row in job.rows if row.candidate_feature_ids and row.resolution is None
    ]
    if unresolved:
        raise HTTPException(
            status_code=409,
            detail="Resolve duplicate candidates before committing",
        )
    committed = [
        row
        for row in job.rows
        if row.validation_error is None and row.resolution != "skip"
    ]
    for row in committed:
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
                source_name=job.source_name or job.filename,
                source_url=job.source_url,
                source_record_id=row.external_id,
                import_id=job.id,
                created_by="admin",
                metadata_={"row_number": row.row_number},
            )
        )
        session.add(feature)
    job.status = "committed"
    job.committed_at = datetime.now(UTC)
    if payload.status == "published" and committed:
        touch_layer_data(session, job.layer_id)
    session.commit()
    return _summary(job)


def cancel_import(session: Session, import_id: uuid.UUID) -> None:
    job = _job(session, import_id)
    if job.status != "validated":
        raise HTTPException(status_code=409, detail="Import is no longer pending")
    job.status = "cancelled"
    job.cancelled_at = datetime.now(UTC)
    session.commit()


def resolve_import_row(
    session: Session,
    import_id: uuid.UUID,
    row_number: int,
    payload: ImportRowResolution,
) -> ImportRow:
    job = session.get(ImportJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    if job.status != "validated":
        raise HTTPException(
            status_code=409, detail="Only validated imports can be resolved"
        )
    row = session.scalar(
        select(ImportRow).where(
            ImportRow.import_id == import_id, ImportRow.row_number == row_number
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Import row not found")
    if not row.candidate_feature_ids:
        raise HTTPException(
            status_code=409, detail="Row has no duplicate candidates to resolve"
        )
    row.resolution = payload.resolution
    row.resolved_at = datetime.now(UTC)
    session.commit()
    session.refresh(row)
    return row


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
    matches = _candidate_matches(session, layer, geometry, external_id, properties)
    return ImportRow(
        row_number=row_number,
        external_id=external_id,
        geometry=geometry,
        properties=properties,
        candidate_feature_ids=[match["feature_id"] for match in matches],
        candidate_matches=matches,
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


def _duplicate_detection(layer: Layer) -> tuple[list[str], float | None]:
    config = layer.metadata_.get("duplicate_detection")
    if not isinstance(config, dict):
        return [], None
    raw_properties = config.get("identity_properties")
    identity_properties = (
        [prop for prop in raw_properties if isinstance(prop, str) and prop]
        if isinstance(raw_properties, list)
        else []
    )
    raw_radius = config.get("coordinate_radius_m")
    radius = (
        float(raw_radius)
        if isinstance(raw_radius, (int, float))
        and not isinstance(raw_radius, bool)
        and raw_radius > 0
        else None
    )
    return identity_properties, radius


def _candidate_matches(
    session: Session,
    layer: Layer,
    geometry: dict[str, Any],
    external_id: str | None,
    properties: dict[str, Any],
) -> list[dict[str, Any]]:
    identity_properties, radius = _duplicate_detection(layer)
    predicates = []
    if external_id:
        predicates.append(Feature.external_id == external_id)
    for prop in identity_properties:
        value = properties.get(prop)
        if value not in (None, ""):
            predicates.append(Feature.properties[prop].astext == str(value))

    spatial = (
        radius is not None
        and isinstance(geometry, dict)
        and geometry.get("type") == "Point"
    )
    geometry_expr = _geometry(geometry) if spatial else None
    if spatial:
        predicates.append(
            func.ST_DWithin(
                func.cast(Feature.geometry, Geography),
                func.cast(geometry_expr, Geography),
                radius,
            )
        )
    if not predicates:
        return []

    distance = (
        func.ST_Distance(
            func.cast(Feature.geometry, Geography),
            func.cast(geometry_expr, Geography),
        ).label("distance_m")
        if spatial
        else literal(None).label("distance_m")
    )
    statement = (
        select(
            Feature.id,
            Feature.external_id,
            Feature.properties,
            Feature.status,
            func.ST_AsGeoJSON(Feature.geometry).label("geometry_json"),
            distance,
        )
        .where(
            Feature.layer_id == layer.id,
            Feature.archived_at.is_(None),
            or_(*predicates),
        )
        .order_by(Feature.id)
        .limit(MAX_CANDIDATES_PER_ROW)
    )

    matches = []
    for row in session.execute(statement).mappings():
        reasons = []
        if external_id and row["external_id"] == external_id:
            reasons.append({"type": "external_id", "value": external_id})
        for prop in identity_properties:
            value = properties.get(prop)
            if value not in (None, "") and row["properties"].get(prop) == value:
                reasons.append(
                    {"type": "property_exact", "property": prop, "value": value}
                )
        if (
            spatial
            and row["distance_m"] is not None
            and float(row["distance_m"]) <= radius
        ):
            reasons.append(
                {
                    "type": "spatial_proximity",
                    "distance_m": round(float(row["distance_m"]), 1),
                    "threshold_m": radius,
                }
            )
        if not reasons:
            continue
        matches.append(
            {
                "feature_id": str(row["id"]),
                "reasons": reasons,
                "summary": _candidate_summary(layer, row),
            }
        )
    return matches


def _candidate_summary(layer: Layer, row: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "external_id": row["external_id"],
        "status": row["status"],
    }
    geometry = json.loads(row["geometry_json"])
    if geometry.get("type") == "Point":
        summary["coordinates"] = geometry["coordinates"]
    label_property = (
        layer.style.get("label_property") if isinstance(layer.style, dict) else None
    )
    if isinstance(label_property, str) and row["properties"].get(label_property):
        summary["label"] = str(row["properties"][label_property])
    elif row["external_id"]:
        summary["label"] = row["external_id"]
    return summary


def _geometry(geometry: dict[str, Any] | None) -> Any:
    assert geometry is not None
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
        source_name=job.source_name,
        source_url=job.source_url,
    )
