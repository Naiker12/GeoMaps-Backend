import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

if TYPE_CHECKING:
    from app.db.models.project import Project


class ProjectAsset(Base):
    """Archivo tipado asociado a un proyecto: imagen, PDF, IFC, GLB, CAD o fuente espacial."""

    __tablename__ = "project_assets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    role: Mapped[Optional[str]] = mapped_column(String(50))

    original_filename: Mapped[Optional[str]] = mapped_column(Text)
    storage_bucket: Mapped[Optional[str]] = mapped_column(String(100))
    storage_path: Mapped[Optional[str]] = mapped_column(Text)
    public_url: Mapped[Optional[str]] = mapped_column(Text)
    mime_type: Mapped[Optional[str]] = mapped_column(String(150))
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    extension: Mapped[Optional[str]] = mapped_column(String(20))

    derived_from_asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("project_assets.id", ondelete="SET NULL"),
        nullable=True,
    )

    conversion_status: Mapped[str] = mapped_column(
        String(50),
        default="not_required",
        nullable=False,
    )
    conversion_error: Mapped[Optional[str]] = mapped_column(Text)

    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)
    transform: Mapped[Optional[dict]] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    project: Mapped["Project"] = relationship(back_populates="assets")
    derived_from: Mapped[Optional["ProjectAsset"]] = relationship(remote_side=[id])
