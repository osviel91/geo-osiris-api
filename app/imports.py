import csv
import hashlib
import io
import json
import math
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from geoalchemy2 import Geography
from sqlalchemy import and_, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.freshness import touch_layer_data
from app.geometry import validate_geometry, validate_properties
from app.models import (
    Feature,
    FeatureProvenance,
    ImportApproval,
    ImportJob,
    ImportRow,
    Layer,
)
from app.schemas import (
    ApprovalDecision,
    ImportApprovalRead,
    ImportCommit,
    ImportCreate,
    ImportRowResolution,
    ImportSummary,
)

MAX_IMPORT_ROWS = 10_000
MAX_CSV_FIELD_CHARS = 64_000
MAX_CANDIDATES_PER_ROW = 5
MAPPING_VERSION_V1 = "1"
MAPPING_VERSION_V2 = "2"
PROPERTY_TYPES = {"string", "number", "integer", "boolean", "json"}

csv.field_size_limit(MAX_CSV_FIELD_CHARS)


def stage_import(session: Session, payload: ImportCreate) -> ImportSummary:
    layer = _managed_layer(session, payload.layer_id)
    records, headers, mapping, mapping_version = _parse_records(payload)
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
        mapping_version=mapping_version,
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


def execute_approved_import(
    session: Session, import_id: uuid.UUID, payload: ImportCommit, executor: str
) -> ImportSummary:
    job = _locked_job(session, import_id)
    approval = _active_approval(session, import_id, lock=True)
    if approval is None:
        raise HTTPException(status_code=409, detail="No active approval request")
    _require_approved(session, approval)
    status = payload.status if payload.status is not None else approval.requested_status
    if approval.requested_status != status:
        raise HTTPException(
            status_code=409, detail="Approved output status does not match"
        )
    if approval.fingerprint != _fingerprint(_snapshot(job, status)):
        approval.state = "stale"
        session.commit()
        raise HTTPException(status_code=409, detail="Approval is stale")
    try:
        with session.begin_nested():
            _commit_job(session, job, ImportCommit(status=status))
            session.flush()
    except SQLAlchemyError:
        approval.state = "failed"
        approval.failure_reason = "Authoritative import commit failed"
        session.commit()
        raise HTTPException(status_code=409, detail="Publication failed") from None
    approval.state = "executed"
    approval.executor = executor
    approval.executed_at = datetime.now(UTC)
    session.commit()
    return _summary(job)


def _commit_job(session: Session, job: ImportJob, payload: ImportCommit) -> None:
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


def cancel_import(session: Session, import_id: uuid.UUID) -> None:
    job = _locked_job(session, import_id)
    if job.status != "validated":
        raise HTTPException(status_code=409, detail="Import is no longer pending")
    job.status = "cancelled"
    job.cancelled_at = datetime.now(UTC)
    _stale_active_approval(session, import_id)
    session.commit()


def resolve_import_row(
    session: Session,
    import_id: uuid.UUID,
    row_number: int,
    payload: ImportRowResolution,
) -> ImportRow:
    job = _locked_job(session, import_id)
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
    _stale_active_approval(session, import_id)
    session.commit()
    session.refresh(row)
    return row


def create_approval_request(
    session: Session,
    import_id: uuid.UUID,
    payload: ImportCommit,
    requester: str,
) -> ImportApprovalRead:
    if payload.status is None:
        raise HTTPException(status_code=422, detail="status is required")
    job = _locked_job(session, import_id)
    _ensure_ready(job)
    _expire_active_approval(session, import_id)
    if _active_approval(session, import_id, lock=True) is not None:
        raise HTTPException(
            status_code=409, detail="Import already has an active approval"
        )
    snapshot = _snapshot(job, payload.status)
    approval = ImportApproval(
        import_id=job.id,
        snapshot=snapshot,
        fingerprint=_fingerprint(snapshot),
        requested_status=payload.status,
        requester=requester,
        expires_at=datetime.now(UTC) + timedelta(minutes=_approval_ttl_minutes()),
    )
    session.add(approval)
    session.commit()
    session.refresh(approval)
    return approval_read(approval)


