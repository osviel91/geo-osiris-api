import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Layer(Base):
    __tablename__ = "layers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50))
    mode: Mapped[str] = mapped_column(String(20))
    geometry_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    enabled: Mapped[bool] = mapped_column(default=True)
    style: Mapped[dict] = mapped_column(JSONB, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    revision: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    data_updated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    features: Mapped[list["Feature"]] = relationship(back_populates="layer")
    imports: Mapped[list["ImportJob"]] = relationship(back_populates="layer")
    external_sources: Mapped[list["ExternalSource"]] = relationship(
        back_populates="layer"
    )

    __table_args__ = (
        CheckConstraint("mode IN ('managed', 'external')", name="layers_mode_check"),
    )


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    layer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("layers.id"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(200))
    geometry: Mapped[object] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False)
    )
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    verified_at: Mapped[datetime | None]
    archived_at: Mapped[datetime | None]

    layer: Mapped[Layer] = relationship(back_populates="features")
    provenance_records: Mapped[list["FeatureProvenance"]] = relationship(
        back_populates="feature", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'stale', 'archived')",
            name="features_status_check",
        ),
        UniqueConstraint(
            "layer_id", "external_id", name="features_layer_external_id_key"
        ),
        Index("features_geometry_gix", "geometry", postgresql_using="gist"),
    )


class FeatureProvenance(Base):
    __tablename__ = "feature_provenance"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    feature_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("features.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    source_name: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_record_id: Mapped[str | None] = mapped_column(String(200))
    import_id: Mapped[uuid.UUID | None]
    created_by: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[str | None] = mapped_column(String(50))
    observed_at: Mapped[datetime | None]
    imported_at: Mapped[datetime] = mapped_column(server_default=func.now())
    verified_at: Mapped[datetime | None]
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    feature: Mapped[Feature] = relationship(back_populates="provenance_records")

    __table_args__ = (
        CheckConstraint(
            "source_type IN ('manual', 'import', 'agent', 'external')",
            name="feature_provenance_source_type_check",
        ),
    )


class ImportJob(Base):
    __tablename__ = "imports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    layer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("layers.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="validated")
    row_count: Mapped[int] = mapped_column(default=0)
    invalid_count: Mapped[int] = mapped_column(default=0)
    candidate_count: Mapped[int] = mapped_column(default=0)
    csv_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    csv_headers: Mapped[list[str]] = mapped_column(JSONB, default=list)
    mapping_version: Mapped[str] = mapped_column(String(20), default="1")
    source_name: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    committed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]

    layer: Mapped[Layer] = relationship(back_populates="imports")
    rows: Mapped[list["ImportRow"]] = relationship(
        back_populates="import_job", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["ImportApproval"]] = relationship(
        back_populates="import_job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("format IN ('geojson', 'csv')", name="imports_format_check"),
        CheckConstraint(
            "status IN ('validated', 'committed', 'cancelled')",
            name="imports_status_check",
        ),
    )


class ImportRow(Base):
    __tablename__ = "import_rows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("imports.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column()
    external_id: Mapped[str | None] = mapped_column(String(200))
    geometry: Mapped[dict | None] = mapped_column(JSONB)
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)
    validation_error: Mapped[str | None] = mapped_column(Text)
    candidate_feature_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    candidate_matches: Mapped[list] = mapped_column(JSONB, default=list)
    resolution: Mapped[str | None] = mapped_column(String(20))
    resolved_at: Mapped[datetime | None]

    import_job: Mapped[ImportJob] = relationship(back_populates="rows")

    __table_args__ = (
        CheckConstraint(
            "resolution IS NULL OR resolution IN ('skip', 'import_anyway')",
            name="import_rows_resolution_check",
        ),
    )


class ImportApproval(Base):
    __tablename__ = "import_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    import_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("imports.id"), index=True)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(String(64))
    requested_status: Mapped[str] = mapped_column(String(20))
    requester: Mapped[str] = mapped_column(String(100))
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    state: Mapped[str] = mapped_column(String(20), default="pending")
    approver: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None]
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime]
    executor: Mapped[str | None] = mapped_column(String(100))
    executed_at: Mapped[datetime | None]
    failure_reason: Mapped[str | None] = mapped_column(Text)

    import_job: Mapped[ImportJob] = relationship(back_populates="approvals")

    __table_args__ = (
        CheckConstraint(
            "requested_status IN ('draft', 'published')",
            name="import_approvals_requested_status_check",
        ),
        CheckConstraint(
            "state IN ('pending', 'approved', 'rejected', 'expired', "
            "'stale', 'executed', 'failed')",
            name="import_approvals_state_check",
        ),
        Index(
            "import_approvals_one_active_per_import",
            "import_id",
            unique=True,
            postgresql_where=text("state IN ('pending', 'approved')"),
        ),
    )


class ExternalSource(Base):
    __tablename__ = "external_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    layer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("layers.id"), unique=True, index=True
    )
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    adapter: Mapped[str] = mapped_column(String(100))
    dataset_id: Mapped[str] = mapped_column(String(200))
    endpoint: Mapped[str | None] = mapped_column(Text)
    adapter_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(20), default="never")
    last_attempt_at: Mapped[datetime | None]
    last_success_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)

    layer: Mapped[Layer] = relationship(back_populates="external_sources")

    __table_args__ = (
        CheckConstraint(
            "status IN ('never', 'success', 'failed')",
            name="external_sources_status_check",
        ),
    )


class LifecycleEvent(Base):
    __tablename__ = "lifecycle_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(50))
    actor: Mapped[str] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    previous_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    resulting_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
