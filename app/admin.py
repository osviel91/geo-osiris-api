"""Read models for the generic Geo Hub administration API."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.models import (
    ExternalSource,
    Feature,
    FeatureProvenance,
    ImportApproval,
    ImportJob,
    ImportRow,
    Layer,
)
from app.pagination import clamp_limit, decode_cursor, encode_cursor
from app.schemas import (
    AdminFeatureRead,
    AdminImportRead,
    AdminImportRowRead,
    AdminLayerRead,
    AdminSourceRead,
    ImportApprovalSummary,
    ProvenanceRead,
)

APPROVAL_STATES = {
    "pending",
    "approved",
    "rejected",
    "expired",
    "stale",
    "executed",
    "failed",
}


def _uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Invalid cursor") from error


def _datetime(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail="Invalid cursor") from error


def _require_layer(session: Session, layer_id: uuid.UUID) -> Layer:
    layer = session.get(Layer, layer_id)
    if layer is None:
        raise HTTPException(status_code=404, detail="Layer not found")
    return layer


def _layer_read(layer: Layer, feature_count: int) -> AdminLayerRead:
    return AdminLayerRead(
        id=str(layer.id),
        slug=layer.slug,
        name=layer.name,
        description=layer.description,
        category=layer.category,
        mode=layer.mode,
        geometry_types=layer.geometry_types,
        enabled=layer.enabled,
        style=layer.style,
        metadata_=layer.metadata_,
        revision=layer.revision,
        data_updated_at=layer.data_updated_at,
        feature_count=feature_count,
        created_at=layer.created_at,
        updated_at=layer.updated_at,
    )


def _provenance_read(record: FeatureProvenance) -> ProvenanceRead:
    return ProvenanceRead(
        id=str(record.id),
        source_type=record.source_type,
        source_name=record.source_name,
        source_url=record.source_url,
        source_record_id=record.source_record_id,
        import_id=str(record.import_id) if record.import_id else None,
        created_by=record.created_by,
        confidence=record.confidence,
        observed_at=record.observed_at,
        imported_at=record.imported_at,
        verified_at=record.verified_at,
        metadata_=record.metadata_,
    )


def _feature_read(
    feature: Feature,
    geometry_json: str,
    provenance: list[ProvenanceRead] | None = None,
) -> AdminFeatureRead:
    return AdminFeatureRead(
        id=str(feature.id),
        layer_id=str(feature.layer_id),
        external_id=feature.external_id,
        geometry=json.loads(geometry_json),
        properties=feature.properties,
        status=feature.status,
        created_at=feature.created_at,
        updated_at=feature.updated_at,
        verified_at=feature.verified_at,
        archived_at=feature.archived_at,
        provenance=provenance or [],
    )


def _import_read(
    job: ImportJob, resolved: int = 0, unresolved: int = 0
) -> AdminImportRead:
    return AdminImportRead(
        id=str(job.id),
        layer_id=str(job.layer_id),
        filename=job.filename,
        format=job.format,
        status=job.status,
        row_count=job.row_count,
        valid_count=max(job.row_count - job.invalid_count, 0),
        invalid_count=job.invalid_count,
        candidate_count=job.candidate_count,
        resolved_candidate_count=resolved,
        unresolved_candidate_count=unresolved,
        csv_mapping=job.csv_mapping,
        csv_headers=job.csv_headers,
        mapping_version=job.mapping_version,
        source_name=job.source_name,
        source_url=job.source_url,
        created_at=job.created_at,
        committed_at=job.committed_at,
        cancelled_at=job.cancelled_at,
    )


def _resolution_counts(
    session: Session, import_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    if not import_ids:
        return {}
    candidate = func.jsonb_array_length(ImportRow.candidate_feature_ids) > 0
    statement = (
        select(
            ImportRow.import_id,
            func.count()
            .filter(candidate, ImportRow.resolution.is_not(None))
            .label("resolved"),
            func.count()
            .filter(candidate, ImportRow.resolution.is_(None))
            .label("unresolved"),
        )
        .where(ImportRow.import_id.in_(import_ids))
        .group_by(ImportRow.import_id)
    )
    return {
        row.import_id: (row.resolved, row.unresolved)
        for row in session.execute(statement)
    }


def import_row_read(row: ImportRow) -> AdminImportRowRead:
    return AdminImportRowRead(
        row_number=row.row_number,
        external_id=row.external_id,
        geometry=row.geometry,
        properties=row.properties,
        validation_error=row.validation_error,
        candidate_feature_ids=row.candidate_feature_ids,
        candidate_matches=row.candidate_matches,
        resolution=row.resolution,
        resolved_at=row.resolved_at,
    )


def _source_read(source: ExternalSource) -> AdminSourceRead:
    return AdminSourceRead(
        id=str(source.id),
        layer_id=str(source.layer_id),
        slug=source.slug,
        adapter=source.adapter,
        dataset_id=source.dataset_id,
        endpoint=source.endpoint,
        adapter_config=source.adapter_config,
        enabled=source.enabled,
        status=source.status,
        last_attempt_at=source.last_attempt_at,
        last_success_at=source.last_success_at,
        last_error=source.last_error,
    )


def list_admin_layers(
    session: Session, limit: int, cursor: str | None
) -> tuple[list[AdminLayerRead], str | None]:
    limit = clamp_limit(limit)
    after = decode_cursor(cursor, {"slug"})["slug"] if cursor else None
    statement = select(Layer, func.count(Feature.id)).outerjoin(
        Feature, (Feature.layer_id == Layer.id) & (Feature.archived_at.is_(None))
    )
    if after is not None:
        statement = statement.where(Layer.slug > after)
    statement = statement.group_by(Layer.id).order_by(Layer.slug).limit(limit + 1)
    rows = list(session.execute(statement))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor({"slug": rows[-1][0].slug})
    return [_layer_read(layer, count) for layer, count in rows], next_cursor


def get_admin_layer(session: Session, layer_id: uuid.UUID) -> AdminLayerRead:
    layer = _require_layer(session, layer_id)
    count = session.scalar(
        select(func.count(Feature.id)).where(
            Feature.layer_id == layer_id, Feature.archived_at.is_(None)
        )
    )
    return _layer_read(layer, count or 0)


def list_admin_features(
    session: Session,
    layer_id: uuid.UUID,
    limit: int,
    cursor: str | None,
    status: str | None,
) -> tuple[list[AdminFeatureRead], str | None]:
    _require_layer(session, layer_id)
    limit = clamp_limit(limit)
    after = decode_cursor(cursor, {"id"})["id"] if cursor else None
    statement = select(
        Feature, func.ST_AsGeoJSON(Feature.geometry).label("geometry_json")
    ).where(Feature.layer_id == layer_id)
    if status is not None:
        statement = statement.where(Feature.status == status)
    else:
        statement = statement.where(Feature.archived_at.is_(None))
    if after is not None:
        statement = statement.where(Feature.id > _uuid(after))
    statement = statement.order_by(Feature.id).limit(limit + 1)
    rows = list(session.execute(statement))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor({"id": str(rows[-1][0].id)})
    return [
        _feature_read(feature, geometry_json) for feature, geometry_json in rows
    ], next_cursor


def get_admin_feature(session: Session, feature_id: uuid.UUID) -> AdminFeatureRead:
    feature = session.get(Feature, feature_id)
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    geometry_json = session.scalar(
        select(func.ST_AsGeoJSON(Feature.geometry)).where(Feature.id == feature_id)
    )
    provenance = session.scalars(
        select(FeatureProvenance)
        .where(FeatureProvenance.feature_id == feature_id)
        .order_by(FeatureProvenance.imported_at, FeatureProvenance.id)
    ).all()
    return _feature_read(
        feature, geometry_json, [_provenance_read(record) for record in provenance]
    )


def list_admin_imports(
    session: Session, layer_id: uuid.UUID | None, limit: int, cursor: str | None
) -> tuple[list[AdminImportRead], str | None]:
    limit = clamp_limit(limit)
    statement = select(ImportJob)
    if layer_id is not None:
        statement = statement.where(ImportJob.layer_id == layer_id)
    if cursor:
        data = decode_cursor(cursor, {"created_at", "id"})
        statement = statement.where(
            tuple_(ImportJob.created_at, ImportJob.id)
            < (_datetime(data["created_at"]), _uuid(data["id"]))
        )
    statement = statement.order_by(
        ImportJob.created_at.desc(), ImportJob.id.desc()
    ).limit(limit + 1)
    rows = list(session.scalars(statement))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(
            {"created_at": last.created_at.isoformat(), "id": str(last.id)}
        )
    counts = _resolution_counts(session, [job.id for job in rows])
    return [_import_read(job, *counts.get(job.id, (0, 0))) for job in rows], next_cursor


def get_admin_import(session: Session, import_id: uuid.UUID) -> AdminImportRead:
    job = session.get(ImportJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    resolved, unresolved = _resolution_counts(session, [import_id]).get(
        import_id, (0, 0)
    )
    return _import_read(job, resolved, unresolved)


def list_admin_import_rows(
    session: Session,
    import_id: uuid.UUID,
    limit: int,
    cursor: str | None,
    state: str | None,
) -> tuple[list[AdminImportRowRead], str | None]:
    job = session.get(ImportJob, import_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import not found")
    limit = clamp_limit(limit)
    after = 0
    if cursor:
        value = decode_cursor(cursor, {"row_number"})["row_number"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise HTTPException(status_code=422, detail="Invalid cursor")
        after = value
    statement = select(ImportRow).where(
        ImportRow.import_id == import_id, ImportRow.row_number > after
    )
    if state == "invalid":
        statement = statement.where(ImportRow.validation_error.is_not(None))
    elif state == "candidate":
        statement = statement.where(
            ImportRow.validation_error.is_(None),
            func.jsonb_array_length(ImportRow.candidate_feature_ids) > 0,
        )
    elif state == "valid":
        statement = statement.where(
            ImportRow.validation_error.is_(None),
            func.jsonb_array_length(ImportRow.candidate_feature_ids) == 0,
        )
    elif state is not None:
        raise HTTPException(status_code=422, detail="Unknown row state")
    statement = statement.order_by(ImportRow.row_number).limit(limit + 1)
    rows = list(session.scalars(statement))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor({"row_number": rows[-1].row_number})
    return [import_row_read(row) for row in rows], next_cursor


def _expire_due(session: Session, approvals: list[ImportApproval]) -> None:
    now = datetime.now(UTC)
    changed = False
    for approval in approvals:
        if approval.state in ("pending", "approved") and approval.expires_at <= now:
            approval.state = "expired"
            changed = True
    if changed:
        session.commit()


def _approval_summary(approval: ImportApproval, layer: Layer) -> ImportApprovalSummary:
    snapshot = approval.snapshot or {}
    mapping = snapshot.get("mapping") or {}
    return ImportApprovalSummary(
        id=str(approval.id),
        import_id=str(approval.import_id),
        layer_id=str(layer.id),
        layer_name=layer.name,
        layer_slug=layer.slug,
        filename=snapshot.get("filename") or "",
        format=snapshot.get("format") or "",
        source_name=snapshot.get("source_name"),
        source_url=snapshot.get("source_url"),
        mapping_version=mapping.get("mapping_version") or "",
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
        fingerprint=approval.fingerprint,
        row_count=snapshot.get("row_count") or 0,
        valid_count=snapshot.get("valid_count") or 0,
        invalid_count=snapshot.get("invalid_count") or 0,
        candidate_count=snapshot.get("candidate_count") or 0,
        resolved_candidate_count=snapshot.get("resolved_candidate_count") or 0,
        unresolved_candidate_count=snapshot.get("unresolved_candidate_count") or 0,
    )


def list_admin_approvals(
    session: Session,
    state: str | None,
    import_id: uuid.UUID | None,
    limit: int,
    cursor: str | None,
) -> tuple[list[ImportApprovalSummary], str | None]:
    limit = clamp_limit(limit)
    state_filter = None
    if state == "active":
        state_filter = ImportApproval.state.in_(("pending", "approved"))
    elif state:
        if state not in APPROVAL_STATES:
            raise HTTPException(status_code=422, detail="Unknown approval state")
        state_filter = ImportApproval.state == state
    statement = (
        select(ImportApproval, Layer)
        .join(ImportJob, ImportJob.id == ImportApproval.import_id)
        .join(Layer, Layer.id == ImportJob.layer_id)
    )
    if import_id is not None:
        statement = statement.where(ImportApproval.import_id == import_id)
    if state_filter is not None:
        statement = statement.where(state_filter)
    if cursor:
        data = decode_cursor(cursor, {"requested_at", "id"})
        statement = statement.where(
            tuple_(ImportApproval.requested_at, ImportApproval.id)
            < (_datetime(data["requested_at"]), _uuid(data["id"]))
        )
    statement = statement.order_by(
        ImportApproval.requested_at.desc(), ImportApproval.id.desc()
    ).limit(limit + 1)
    rows = list(session.execute(statement))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1][0]
        next_cursor = encode_cursor(
            {"requested_at": last.requested_at.isoformat(), "id": str(last.id)}
        )
    _expire_due(session, [approval for approval, _ in rows])
    return [_approval_summary(approval, layer) for approval, layer in rows], next_cursor


def get_admin_approval(
    session: Session, approval_id: uuid.UUID
) -> ImportApprovalSummary:
    row = session.execute(
        select(ImportApproval, Layer)
        .join(ImportJob, ImportJob.id == ImportApproval.import_id)
        .join(Layer, Layer.id == ImportJob.layer_id)
        .where(ImportApproval.id == approval_id)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    _expire_due(session, [row[0]])
    return _approval_summary(row[0], row[1])


def list_admin_sources(
    session: Session, limit: int, cursor: str | None
) -> tuple[list[AdminSourceRead], str | None]:
    limit = clamp_limit(limit)
    after = decode_cursor(cursor, {"slug"})["slug"] if cursor else None
    statement = select(ExternalSource)
    if after is not None:
        statement = statement.where(ExternalSource.slug > after)
    statement = statement.order_by(ExternalSource.slug).limit(limit + 1)
    rows = list(session.scalars(statement))
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor({"slug": rows[-1].slug})
    return [_source_read(source) for source in rows], next_cursor


def get_admin_source(session: Session, source_id: uuid.UUID) -> AdminSourceRead:
    source = session.get(ExternalSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="External source not found")
    return _source_read(source)