def decide_approval(
    session: Session,
    import_id: uuid.UUID,
    payload: ApprovalDecision,
    approver: str,
) -> ImportApprovalRead:
    _locked_job(session, import_id)
    approval = _active_approval(session, import_id, lock=True)
    if approval is None:
        raise HTTPException(status_code=409, detail="No active approval request")
    _expire_or_raise(session, approval)
    if approval.state != "pending":
        raise HTTPException(status_code=409, detail="Approval has already been decided")
    approval.approver = approver
    approval.approved_at = datetime.now(UTC)
    if payload.decision == "approve":
        approval.state = "approved"
    else:
        approval.state = "rejected"
        approval.rejection_reason = payload.reason
    session.commit()
    session.refresh(approval)
    return approval_read(approval)


def approval_read(approval: ImportApproval) -> ImportApprovalRead:
    return ImportApprovalRead(
        id=str(approval.id),
        import_id=str(approval.import_id),
        fingerprint=approval.fingerprint,
        requested_status=approval.requested_status,
        requester=approval.requester,
        requested_at=approval.requested_at,
        state=approval.state,
        approver=approval.approver,
        approved_at=approval.approved_at,
        rejection_reason=approval.rejection_reason,
        expires_at=approval.expires_at,
        executor=approval.executor,
        executed_at=approval.executed_at,
        failure_reason=approval.failure_reason,
        snapshot=approval.snapshot,
    )


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
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any], str]:
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
            return records, [], {}, MAPPING_VERSION_V1
        return _parse_csv(payload.content, payload.csv_mapping)
    except (KeyError, TypeError, ValueError, csv.Error, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=422, detail=f"Invalid import: {error}"
        ) from error


def _parse_csv(
    content: str, mapping: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any], str]:
    reader = csv.DictReader(io.StringIO(content))
    headers = list(reader.fieldnames or [])
    normalized, mapping_version = _normalize_csv_mapping(mapping, headers)
    records = [_csv_record(row, normalized) for row in reader]
    return records, headers, normalized, mapping_version


def _normalize_csv_mapping(
    mapping: dict[str, Any], headers: list[str]
) -> tuple[dict[str, Any], str]:
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
    for name in property_columns:
        if not isinstance(name, str) or not name:
            raise ValueError("CSV property names must be non-empty strings")
    for column in (longitude, latitude):
        if column not in headers:
            raise ValueError(f"CSV is missing mapped column '{column}'")
    if external_id is not None and external_id not in headers:
        raise ValueError(f"CSV is missing mapped column '{external_id}'")
    reserved = {longitude, latitude}
    if external_id:
        reserved.add(external_id)
    uses_typed_mapping = False
    resolved: dict[str, Any] = {}
    if property_columns:
        for name, specification in property_columns.items():
            if isinstance(specification, str):
                column = specification
                property_type = "string"
            elif isinstance(specification, dict):
                column = specification.get("column")
                property_type = specification.get("type", "string")
                uses_typed_mapping = True
            else:
                raise ValueError(
                    "CSV property mappings must be column strings or objects"
                )
            if not isinstance(column, str) or not column:
                raise ValueError("CSV property columns must be header names")
            if column in {longitude, latitude}:
                raise ValueError("CSV property columns cannot reuse coordinate columns")
            if column not in headers:
                raise ValueError(f"CSV is missing mapped column '{column}'")
            if (
                not isinstance(property_type, str)
                or property_type not in PROPERTY_TYPES
            ):
                raise ValueError(f"Unsupported CSV property type '{property_type}'")
            resolved[name] = (
                {"column": column, "type": property_type}
                if uses_typed_mapping
                else column
            )
        if uses_typed_mapping:
            resolved = {
                name: (
                    specification
                    if isinstance(specification, dict)
                    else {"column": specification, "type": "string"}
                )
                for name, specification in resolved.items()
            }
    else:
        resolved = {header: header for header in headers if header not in reserved}
    normalized = {
        "longitude": longitude,
        "latitude": latitude,
        "external_id": external_id,
        "properties": resolved,
    }
    return (
        normalized,
        MAPPING_VERSION_V2 if uses_typed_mapping else MAPPING_VERSION_V1,
    )


