import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.gzip import GZipMiddleware

import app.aemet  # noqa: F401
import app.geojson_source  # noqa: F401
from app.admin import (
    get_admin_approval,
    get_admin_feature,
    get_admin_import,
    get_admin_layer,
    get_admin_source,
    import_row_read,
    list_admin_approvals,
    list_admin_features,
    list_admin_import_rows,
    list_admin_imports,
    list_admin_layers,
    list_admin_sources,
)
from app.agent_sources import preflight
from app.database import get_session, is_ready
from app.imports import (
    cancel_import,
    create_approval_request,
    decide_approval,
    execute_approved_import,
    resolve_import_row,
    stage_import,
)
from app.layers import (
    DEFAULT_PRECISION,
    MAX_PRECISION,
    MAX_SIMPLIFY_DEGREES,
    get_layer_features_page,
    get_layer_geojson,
    list_compatibility_layers,
    list_layers,
)
from app.lifecycle import (
    archive_feature,
    cascade_delete_layer,
    delete_empty_layer,
    disable_layer,
    disable_source,
    enable_layer,
    enable_source,
    hard_delete_feature,
    record_event,
    restore_feature,
)
from app.managed import (
    create_feature,
    create_layer,
    patch_feature,
    update_layer,
)
from app.models import ExternalSource, Layer
from app.pagination import DEFAULT_LIMIT
from app.schemas import (
    AdminFeature,
    AdminFeatureRead,
    AdminImportRead,
    AdminImportRowRead,
    AdminLayer,
    AdminLayerRead,
    AdminSourceRead,
    AgentSourceCreate,
    AgentSourceProposal,
    AgentSourceSync,
    AgentSourceValidation,
    ApprovalDecision,
    CascadeLayerDelete,
    CompatibilityLayer,
    CompatibilityLayersResponse,
    EmptyLayerDelete,
    ExternalFeatureDelete,
    ExternalSourceSummary,
    FeaturePatch,
    FeatureWrite,
    GeoJSONFeatureCollection,
    GeoJSONFeatureCollectionPage,
    ImportApprovalRead,
    ImportApprovalSummary,
    ImportCommit,
    ImportCreate,
    ImportRowResolution,
    ImportSummary,
    LayerCreate,
    LayerSummary,
    LayerUpdate,
    Page,
    PointGeometry,
    StaticFeature,
    StaticFeatureCollection,
    StaticFeatureProperties,
)
from app.security import (
    ADMIN,
    PUBLISH,
    READ,
    STAGE,
    require_actor,
    require_approver,
    require_scope,
)
from app.sources import sync_source, sync_source_report

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

TEST_LAYER = CompatibilityLayer(
    id="test",
    name="Test Layer",
    description="Static validation layer",
    endpoint="/layers/test",
)

TEST_FEATURES = [
    StaticFeature(
        geometry=PointGeometry(type="Point", coordinates=(-3.7038, 40.4168)),
        properties=StaticFeatureProperties(
            id="test-1",
            name="Madrid test point",
            source="local",
            category="test",
            status="online",
        ),
    ),
    StaticFeature(
        geometry=PointGeometry(type="Point", coordinates=(2.1734, 41.3851)),
        properties=StaticFeatureProperties(
            id="test-2",
            name="Barcelona test point",
            source="local",
            category="test",
            status="online",
        ),
    ),
    StaticFeature(
        geometry=PointGeometry(type="Point", coordinates=(-0.3763, 39.4699)),
        properties=StaticFeatureProperties(
            id="test-3",
            name="Valencia test point",
            source="local",
            category="test",
            status="online",
        ),
    ),
]


def _source_summary(source: ExternalSource) -> ExternalSourceSummary:
    return ExternalSourceSummary(
        id=str(source.id),
        layer_id=str(source.layer_id),
        slug=source.slug,
        adapter=source.adapter,
        dataset_id=source.dataset_id,
        adapter_config=source.adapter_config,
        enabled=source.enabled,
        status=source.status,
        last_attempt_at=source.last_attempt_at,
        last_success_at=source.last_success_at,
        last_error=source.last_error,
        agent_managed=source.agent_managed,
    )


origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]

app = FastAPI(title="OSIRIS Geo API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=[],
)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    if not is_ready():
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok"}


@app.get("/api/v1/layers", response_model=list[LayerSummary])
def public_layers(session: Session = Depends(get_session)) -> list[LayerSummary]:
    try:
        return list_layers(session)
    except SQLAlchemyError as error:
        logger.exception("Could not list persisted layers")
        raise HTTPException(status_code=503, detail="Database unavailable") from error


@app.get("/api/v1/layers/{slug}", response_model=GeoJSONFeatureCollection)
def public_layer(
    slug: str, session: Session = Depends(get_session)
) -> GeoJSONFeatureCollection:
    try:
        return get_layer_geojson(session, slug)
    except SQLAlchemyError as error:
        logger.exception("Could not load persisted layer", extra={"layer": slug})
        raise HTTPException(status_code=503, detail="Database unavailable") from error


@app.get("/api/v1/layers/{slug}/features", response_model=GeoJSONFeatureCollectionPage)
def public_layer_features(
    slug: str,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    bbox: str | None = None,
    updated_since: datetime | None = None,
    precision: int = Query(DEFAULT_PRECISION, ge=0, le=MAX_PRECISION),
    simplify: float = Query(0.0, ge=0.0, le=MAX_SIMPLIFY_DEGREES),
    session: Session = Depends(get_session),
) -> GeoJSONFeatureCollectionPage:
    return get_layer_features_page(
        session, slug, limit, cursor, bbox, updated_since, precision, simplify
    )


@app.post(
    "/api/v1/admin/layers",
    response_model=AdminLayer,
    dependencies=[Depends(require_scope(STAGE))],
)
def admin_create_layer(
    payload: LayerCreate, session: Session = Depends(get_session)
) -> AdminLayer:
    layer = create_layer(session, payload)
    return AdminLayer(
        id=str(layer.id), slug=layer.slug, name=layer.name, mode=layer.mode
    )


@app.patch(
    "/api/v1/admin/layers/{layer_id}",
    response_model=AdminLayer,
    dependencies=[Depends(require_scope(STAGE))],
)
def admin_update_layer(
    layer_id: uuid.UUID, payload: LayerUpdate, session: Session = Depends(get_session)
) -> AdminLayer:
    layer = update_layer(session, layer_id, payload)
    return AdminLayer(
        id=str(layer.id), slug=layer.slug, name=layer.name, mode=layer.mode
    )


@app.post(
    "/api/v1/admin/layers/{layer_id}/features",
    response_model=AdminFeature,
    dependencies=[Depends(require_scope(STAGE))],
)
def admin_create_feature(
    layer_id: uuid.UUID, payload: FeatureWrite, session: Session = Depends(get_session)
) -> AdminFeature:
    feature = create_feature(session, layer_id, payload)
    return AdminFeature(
        id=str(feature.id), layer_id=str(feature.layer_id), status=feature.status
    )


@app.patch(
    "/api/v1/admin/features/{feature_id}",
    response_model=AdminFeature,
    dependencies=[Depends(require_scope(STAGE))],
)
def admin_update_feature(
    feature_id: uuid.UUID,
    payload: FeaturePatch,
    session: Session = Depends(get_session),
) -> AdminFeature:
    feature = patch_feature(session, feature_id, payload)
    return AdminFeature(
        id=str(feature.id), layer_id=str(feature.layer_id), status=feature.status
    )


@app.delete(
    "/api/v1/admin/features/{feature_id}", dependencies=[Depends(require_scope(ADMIN))]
)
def admin_archive_feature(
    feature_id: uuid.UUID,
    actor: str = Depends(require_actor(ADMIN)),
    session: Session = Depends(get_session),
) -> None:
    archive_feature(session, feature_id, actor, managed_only=True)


