from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class CompatibilityLayer(BaseModel):
    id: str
    name: str
    description: str
    endpoint: str


class CompatibilityLayersResponse(BaseModel):
    layers: list[CompatibilityLayer]


class PointGeometry(BaseModel):
    type: Literal["Point"]
    coordinates: tuple[float, float]


class StaticFeatureProperties(BaseModel):
    id: str
    name: str
    source: str
    category: str
    status: str


class StaticFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: PointGeometry
    properties: StaticFeatureProperties


class StaticFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[StaticFeature]


class LayerSummary(BaseModel):
    id: str
    slug: str
    name: str
    category: str
    mode: str
    geometry_types: list[str]
    enabled: bool
    feature_count: int
    updated_at: datetime


class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: dict[str, Any]
    properties: dict[str, Any]


class GeoJSONFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]
