from datetime import datetime
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


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


class GeoJSONFeatureCollectionPage(GeoJSONFeatureCollection):
    next_cursor: str | None = None


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


class FeaturePatch(BaseModel):
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any] | None = None
    external_id: str | None = Field(default=None, max_length=200)
    status: Literal["draft", "published", "stale", "archived"] | None = None
    verified_at: datetime | None = None
    source_type: Literal["manual", "import", "agent", "external"] | None = None
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
    source_name: str | None = Field(default=None, max_length=200)
    source_url: str | None = None


class ImportCommit(BaseModel):
    status: Literal["draft", "published"] | None = None


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1_000)


class ImportApprovalRead(BaseModel):
    id: str
    import_id: str
    fingerprint: str
    requested_status: str
    requester: str
    requested_at: datetime
    state: str
    approver: str | None
    approved_at: datetime | None
    rejection_reason: str | None
    expires_at: datetime
    executor: str | None
    executed_at: datetime | None
    failure_reason: str | None
    snapshot: dict[str, Any]


class ImportApprovalSummary(BaseModel):
    id: str
    import_id: str
    layer_id: str
    layer_name: str
    layer_slug: str
    filename: str
    format: str
    source_name: str | None
    source_url: str | None
    mapping_version: str
    requested_status: str
    requester: str
    requested_at: datetime
    state: str
    approver: str | None
    approved_at: datetime | None
    rejection_reason: str | None
    expires_at: datetime
    executor: str | None
    executed_at: datetime | None
    failure_reason: str | None
    fingerprint: str
    row_count: int
    valid_count: int
    invalid_count: int
    candidate_count: int
    resolved_candidate_count: int
    unresolved_candidate_count: int


class ImportSummary(BaseModel):
    id: str
    layer_id: str
    filename: str
    format: str
    status: str
    row_count: int
    valid_count: int
    invalid_count: int
    candidate_count: int
    csv_mapping: dict[str, Any]
    csv_headers: list[str]
    mapping_version: str
    source_name: str | None
    source_url: str | None


class ExternalSourceSummary(BaseModel):
    id: str
    layer_id: str
    slug: str
    adapter: str
    dataset_id: str
    adapter_config: dict[str, Any]
    enabled: bool = True
    status: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    agent_managed: bool = False


class AgentSourceProposal(BaseModel):
    endpoint: str
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=500)
    category: str = Field(max_length=50)
    geometry_types: list[str] = Field(min_length=1)
    dataset_id: str = Field(min_length=1, max_length=200)
    id_property: str | None = Field(default=None, max_length=100)
    properties: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=20, ge=1, le=60)
    pagination: dict[str, Any] | None = None
    geometry_repair: dict[str, Any] | None = None
    attribution: str | None = Field(default=None, max_length=500)
    license: str | None = Field(default=None, max_length=200)


class AgentSourceCreate(BaseModel):
    proposal: AgentSourceProposal
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class AgentSourceValidation(BaseModel):
    proposal: AgentSourceProposal
    summary: dict[str, Any]
    warnings: list[str]
    fingerprint: str


class AgentSourceSync(BaseModel):
    source_id: str
    source_slug: str
    layer_id: str
    layer_slug: str
    status: str
    created: int
    updated: int
    archived: int
    unchanged: int
    reactivated: int
    valid_as_received: int = 0
    repaired: int = 0
    rejected: int = 0
    duration_ms: int
    attempted_at: datetime
    completed_at: datetime
    error: str | None = None
    warnings: list[str] = []


class AdminLayerRead(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None
    category: str
    mode: str
    geometry_types: list[str]
    enabled: bool
    style: dict[str, Any]
    metadata_: dict[str, Any]
    revision: int
    data_updated_at: datetime | None
    feature_count: int
    created_at: datetime
    updated_at: datetime


class ProvenanceRead(BaseModel):
    id: str
    source_type: str
    source_name: str | None
    source_url: str | None
    source_record_id: str | None
    import_id: str | None
    created_by: str
    confidence: str | None
    observed_at: datetime | None
    imported_at: datetime
    verified_at: datetime | None
    metadata_: dict[str, Any]


class AdminFeatureRead(BaseModel):
    id: str
    layer_id: str
    external_id: str | None
    geometry: dict[str, Any]
    properties: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime
    verified_at: datetime | None
    archived_at: datetime | None
    provenance: list[ProvenanceRead] = Field(default_factory=list)
    ownership: str = "manual"
    source: "FeatureSourceRead | None" = None
    deletion_warning: str | None = None


class FeatureSourceRead(BaseModel):
    slug: str
    record_id: str | None


class EmptyLayerDelete(BaseModel):
    confirmation: Literal["DELETE EMPTY LAYER"]


class CascadeLayerDelete(BaseModel):
    confirmation: Literal["DELETE DISPOSABLE LAYER"]


class ExternalFeatureDelete(BaseModel):
    confirm_recreated_on_sync: bool = False


class AdminImportRead(BaseModel):
    id: str
    layer_id: str
    filename: str
    format: str
    status: str
    row_count: int
    valid_count: int
    invalid_count: int
    candidate_count: int
    resolved_candidate_count: int
    unresolved_candidate_count: int
    csv_mapping: dict[str, Any]
    csv_headers: list[str]
    mapping_version: str
    source_name: str | None
    source_url: str | None
    created_at: datetime
    committed_at: datetime | None
    cancelled_at: datetime | None


class AdminImportRowRead(BaseModel):
    row_number: int
    external_id: str | None
    geometry: dict[str, Any] | None
    properties: dict[str, Any]
    validation_error: str | None
    candidate_feature_ids: list[str]
    candidate_matches: list[dict[str, Any]] = Field(default_factory=list)
    resolution: str | None
    resolved_at: datetime | None


class ImportRowResolution(BaseModel):
    resolution: Literal["skip", "import_anyway"]


class AdminSourceRead(BaseModel):
    id: str
    layer_id: str
    slug: str
    adapter: str
    dataset_id: str
    endpoint: str | None
    adapter_config: dict[str, Any]
    enabled: bool
    status: str
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    agent_managed: bool = False
