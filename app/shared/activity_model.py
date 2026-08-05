import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import String, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.shared.db.session import Base
from app.shared.core.datetime import get_utc_now

class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True) # e.g., 'user_login', 'map_view', 'layer_upload'
    
    # Metadata para guardar detalles flexibles (browser, ip, layer_id, etc.)
    metadata_: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), default=get_utc_now)

    def __repr__(self):
        return f"<ActivityLog(event={self.event_type}, user_id={self.user_id})>"
