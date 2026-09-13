from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CompatibilityLayer(BaseModel):
    id: str
    name: str
    description: str
    endpoint: str
    revision: int = 0
    data_updated_at: datetime | None = None


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
    revision: int
    data_updated_at: datetime | None
    updated_at: datetime


class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: dict[str, Any]
    properties: dict[str, Any]


class GeoJSONFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]


class LayerCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    name: str = Field(max_length=200)
    description: str | None = None
    category: str = Field(max_length=50)
    mode: Literal["managed", "external"]
    geometry_types: list[str] = Field(min_length=1)
    enabled: bool = True
    style: dict[str, Any] = Field(default_factory=dict)
    metadata_: dict[str, Any] = Field(default_factory=dict)


class LayerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    category: str | None = Field(default=None, max_length=50)
    enabled: bool | None = None
    style: dict[str, Any] | None = None
    metadata_: dict[str, Any] | None = None


class FeatureWrite(BaseModel):
    geometry: dict[str, Any]
    properties: dict[str, Any] = Field(default_factory=dict)
    external_id: str | None = Field(default=None, max_length=200)
    status: Literal["draft", "published", "stale", "archived"] = "draft"
    verified_at: datetime | None = None
    source_type: Literal["manual", "import", "agent", "external"] = "manual"
    source_name: str | None = Field(default=None, max_length=200)
    source_url: str | None = None
    source_record_id: str | None = Field(default=None, max_length=200)


class AdminLayer(BaseModel):
    id: str
    slug: str
    name: str
    mode: str


class AdminFeature(BaseModel):
    id: str
    layer_id: str
    status: str


class ImportCreate(BaseModel):
    layer_id: UUID
    filename: str = Field(max_length=255)
    format: Literal["geojson", "csv"]
    content: str = Field(max_length=5_000_000)
    csv_mapping: dict[str, Any] = Field(default_factory=dict)


class ImportCommit(BaseModel):
    status: Literal["draft", "published"] = "draft"


class ImportRowSummary(BaseModel):
    row_number: int
    validation_error: str | None
    candidate_feature_ids: list[str]


class ImportSummary(BaseModel):
    id: str
    layer_id: str
    filename: str
    format: str
    status: str
    row_count: int
    invalid_count: int
    candidate_count: int
    rows: list[ImportRowSummary]


class ExternalSourceSummary(BaseModel):
    id: str
    layer_id: str
    slug: str
    adapter: str
    dataset_id: str
    status: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
