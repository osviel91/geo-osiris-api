import logging
import os
import uuid
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.aemet  # noqa: F401
from app.admin import (
    get_admin_feature,
    get_admin_import,
    get_admin_layer,
    get_admin_source,
    import_row_read,
    list_admin_features,
    list_admin_import_rows,
    list_admin_imports,
    list_admin_layers,
    list_admin_sources,
)
from app.database import get_session, is_ready
from app.imports import (
    cancel_import,
    commit_import,
    resolve_import_row,
    stage_import,
)
from app.layers import (
    get_layer_features_page,
    get_layer_geojson,
    list_compatibility_layers,
    list_layers,
)
from app.managed import (
    archive_feature,
    create_feature,
    create_layer,
    update_feature,
    update_layer,
)
from app.pagination import DEFAULT_LIMIT
from app.schemas import (
    AdminFeature,
    AdminFeatureRead,
    AdminImportRead,
    AdminImportRowRead,
    AdminLayer,
    AdminLayerRead,
    AdminSourceRead,
    CompatibilityLayer,
    CompatibilityLayersResponse,
    ExternalSourceSummary,
    FeatureWrite,
    GeoJSONFeatureCollection,
    GeoJSONFeatureCollectionPage,
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
from app.security import require_admin
from app.sources import sync_source

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
    session: Session = Depends(get_session),
) -> GeoJSONFeatureCollectionPage:
    return get_layer_features_page(session, slug, limit, cursor, bbox, updated_since)


@app.post(
    "/api/v1/admin/layers",
    response_model=AdminLayer,
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
)
def admin_update_feature(
    feature_id: uuid.UUID,
    payload: FeatureWrite,
    session: Session = Depends(get_session),
) -> AdminFeature:
    feature = update_feature(session, feature_id, payload)
    return AdminFeature(
        id=str(feature.id), layer_id=str(feature.layer_id), status=feature.status
    )


@app.delete(
    "/api/v1/admin/features/{feature_id}", dependencies=[Depends(require_admin)]
)
def admin_archive_feature(
    feature_id: uuid.UUID, session: Session = Depends(get_session)
) -> None:
    archive_feature(session, feature_id)


@app.post(
    "/api/v1/admin/imports",
    response_model=ImportSummary,
    dependencies=[Depends(require_admin)],
)
def admin_stage_import(
    payload: ImportCreate, session: Session = Depends(get_session)
) -> ImportSummary:
    return stage_import(session, payload)


@app.get(
    "/api/v1/admin/layers",
    response_model=Page[AdminLayerRead],
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
)
def admin_get_layer(
    layer_id: uuid.UUID, session: Session = Depends(get_session)
) -> AdminLayerRead:
    return get_admin_layer(session, layer_id)


@app.get(
    "/api/v1/admin/layers/{layer_id}/features",
    response_model=Page[AdminFeatureRead],
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
)
def admin_get_feature(
    feature_id: uuid.UUID, session: Session = Depends(get_session)
) -> AdminFeatureRead:
    return get_admin_feature(session, feature_id)


@app.get(
    "/api/v1/admin/imports",
    response_model=Page[AdminImportRead],
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
)
def admin_get_import(
    import_id: uuid.UUID, session: Session = Depends(get_session)
) -> AdminImportRead:
    return get_admin_import(session, import_id)


@app.get(
    "/api/v1/admin/imports/{import_id}/rows",
    response_model=Page[AdminImportRowRead],
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
)
def admin_resolve_import_row(
    import_id: uuid.UUID,
    row_number: int,
    payload: ImportRowResolution,
    session: Session = Depends(get_session),
) -> AdminImportRowRead:
    return import_row_read(resolve_import_row(session, import_id, row_number, payload))


@app.get(
    "/api/v1/admin/sources",
    response_model=Page[AdminSourceRead],
    dependencies=[Depends(require_admin)],
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
    dependencies=[Depends(require_admin)],
)
def admin_get_source(
    source_id: uuid.UUID, session: Session = Depends(get_session)
) -> AdminSourceRead:
    return get_admin_source(session, source_id)


@app.post(
    "/api/v1/admin/imports/{import_id}/commit",
    response_model=ImportSummary,
    dependencies=[Depends(require_admin)],
)
def admin_commit_import(
    import_id: uuid.UUID,
    payload: ImportCommit,
    session: Session = Depends(get_session),
) -> ImportSummary:
    return commit_import(session, import_id, payload)


@app.delete(
    "/api/v1/admin/imports/{import_id}",
    dependencies=[Depends(require_admin)],
)
def admin_cancel_import(
    import_id: uuid.UUID, session: Session = Depends(get_session)
) -> None:
    cancel_import(session, import_id)


@app.post(
    "/api/v1/admin/sources/{source_id}/sync",
    response_model=ExternalSourceSummary,
    dependencies=[Depends(require_admin)],
)
def admin_sync_source(
    source_id: uuid.UUID, session: Session = Depends(get_session)
) -> ExternalSourceSummary:
    source = sync_source(session, source_id)
    return ExternalSourceSummary(
        id=str(source.id),
        layer_id=str(source.layer_id),
        slug=source.slug,
        adapter=source.adapter,
        dataset_id=source.dataset_id,
        status=source.status,
        last_attempt_at=source.last_attempt_at,
        last_success_at=source.last_success_at,
        last_error=source.last_error,
    )


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