def _csv_record(row: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    external_id = (
        row.get(mapping["external_id"]) or None if mapping["external_id"] else None
    )
    record: dict[str, Any] = {
        "external_id": external_id,
        "properties": properties,
        "geometry": None,
    }
    try:
        for name, specification in mapping["properties"].items():
            if isinstance(specification, str):
                properties[name] = row.get(specification)
            else:
                properties[name] = _csv_property_value(
                    row.get(specification["column"]), specification["type"], name
                )
    except ValueError as error:
        record["error"] = str(error)
        return record
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


def _csv_property_value(value: str | None, property_type: str, name: str) -> Any:
    if value in (None, ""):
        return None
    if property_type == "string":
        return value
    if property_type == "number":
        try:
            number = float(value)
        except ValueError as error:
            raise ValueError(f"Invalid number value for property '{name}'") from error
        if math.isfinite(number):
            return number
        raise ValueError(f"Invalid number value for property '{name}'")
    if property_type == "integer":
        if re.fullmatch(r"[+-]?\d+", value.strip()):
            return int(value)
        raise ValueError(f"Invalid integer value for property '{name}'")
    if property_type == "boolean":
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
        raise ValueError(f"Invalid boolean value for property '{name}'")
    try:
        return json.loads(value, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid JSON value for property '{name}'") from error


def _reject_json_constant(_: str) -> None:
    raise ValueError("Invalid JSON constant")


def _duplicate_detection(layer: Layer) -> dict[str, Any]:
    config = layer.metadata_.get("duplicate_detection")
    if not isinstance(config, dict):
        return {"groups": [], "radius": None, "require_identity_signal": False}

    groups: list[list[str]] = []
    raw_groups = config.get("identity_groups")
    if isinstance(raw_groups, list):
        for group in raw_groups:
            if isinstance(group, list):
                props = [prop for prop in group if isinstance(prop, str) and prop]
                if props:
                    groups.append(props)
    if not groups:
        raw_properties = config.get("identity_properties")
        if isinstance(raw_properties, list):
            groups = [
                [prop] for prop in raw_properties if isinstance(prop, str) and prop
            ]

    raw_radius = config.get("coordinate_radius_m")
    require_identity_signal = False
    spatial = config.get("spatial")
    if isinstance(spatial, dict):
        raw_radius = spatial.get("radius_m")
        require_identity_signal = spatial.get("require_identity_signal") is True

    radius = (
        float(raw_radius)
        if isinstance(raw_radius, (int, float))
        and not isinstance(raw_radius, bool)
        and raw_radius > 0
        else None
    )
    return {
        "groups": groups,
        "radius": radius,
        "require_identity_signal": require_identity_signal,
    }


def _group_matches(group: list[str], properties: dict[str, Any]) -> bool:
    return all(properties.get(prop) not in (None, "") for prop in group)


def _candidate_matches(
    session: Session,
    layer: Layer,
    geometry: dict[str, Any],
    external_id: str | None,
    properties: dict[str, Any],
) -> list[dict[str, Any]]:
    detection = _duplicate_detection(layer)
    groups = detection["groups"]
    radius = detection["radius"]
    require_identity_signal = detection["require_identity_signal"]

    predicates = []
    if external_id:
        predicates.append(Feature.external_id == external_id)
    for group in groups:
        if _group_matches(group, properties):
            predicates.append(
                and_(
                    *(
                        Feature.properties[prop]
                        == cast(literal(json.dumps(properties[prop])), JSONB)
                        for prop in group
                    )
                )
            )

    spatial = (
        radius is not None
        and isinstance(geometry, dict)
        and geometry.get("type") == "Point"
    )
    geometry_expr = _geometry(geometry) if spatial else None
    if spatial and not require_identity_signal:
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
        matched_properties: list[str] = []
        for group in groups:
            if not _group_matches(group, properties):
                continue
            if all(
                row["properties"].get(prop) == properties.get(prop) for prop in group
            ):
                for prop in group:
                    if prop not in matched_properties:
                        matched_properties.append(prop)
        for prop in matched_properties:
            reasons.append(
                {"type": "property_exact", "property": prop, "value": properties[prop]}
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


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _snapshot(job: ImportJob, requested_status: str) -> dict[str, Any]:
    rows = [
        {
            "row_number": row.row_number,
            "external_id": row.external_id,
            "geometry": row.geometry,
            "properties": row.properties,
            "validation_error": row.validation_error,
            "candidate_feature_ids": row.candidate_feature_ids,
            "candidate_matches": row.candidate_matches,
            "resolution": row.resolution,
        }
        for row in sorted(job.rows, key=lambda row: row.row_number)
    ]
    mapping = {
        "csv_mapping": job.csv_mapping,
        "csv_headers": job.csv_headers,
        "mapping_version": job.mapping_version,
    }
    resolved = sum(
        bool(row["candidate_feature_ids"] and row["resolution"]) for row in rows
    )
    return {
        "import_id": str(job.id),
        "layer_id": str(job.layer_id),
        "filename": job.filename,
        "format": job.format,
        "source_name": job.source_name,
        "source_url": job.source_url,
        "status": job.status,
        "requested_status": requested_status,
        "row_count": job.row_count,
        "valid_count": max(job.row_count - job.invalid_count, 0),
        "invalid_count": job.invalid_count,
        "candidate_count": job.candidate_count,
        "resolved_candidate_count": resolved,
        "unresolved_candidate_count": job.candidate_count - resolved,
        "mapping": mapping,
        "mapping_hash": _digest(mapping),
        "content_hash": _digest(rows),
        "rows": rows,
    }


def _fingerprint(snapshot: dict[str, Any]) -> str:
    return _digest(snapshot)


def _approval_ttl_minutes() -> int:
    try:
        return max(1, int(os.getenv("APPROVAL_TTL_MINUTES", "60")))
    except ValueError as error:
        raise RuntimeError("APPROVAL_TTL_MINUTES must be an integer") from error


def _active_approval(
    session: Session, import_id: uuid.UUID, lock: bool = False
) -> ImportApproval | None:
    statement = select(ImportApproval).where(
        ImportApproval.import_id == import_id,
        ImportApproval.state.in_(("pending", "approved")),
    )
    if lock:
        statement = statement.with_for_update()
    return session.scalar(statement)


def _expire_active_approval(session: Session, import_id: uuid.UUID) -> None:
    approval = _active_approval(session, import_id, lock=True)
    if approval is not None and approval.expires_at <= datetime.now(UTC):
        approval.state = "expired"


def _expire_or_raise(session: Session, approval: ImportApproval) -> None:
    if approval.expires_at <= datetime.now(UTC):
        approval.state = "expired"
        session.commit()
        raise HTTPException(status_code=409, detail="Approval has expired")


def _stale_active_approval(session: Session, import_id: uuid.UUID) -> None:
    approval = _active_approval(session, import_id, lock=True)
    if approval is not None:
        approval.state = "stale"


def _require_approved(session: Session, approval: ImportApproval) -> None:
    _expire_or_raise(session, approval)
    if approval.state != "approved":
        raise HTTPException(status_code=409, detail="Approval is not approved")


def _ensure_ready(job: ImportJob) -> None:
    if job.status != "validated":
        raise HTTPException(status_code=409, detail="Import is no longer pending")
    if job.invalid_count:
        raise HTTPException(
            status_code=409, detail="Resolve invalid rows before committing"
        )
    if any(row.candidate_feature_ids and row.resolution is None for row in job.rows):
        raise HTTPException(
            status_code=409, detail="Resolve duplicate candidates before committing"
        )


def _job(session: Session, import_id: uuid.UUID) -> ImportJob:
    job = session.scalar(
        select(ImportJob)
        .where(ImportJob.id == import_id)
        .options(selectinload(ImportJob.rows))
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    return job


def _locked_job(session: Session, import_id: uuid.UUID) -> ImportJob:
    job = session.scalar(
        select(ImportJob)
        .where(ImportJob.id == import_id)
        .options(selectinload(ImportJob.rows))
        .with_for_update()
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
