"""Explicit, audited lifecycle operations for admin-managed data."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.freshness import touch_layer_data
from app.models import (
    ExternalSource,
    Feature,
    FeatureProvenance,
    ImportApproval,
    ImportJob,
    ImportRow,
    Layer,
    LifecycleEvent,
)

MANUAL = "manual"
MANAGED_IMPORTED = "managed/imported"
EXTERNAL = "external"
MIXED = "mixed"


@dataclass(frozen=True)
class FeatureOwnership:
    kind: str
    source_slug: str | None = None
    source_record_id: str | None = None


def classify_feature(feature: Feature) -> FeatureOwnership:
    provenance = feature.provenance_records
    external = [record for record in provenance if record.source_type == "external"]
    non_external = [record for record in provenance if record.source_type != "external"]
    source_slugs = {record.source_name for record in external}
    if external and (non_external or len(source_slugs) != 1):
        return FeatureOwnership(MIXED)
    if external:
        record = external[-1]
        return FeatureOwnership(EXTERNAL, record.source_name, record.source_record_id)
    if any(record.source_type in {"import", "agent"} for record in provenance):
        return FeatureOwnership(MANAGED_IMPORTED)
    return FeatureOwnership(MANUAL)


def feature_lifecycle_info(feature: Feature) -> dict:
    ownership = classify_feature(feature)
    source = None
    warning = None
    if ownership.kind == EXTERNAL:
        source = {
            "slug": ownership.source_slug,
            "record_id": ownership.source_record_id,
        }
        warning = "The next successful source sync may recreate this feature."
    return {
        "ownership": ownership.kind,
        "source": source,
        "deletion_warning": warning,
    }


def record_event(
    session: Session,
    *,
    entity_type: str,
    entity_id: uuid.UUID | None,
    action: str,
    actor: str,
    previous_state: dict,
    resulting_state: dict,
    metadata: dict | None = None,
) -> None:
    session.add(
        LifecycleEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            previous_state=previous_state,
            resulting_state=resulting_state,
            metadata_=metadata or {},
        )
    )


def _feature(session: Session, feature_id: uuid.UUID) -> Feature:
    feature = session.scalar(
        select(Feature)
        .where(Feature.id == feature_id)
        .options(selectinload(Feature.provenance_records))
    )
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    return feature


def _feature_state(feature: Feature) -> dict:
    return {
        "status": feature.status,
        "archived_at": feature.archived_at.isoformat()
        if feature.archived_at is not None
        else None,
        **feature_lifecycle_info(feature),
    }


def _reject_mixed(feature: Feature) -> FeatureOwnership:
    ownership = classify_feature(feature)
    if ownership.kind == MIXED:
        raise HTTPException(
            status_code=409,
            detail="Feature has mixed provenance ownership and requires manual review",
        )
    return ownership


def archive_feature(
    session: Session, feature_id: uuid.UUID, actor: str, *, managed_only: bool = False
) -> Feature:
    feature = _feature(session, feature_id)
    if managed_only and feature.layer.mode != "managed":
        raise HTTPException(status_code=404, detail="Managed feature not found")
    ownership = _reject_mixed(feature)
    if feature.status == "archived":
        raise HTTPException(status_code=409, detail="Feature is already archived")
    previous = _feature_state(feature)
    was_published = feature.status == "published"
    feature.status = "archived"
    feature.archived_at = datetime.now(UTC)
    if was_published:
        touch_layer_data(session, feature.layer_id)
    record_event(
        session,
        entity_type="feature",
        entity_id=feature.id,
        action="archive",
        actor=actor,
        previous_state=previous,
        resulting_state=_feature_state(feature),
        metadata={"ownership": ownership.kind},
    )
    session.commit()
    return feature


def restore_feature(session: Session, feature_id: uuid.UUID, actor: str) -> Feature:
    feature = _feature(session, feature_id)
    ownership = _reject_mixed(feature)
    if feature.status != "archived" or feature.archived_at is None:
        raise HTTPException(status_code=409, detail="Feature is not archived")
    previous = _feature_state(feature)
    feature.status = "published"
    feature.archived_at = None
    touch_layer_data(session, feature.layer_id)
    record_event(
        session,
        entity_type="feature",
        entity_id=feature.id,
        action="restore",
        actor=actor,
        previous_state=previous,
        resulting_state=_feature_state(feature),
        metadata={"ownership": ownership.kind},
    )
    session.commit()
    return feature


def _has_active_approval(session: Session, layer_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(ImportApproval.id)
            .join(ImportJob, ImportJob.id == ImportApproval.import_id)
            .where(
                ImportJob.layer_id == layer_id,
                ImportApproval.state.in_(("pending", "approved")),
            )
        )
        is not None
    )


def hard_delete_feature(
    session: Session,
    feature_id: uuid.UUID,
    actor: str,
    *,
    confirm_recreated_on_sync: bool = False,
) -> None:
    feature = _feature(session, feature_id)
    ownership = _reject_mixed(feature)
    if ownership.kind == EXTERNAL and not confirm_recreated_on_sync:
        raise HTTPException(
            status_code=409,
            detail="External feature deletion requires confirm_recreated_on_sync=true",
        )
    if _has_active_approval(session, feature.layer_id):
        raise HTTPException(
            status_code=409, detail="Layer has an active import approval"
        )
    for provenance in feature.provenance_records:
        if (
            provenance.import_id
            and session.scalar(
                select(ImportJob.status).where(ImportJob.id == provenance.import_id)
            )
            == "validated"
        ):
            raise HTTPException(
                status_code=409, detail="Feature belongs to a pending import"
            )

    previous = _feature_state(feature)
    if feature.status == "published":
        touch_layer_data(session, feature.layer_id)
    session.execute(
        delete(FeatureProvenance).where(FeatureProvenance.feature_id == feature.id)
    )
    session.execute(delete(Feature).where(Feature.id == feature.id))
    record_event(
        session,
        entity_type="feature",
        entity_id=feature.id,
        action="hard_delete",
        actor=actor,
        previous_state=previous,
        resulting_state={"deleted": True},
        metadata={
            "ownership": ownership.kind,
            "confirm_recreated_on_sync": confirm_recreated_on_sync,
        },
    )
    session.commit()


def _layer(session: Session, layer_id: uuid.UUID) -> Layer:
    layer = session.get(Layer, layer_id)
    if layer is None:
        raise HTTPException(status_code=404, detail="Layer not found")
    return layer


def _layer_state(layer: Layer) -> dict:
    return {"enabled": layer.enabled, "mode": layer.mode, "slug": layer.slug}


def disable_layer(session: Session, layer_id: uuid.UUID, actor: str) -> Layer:
    layer = _layer(session, layer_id)
    if not layer.enabled:
        raise HTTPException(status_code=409, detail="Layer is already disabled")
    previous = _layer_state(layer)
    layer.enabled = False
    record_event(
        session,
        entity_type="layer",
        entity_id=layer.id,
        action="disable",
        actor=actor,
        previous_state=previous,
        resulting_state=_layer_state(layer),
    )
    session.commit()
    return layer


def enable_layer(session: Session, layer_id: uuid.UUID, actor: str) -> Layer:
    layer = _layer(session, layer_id)
    if layer.enabled:
        raise HTTPException(status_code=409, detail="Layer is already enabled")
    previous = _layer_state(layer)
    layer.enabled = True
    record_event(
        session,
        entity_type="layer",
        entity_id=layer.id,
        action="enable",
        actor=actor,
        previous_state=previous,
        resulting_state=_layer_state(layer),
    )
    session.commit()
    return layer


def _disposable(layer: Layer) -> bool:
    lifecycle = (
        layer.metadata_.get("lifecycle") if isinstance(layer.metadata_, dict) else None
    )
    return (
        layer.mode == "managed"
        and layer.category == "TEST"
        and isinstance(lifecycle, dict)
        and lifecycle.get("disposable") is True
    )


def _layer_dependencies(session: Session, layer_id: uuid.UUID) -> dict[str, int]:
    return {
        "features": session.scalar(
            select(func.count())
            .select_from(Feature)
            .where(Feature.layer_id == layer_id)
        )
        or 0,
        "imports": session.scalar(
            select(func.count())
            .select_from(ImportJob)
            .where(ImportJob.layer_id == layer_id)
        )
        or 0,
        "approvals": session.scalar(
            select(func.count())
            .select_from(ImportApproval)
            .join(ImportJob, ImportJob.id == ImportApproval.import_id)
            .where(ImportJob.layer_id == layer_id)
        )
        or 0,
        "sources": session.scalar(
            select(func.count())
            .select_from(ExternalSource)
            .where(ExternalSource.layer_id == layer_id)
        )
        or 0,
    }


def delete_empty_layer(
    session: Session, layer_id: uuid.UUID, actor: str, confirmation: str
) -> None:
    layer = _layer(session, layer_id)
    if confirmation != "DELETE EMPTY LAYER":
        raise HTTPException(
            status_code=409, detail="Explicit layer confirmation required"
        )
    dependencies = _layer_dependencies(session, layer.id)
    if layer.enabled:
        raise HTTPException(status_code=409, detail="Disable layer before deletion")
    if not _disposable(layer):
        raise HTTPException(status_code=409, detail="Layer is not marked disposable")
    if any(dependencies.values()):
        raise HTTPException(
            status_code=409,
            detail=f"Layer has dependencies: {dependencies}",
        )
    record_event(
        session,
        entity_type="layer",
        entity_id=layer.id,
        action="delete",
        actor=actor,
        previous_state={**_layer_state(layer), **dependencies},
        resulting_state={"deleted": True},
        metadata={"cascade": False},
    )
    session.delete(layer)
    session.commit()


def cascade_delete_layer(
    session: Session, layer_id: uuid.UUID, actor: str, confirmation: str
) -> None:
    layer = _layer(session, layer_id)
    if confirmation != "DELETE DISPOSABLE LAYER":
        raise HTTPException(
            status_code=409, detail="Strong layer confirmation required"
        )
    dependencies = _layer_dependencies(session, layer.id)
    if layer.enabled:
        raise HTTPException(status_code=409, detail="Disable layer before deletion")
    if not _disposable(layer):
        raise HTTPException(status_code=409, detail="Layer is not marked disposable")
    source_count = dependencies.pop("sources")
    if source_count:
        raise HTTPException(
            status_code=409, detail="Disposable layer cannot have a source"
        )
    if _has_active_approval(session, layer.id):
        raise HTTPException(
            status_code=409, detail="Layer has an active import approval"
        )

    feature_ids = select(Feature.id).where(Feature.layer_id == layer.id)
    import_ids = select(ImportJob.id).where(ImportJob.layer_id == layer.id)
    session.execute(
        delete(FeatureProvenance).where(FeatureProvenance.feature_id.in_(feature_ids))
    )
    session.execute(delete(Feature).where(Feature.layer_id == layer.id))
    session.execute(
        delete(ImportApproval).where(ImportApproval.import_id.in_(import_ids))
    )
    session.execute(delete(ImportRow).where(ImportRow.import_id.in_(import_ids)))
    session.execute(delete(ImportJob).where(ImportJob.layer_id == layer.id))
    record_event(
        session,
        entity_type="layer",
        entity_id=layer.id,
        action="cascade_delete",
        actor=actor,
        previous_state={**_layer_state(layer), **dependencies, "sources": source_count},
        resulting_state={"deleted": True},
        metadata={"cascade": True},
    )
    session.delete(layer)
    session.commit()


def disable_source(
    session: Session, source_id: uuid.UUID, actor: str
) -> ExternalSource:
    source = session.get(ExternalSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="External source not found")
    if not source.enabled:
        raise HTTPException(
            status_code=409, detail="External source is already disabled"
        )
    previous = {"enabled": source.enabled, "status": source.status}
    source.enabled = False
    record_event(
        session,
        entity_type="source",
        entity_id=source.id,
        action="disable",
        actor=actor,
        previous_state=previous,
        resulting_state={"enabled": source.enabled, "status": source.status},
    )
    session.commit()
    return source


def enable_source(session: Session, source_id: uuid.UUID, actor: str) -> ExternalSource:
    source = session.get(ExternalSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="External source not found")
    if source.enabled:
        raise HTTPException(
            status_code=409, detail="External source is already enabled"
        )
    previous = {"enabled": source.enabled, "status": source.status}
    source.enabled = True
    record_event(
        session,
        entity_type="source",
        entity_id=source.id,
        action="enable",
        actor=actor,
        previous_state=previous,
        resulting_state={"enabled": source.enabled, "status": source.status},
    )
    session.commit()
    return source
