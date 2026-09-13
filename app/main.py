import logging
import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_session, is_ready
from app.layers import get_layer_geojson, list_compatibility_layers, list_layers
from app.schemas import (
    CompatibilityLayer,
    CompatibilityLayersResponse,
    GeoJSONFeatureCollection,
    LayerSummary,
    PointGeometry,
    StaticFeature,
    StaticFeatureCollection,
    StaticFeatureProperties,
)

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

origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",")]

app = FastAPI(title="OSIRIS Geo API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET"],
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


@app.get("/api/v1/layers/{slug}/features", response_model=GeoJSONFeatureCollection)
def public_layer_features(
    slug: str, session: Session = Depends(get_session)
) -> GeoJSONFeatureCollection:
    return public_layer(slug, session)


@app.get("/layers", response_model=CompatibilityLayersResponse)
def layers(session: Session = Depends(get_session)) -> CompatibilityLayersResponse:
    try:
        persisted = [
            CompatibilityLayer(
                id=layer.slug,
                name=layer.name,
                description="" if layer.description is None else layer.description,
                endpoint=f"/layers/{layer.slug}",
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
