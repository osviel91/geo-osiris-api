import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    features: Mapped[list["Feature"]] = relationship(back_populates="layer")

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
