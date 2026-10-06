from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Broadcast, BroadcastStatus


class BroadcastsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        text: Optional[str],
        media_type: Optional[str],
        media_file_id: Optional[str],
        audience: str,
        audience_payload: Optional[dict] = None,
        scheduled_at: Optional[datetime] = None,
        admin_id: Optional[int] = None,
    ) -> Broadcast:
        b = Broadcast(
            text=text,
            media_type=media_type,
            media_file_id=media_file_id,
            audience=audience,
            audience_payload=audience_payload,
            scheduled_at=scheduled_at,
            created_by_admin_id=admin_id,
            status=BroadcastStatus.SCHEDULED.value,
        )
        self.session.add(b)
        await self.session.flush()
        return b

    async def get(self, broadcast_id: int) -> Optional[Broadcast]:
        return await self.session.get(Broadcast, broadcast_id)

    async def list_recent(self, limit: int = 30) -> list[Broadcast]:
        res = await self.session.execute(
            select(Broadcast).order_by(Broadcast.created_at.desc()).limit(limit)
        )
        return list(res.scalars())

    async def update_progress(
        self,
        broadcast_id: int,
        *,
        status: Optional[BroadcastStatus] = None,
        total: Optional[int] = None,
        sent: Optional[int] = None,
        failed: Optional[int] = None,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
    ) -> None:
        values: dict = {}
        if status is not None:
            values["status"] = status.value
        if total is not None:
            values["total"] = total
        if sent is not None:
            values["sent"] = sent
        if failed is not None:
            values["failed"] = failed
        if started_at is not None:
            values["started_at"] = started_at
        if finished_at is not None:
            values["finished_at"] = finished_at
        if not values:
            return
        await self.session.execute(update(Broadcast).where(Broadcast.id == broadcast_id).values(**values))

    async def due(self, now: datetime) -> list[Broadcast]:
        res = await self.session.execute(
            select(Broadcast).where(
                Broadcast.status == BroadcastStatus.SCHEDULED.value,
                Broadcast.scheduled_at.is_not(None),
                Broadcast.scheduled_at <= now,
            )
        )
        return list(res.scalars())
