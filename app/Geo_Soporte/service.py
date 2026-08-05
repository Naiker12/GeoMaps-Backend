import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.Geo_Soporte.model import SupportRequest
from app.schemas.support import SupportReplyCreate, SupportRequestCreate, SupportRequestUpdate
from app.services.notifications import SupportReplyEmail, email_service


class SupportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_request(
        self,
        request_in: SupportRequestCreate,
        user_id: Optional[uuid.UUID] = None,
    ) -> SupportRequest:
        support_request = SupportRequest(
            user_id=user_id,
            name=request_in.name.strip(),
            email=str(request_in.email).strip().lower(),
            type=request_in.type.strip(),
            message=request_in.message.strip(),
            source=request_in.source.strip() or "help_panel",
            metadata_=request_in.metadata_ or {},
        )
        self.db.add(support_request)
        await self.db.commit()
        await self.db.refresh(support_request)
        return support_request

    async def list_requests(
        self,
        *,
        status: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[SupportRequest], int]:
        filters = []
        if status:
            filters.append(SupportRequest.status == status)
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    SupportRequest.name.ilike(term),
                    SupportRequest.email.ilike(term),
                    SupportRequest.type.ilike(term),
                    SupportRequest.message.ilike(term),
                )
            )

        count_stmt = select(func.count()).select_from(SupportRequest)
        stmt = select(SupportRequest)
        if filters:
            count_stmt = count_stmt.where(*filters)
            stmt = stmt.where(*filters)

        total = await self.db.scalar(count_stmt) or 0
        result = await self.db.execute(
            stmt.order_by(SupportRequest.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        return list(result.scalars().all()), int(total)

    async def get_request(self, request_id: uuid.UUID) -> Optional[SupportRequest]:
        result = await self.db.execute(
            select(SupportRequest).where(SupportRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    async def update_request(
        self,
        request_id: uuid.UUID,
        request_in: SupportRequestUpdate,
    ) -> Optional[SupportRequest]:
        support_request = await self.get_request(request_id)
        if not support_request:
            return None

        update_data = request_in.model_dump(exclude_unset=True)
        old_status = support_request.status
        for key, value in update_data.items():
            setattr(support_request, key, value)

        if update_data.get("status") == "resolved" and old_status != "resolved":
            support_request.resolved_at = datetime.now(timezone.utc)
        elif update_data.get("status") and update_data.get("status") != "resolved":
            support_request.resolved_at = None

        await self.db.commit()
        await self.db.refresh(support_request)
        return support_request

    async def reply_request(
        self,
        request_id: uuid.UUID,
        reply_in: SupportReplyCreate,
    ) -> Optional[SupportRequest]:
        support_request = await self.get_request(request_id)
        if not support_request:
            return None

        sent_at = datetime.now(timezone.utc)
        await email_service.send_support_reply(
            SupportReplyEmail(
                to_email=support_request.email,
                to_name=support_request.name,
                case_id=str(support_request.id),
                original_message=support_request.message,
                reply_message=reply_in.response_message.strip(),
            )
        )

        support_request.response_message = reply_in.response_message.strip()
        support_request.responded_at = sent_at
        support_request.email_sent_at = sent_at
        if reply_in.mark_resolved:
            support_request.status = "resolved"
            support_request.resolved_at = sent_at
        elif support_request.status == "new":
            support_request.status = "reviewing"

        await self.db.commit()
        await self.db.refresh(support_request)
        return support_request
