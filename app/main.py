import logging
import os
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


class Layer(BaseModel):
    id: str
    name: str
    description: str
    endpoint: str


class LayersResponse(BaseModel):
    layers: list[Layer]


class PointGeometry(BaseModel):
    type: Literal["Point"]
    coordinates: tuple[float, float]


class FeatureProperties(BaseModel):
    id: str
    name: str
    source: str
    category: str
    status: str


class Feature(BaseModel):
    type: Literal["Feature"]
    geometry: PointGeometry
    properties: FeatureProperties


class FeatureCollection(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[Feature]


TEST_LAYER = Layer(
    id="test",
    name="Test Layer",
    description="Static validation layer",
    endpoint="/layers/test",
)

TEST_FEATURES = [
    Feature(
        type="Feature",
        geometry=PointGeometry(type="Point", coordinates=(-3.7038, 40.4168)),
        properties=FeatureProperties(
            id="test-1",
            name="Madrid test point",
            source="local",
            category="test",
            status="online",
        ),
    ),
    Feature(
        type="Feature",
        geometry=PointGeometry(type="Point", coordinates=(2.1734, 41.3851)),
        properties=FeatureProperties(
            id="test-2",
            name="Barcelona test point",
            source="local",
            category="test",
            status="online",
        ),
    ),
    Feature(
        type="Feature",
        geometry=PointGeometry(type="Point", coordinates=(-0.3763, 39.4699)),
        properties=FeatureProperties(
            id="test-3",
            name="Valencia test point",
            source="local",
            category="test",
            status="online",
        ),
    ),
]

origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",")]

app = FastAPI(title="OSIRIS Geo API", version="0.1.0")
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


@app.get("/layers", response_model=LayersResponse)
def layers() -> LayersResponse:
    return LayersResponse(layers=[TEST_LAYER])


@app.get("/layers/test", response_model=FeatureCollection)
def test_layer() -> FeatureCollection:
    return FeatureCollection(type="FeatureCollection", features=TEST_FEATURES)