@app.post(
    "/api/v1/admin/features/{feature_id}/archive",
    response_model=AdminFeature,
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_lifecycle_archive_feature(
    feature_id: uuid.UUID,
    actor: str = Depends(require_actor(ADMIN)),
    session: Session = Depends(get_session),
) -> AdminFeature:
    feature = archive_feature(session, feature_id, actor)
    return AdminFeature(
        id=str(feature.id), layer_id=str(feature.layer_id), status=feature.status
    )


@app.post(
    "/api/v1/admin/features/{feature_id}/restore",
    response_model=AdminFeature,
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_restore_feature(
    feature_id: uuid.UUID,
    actor: str = Depends(require_actor(ADMIN)),
    session: Session = Depends(get_session),
) -> AdminFeature:
    feature = restore_feature(session, feature_id, actor)
    return AdminFeature(
        id=str(feature.id), layer_id=str(feature.layer_id), status=feature.status
    )


@app.post(
    "/api/v1/admin/features/{feature_id}/hard-delete",
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_hard_delete_feature(
    feature_id: uuid.UUID,
    payload: ExternalFeatureDelete,
    actor: str = Depends(require_actor(ADMIN)),
    session: Session = Depends(get_session),
) -> None:
    hard_delete_feature(
        session,
        feature_id,
        actor,
        confirm_recreated_on_sync=payload.confirm_recreated_on_sync,
    )


@app.post(
    "/api/v1/admin/layers/{layer_id}/disable",
    response_model=AdminLayer,
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_disable_layer(
    layer_id: uuid.UUID,
    actor: str = Depends(require_actor(ADMIN)),
    session: Session = Depends(get_session),
) -> AdminLayer:
    layer = disable_layer(session, layer_id, actor)
    return AdminLayer(
        id=str(layer.id), slug=layer.slug, name=layer.name, mode=layer.mode
    )


@app.post(
    "/api/v1/admin/layers/{layer_id}/enable",
    response_model=AdminLayer,
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_enable_layer(
    layer_id: uuid.UUID,
    actor: str = Depends(require_actor(ADMIN)),
    session: Session = Depends(get_session),
) -> AdminLayer:
    layer = enable_layer(session, layer_id, actor)
    return AdminLayer(
        id=str(layer.id), slug=layer.slug, name=layer.name, mode=layer.mode
    )


@app.delete(
    "/api/v1/admin/layers/{layer_id}",
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_delete_empty_layer(
    layer_id: uuid.UUID,
    payload: EmptyLayerDelete,
    actor: str = Depends(require_actor(ADMIN)),
    session: Session = Depends(get_session),
) -> None:
    delete_empty_layer(session, layer_id, actor, payload.confirmation)


@app.post(
    "/api/v1/admin/layers/{layer_id}/cascade-delete",
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_cascade_delete_layer(
    layer_id: uuid.UUID,
    payload: CascadeLayerDelete,
    actor: str = Depends(require_actor(ADMIN)),
    session: Session = Depends(get_session),
) -> None:
    cascade_delete_layer(session, layer_id, actor, payload.confirmation)


@app.post(
    "/api/v1/admin/sources/{source_id}/disable",
    response_model=ExternalSourceSummary,
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_disable_source(
    source_id: uuid.UUID,
    actor: str = Depends(require_actor(ADMIN)),
    session: Session = Depends(get_session),
) -> ExternalSourceSummary:
    source = disable_source(session, source_id, actor)
    return _source_summary(source)


@app.post(
    "/api/v1/admin/sources/{source_id}/enable",
    response_model=ExternalSourceSummary,
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_enable_source(
    source_id: uuid.UUID,
    actor: str = Depends(require_actor(ADMIN)),
    session: Session = Depends(get_session),
) -> ExternalSourceSummary:
    source = enable_source(session, source_id, actor)
    return _source_summary(source)


@app.post(
    "/api/v1/admin/imports",
    response_model=ImportSummary,
    dependencies=[Depends(require_scope(STAGE))],
)
def admin_stage_import(
    payload: ImportCreate, session: Session = Depends(get_session)
) -> ImportSummary:
    return stage_import(session, payload)


@app.get(
    "/api/v1/admin/layers",
    response_model=Page[AdminLayerRead],
    dependencies=[Depends(require_scope(READ))],
)
def admin_list_layers(
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    session: Session = Depends(get_session),
) -> Page[AdminLayerRead]:
    items, next_cursor = list_admin_layers(session, limit, cursor)
    return Page[AdminLayerRead](items=items, next_cursor=next_cursor)


@app.get(
    "/api/v1/admin/layers/{layer_id}",
    response_model=AdminLayerRead,
    dependencies=[Depends(require_scope(READ))],
)
def admin_get_layer(
    layer_id: uuid.UUID, session: Session = Depends(get_session)
) -> AdminLayerRead:
    return get_admin_layer(session, layer_id)


@app.get(
    "/api/v1/admin/layers/{layer_id}/features",
    response_model=Page[AdminFeatureRead],
    dependencies=[Depends(require_scope(READ))],
)
def admin_list_features(
    layer_id: uuid.UUID,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
) -> Page[AdminFeatureRead]:
    items, next_cursor = list_admin_features(session, layer_id, limit, cursor, status)
    return Page[AdminFeatureRead](items=items, next_cursor=next_cursor)


@app.get(
    "/api/v1/admin/features/{feature_id}",
    response_model=AdminFeatureRead,
    dependencies=[Depends(require_scope(READ))],
)
def admin_get_feature(
    feature_id: uuid.UUID, session: Session = Depends(get_session)
) -> AdminFeatureRead:
    return get_admin_feature(session, feature_id)


@app.get(
    "/api/v1/admin/imports",
    response_model=Page[AdminImportRead],
    dependencies=[Depends(require_scope(READ))],
)
def admin_list_imports(
    layer_id: uuid.UUID | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    session: Session = Depends(get_session),
) -> Page[AdminImportRead]:
    items, next_cursor = list_admin_imports(session, layer_id, limit, cursor)
    return Page[AdminImportRead](items=items, next_cursor=next_cursor)


@app.get(
    "/api/v1/admin/imports/{import_id}",
    response_model=AdminImportRead,
    dependencies=[Depends(require_scope(READ))],
)
def admin_get_import(
    import_id: uuid.UUID, session: Session = Depends(get_session)
) -> AdminImportRead:
    return get_admin_import(session, import_id)


@app.get(
    "/api/v1/admin/imports/{import_id}/rows",
    response_model=Page[AdminImportRowRead],
    dependencies=[Depends(require_scope(READ))],
)
def admin_list_import_rows(
    import_id: uuid.UUID,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    state: str | None = None,
    session: Session = Depends(get_session),
) -> Page[AdminImportRowRead]:
    items, next_cursor = list_admin_import_rows(
        session, import_id, limit, cursor, state
    )
    return Page[AdminImportRowRead](items=items, next_cursor=next_cursor)


@app.post(
    "/api/v1/admin/imports/{import_id}/rows/{row_number}/resolution",
    response_model=AdminImportRowRead,
    dependencies=[Depends(require_scope(STAGE))],
)
def admin_resolve_import_row(
    import_id: uuid.UUID,
    row_number: int,
    payload: ImportRowResolution,
    session: Session = Depends(get_session),
) -> AdminImportRowRead:
    return import_row_read(resolve_import_row(session, import_id, row_number, payload))


@app.post(
    "/api/v1/admin/imports/{import_id}/approval-request",
    response_model=ImportApprovalRead,
)
def admin_create_approval_request(
    import_id: uuid.UUID,
    payload: ImportCommit,
    actor: str = Depends(require_actor(STAGE)),
    session: Session = Depends(get_session),
) -> ImportApprovalRead:
    return create_approval_request(session, import_id, payload, actor)


@app.post(
    "/api/v1/admin/imports/{import_id}/approval",
    response_model=ImportApprovalRead,
)
def admin_decide_approval(
    import_id: uuid.UUID,
    payload: ApprovalDecision,
    actor: str = Depends(require_approver()),
    session: Session = Depends(get_session),
) -> ImportApprovalRead:
    return decide_approval(session, import_id, payload, actor)


@app.get(
    "/api/v1/admin/approvals",
    response_model=Page[ImportApprovalSummary],
    dependencies=[Depends(require_scope(READ))],
)
def admin_list_approvals(
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    state: str | None = None,
    import_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
) -> Page[ImportApprovalSummary]:
    items, next_cursor = list_admin_approvals(session, state, import_id, limit, cursor)
    return Page[ImportApprovalSummary](items=items, next_cursor=next_cursor)


@app.get(
    "/api/v1/admin/approvals/{approval_id}",
    response_model=ImportApprovalSummary,
    dependencies=[Depends(require_scope(READ))],
)
def admin_get_approval(
    approval_id: uuid.UUID, session: Session = Depends(get_session)
) -> ImportApprovalSummary:
    return get_admin_approval(session, approval_id)


@app.get(
    "/api/v1/admin/sources",
    response_model=Page[AdminSourceRead],
    dependencies=[Depends(require_scope(READ))],
)
def admin_list_sources(
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    session: Session = Depends(get_session),
) -> Page[AdminSourceRead]:
    items, next_cursor = list_admin_sources(session, limit, cursor)
    return Page[AdminSourceRead](items=items, next_cursor=next_cursor)


@app.get(
    "/api/v1/admin/sources/{source_id}",
    response_model=AdminSourceRead,
    dependencies=[Depends(require_scope(READ))],
)
def admin_get_source(
    source_id: uuid.UUID, session: Session = Depends(get_session)
) -> AdminSourceRead:
    return get_admin_source(session, source_id)


def _agent_validation(proposal: AgentSourceProposal) -> AgentSourceValidation:
    try:
        result = preflight(proposal.model_dump(exclude_none=True))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return AgentSourceValidation(
        proposal=result.proposal,
        summary=result.summary,
        warnings=result.warnings,
        fingerprint=result.fingerprint,
    )


@app.post(
    "/api/v1/admin/agent/sources/validate",
    response_model=AgentSourceValidation,
    dependencies=[Depends(require_scope(STAGE))],
)
def agent_validate_source(proposal: AgentSourceProposal) -> AgentSourceValidation:
    return _agent_validation(proposal)


@app.post(
    "/api/v1/admin/agent/sources",
    response_model=ExternalSourceSummary,
    status_code=201,
    dependencies=[Depends(require_scope(STAGE))],
)
def agent_create_source(
    payload: AgentSourceCreate,
    actor: str = Depends(require_actor(STAGE)),
    session: Session = Depends(get_session),
) -> ExternalSourceSummary:
    validation = _agent_validation(payload.proposal)
    if validation.fingerprint != payload.fingerprint:
        raise HTTPException(
            status_code=409, detail="Source dataset changed; fingerprint is stale"
        )
    proposal = validation.proposal
    if session.scalar(select(Layer).where(Layer.slug == proposal.slug)) is not None:
        raise HTTPException(status_code=409, detail="Layer slug already exists")
    if (
        session.scalar(
            select(ExternalSource).where(ExternalSource.slug == proposal.slug)
        )
        is not None
    ):
        raise HTTPException(status_code=409, detail="Source slug already exists")
    layer = Layer(
        slug=proposal.slug,
        name=proposal.name,
        description=proposal.description,
        category=proposal.category,
        mode="external",
        geometry_types=proposal.geometry_types,
        enabled=False,
        metadata_={
            "agent_managed": True,
            **({"attribution": proposal.attribution} if proposal.attribution else {}),
            **({"license": proposal.license} if proposal.license else {}),
        },
    )
    source = ExternalSource(
        layer=layer,
        slug=proposal.slug,
        adapter="geojson",
        dataset_id=proposal.dataset_id,
        endpoint=proposal.endpoint,
        adapter_config={
            "id_property": proposal.id_property,
            "properties": proposal.properties,
            "timeout_seconds": proposal.timeout_seconds,
            "pagination": proposal.pagination,
            "fingerprint": validation.fingerprint,
        },
        enabled=False,
        agent_managed=True,
    )
    session.add_all([layer, source])
    try:
        session.flush()
        record_event(
            session,
            entity_type="source",
            entity_id=source.id,
            action="agent_source_created",
            actor=actor,
            previous_state={},
            resulting_state={
                "source_id": str(source.id),
                "layer_id": str(layer.id),
                "enabled": False,
            },
            metadata={"fingerprint": validation.fingerprint},
        )
        session.commit()
    except Exception as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Could not create agent source"
        ) from error
    return _source_summary(source)


@app.post(
    "/api/v1/admin/agent/sources/{source_id}/sync",
    response_model=AgentSourceSync,
    dependencies=[Depends(require_scope(STAGE))],
)
def agent_sync_source(
    source_id: uuid.UUID,
    actor: str = Depends(require_actor(STAGE)),
    session: Session = Depends(get_session),
) -> AgentSourceSync:
    source = session.scalar(
        select(ExternalSource).where(ExternalSource.id == source_id)
    )
    if source is None:
        raise HTTPException(status_code=404, detail="External source not found")
    if not source.agent_managed or source.adapter != "geojson":
        raise HTTPException(status_code=403, detail="Source is not agent-managed")
    if not source.enabled:
        raise HTTPException(status_code=409, detail="External source is disabled")
    now = datetime.now(UTC)
    if source.last_attempt_at and now - source.last_attempt_at < timedelta(seconds=60):
        raise HTTPException(
            status_code=429,
            detail="Agent source sync must be at least 60 seconds apart",
        )
    started = time.monotonic()
    attempted_at = now
    source, counts = sync_source_report(session, source_id)
    completed_at = datetime.now(UTC)
    record_event(
        session,
        entity_type="source",
        entity_id=source.id,
        action="agent_source_sync",
        actor=actor,
        previous_state={"status": source.status},
        resulting_state={"status": source.status, **counts},
        metadata={"layer_id": str(source.layer_id)},
    )
    session.commit()
    return AgentSourceSync(
        source_id=str(source.id),
        source_slug=source.slug,
        layer_id=str(source.layer_id),
        layer_slug=source.layer.slug,
        status=source.status,
        **counts,
        duration_ms=int((time.monotonic() - started) * 1000),
        attempted_at=attempted_at,
        completed_at=completed_at,
        error=source.last_error,
    )


@app.post(
    "/api/v1/admin/imports/{import_id}/commit",
    response_model=AdminImportRead,
    dependencies=[Depends(require_scope(PUBLISH))],
)
def admin_commit_import(
    import_id: uuid.UUID,
    payload: ImportCommit,
    actor: str = Depends(require_actor(PUBLISH)),
    session: Session = Depends(get_session),
) -> AdminImportRead:
    execute_approved_import(session, import_id, payload, actor)
    return get_admin_import(session, import_id)


@app.delete(
    "/api/v1/admin/imports/{import_id}",
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_cancel_import(
    import_id: uuid.UUID, session: Session = Depends(get_session)
) -> None:
    cancel_import(session, import_id)


@app.post(
    "/api/v1/admin/sources/{source_id}/sync",
    response_model=ExternalSourceSummary,
    dependencies=[Depends(require_scope(ADMIN))],
)
def admin_sync_source(
    source_id: uuid.UUID, session: Session = Depends(get_session)
) -> ExternalSourceSummary:
    source = sync_source(session, source_id)
    return _source_summary(source)


@app.get("/layers", response_model=CompatibilityLayersResponse)
def layers(session: Session = Depends(get_session)) -> CompatibilityLayersResponse:
    try:
        persisted = [
            CompatibilityLayer(
                id=layer.slug,
                name=layer.name,
                description="" if layer.description is None else layer.description,
                endpoint=f"/layers/{layer.slug}",
                revision=layer.revision,
                data_updated_at=layer.data_updated_at,
            )
            for layer in list_compatibility_layers(session)
        ]
    except SQLAlchemyError:
        logger.exception("Could not list persisted compatibility layers")
        persisted = []
    return CompatibilityLayersResponse(layers=[TEST_LAYER, *persisted])


@app.get("/layers/test", response_model=StaticFeatureCollection)
def test_layer() -> StaticFeatureCollection:
    return StaticFeatureCollection(features=TEST_FEATURES)


@app.get("/layers/{slug}", response_model=GeoJSONFeatureCollection)
def compatibility_layer(
    slug: str, session: Session = Depends(get_session)
) -> GeoJSONFeatureCollection:
    return public_layer(slug, session)
