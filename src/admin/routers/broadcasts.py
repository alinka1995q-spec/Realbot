from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.deps import get_session, templates
from src.database.repositories import BroadcastsRepo

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_broadcasts(
    request: Request,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    items = await BroadcastsRepo(session).list_recent()
    return templates.TemplateResponse(
        "broadcasts.html",
        {"request": request, "active_page": "broadcasts", "items": items},
    )


@router.post("/create")
async def create(
    text: str = Form(""),
    media_file_id: str = Form(""),
    media_type: str = Form(""),
    audience: str = Form("all"),
    tariff_id: str = Form(""),
    scheduled_at: str = Form(""),
    admin_data: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    # tariff_id: принимаем строкой, ручной парсинг (пустая строка -> None)
    tariff_id_int: Optional[int] = None
    if tariff_id.strip():
        try:
            tariff_id_int = int(tariff_id)
        except ValueError:
            tariff_id_int = None

    # расписание: пусто -> сейчас (мгновенная рассылка через scheduler)
    # Если пользователь ввёл время — трактуем как Бишкек (UTC+6) и переводим в UTC
    from datetime import timedelta as _td
    BISHKEK = timezone(_td(hours=6))
    sched: Optional[datetime] = None
    if scheduled_at.strip():
        try:
            naive = datetime.fromisoformat(scheduled_at)
            if naive.tzinfo is None:
                naive = naive.replace(tzinfo=BISHKEK)
            sched = naive.astimezone(timezone.utc)
        except ValueError:
            sched = datetime.now(timezone.utc)
    else:
        sched = datetime.now(timezone.utc)

    payload = {"tariff_id": tariff_id_int} if tariff_id_int else None

    # требуем текст или медиа
    if not (text.strip() or media_file_id.strip()):
        return RedirectResponse("/broadcasts?error=empty", status_code=303)

    await BroadcastsRepo(session).create(
        text=text or None,
        media_type=media_type or None,
        media_file_id=media_file_id or None,
        audience=audience,
        audience_payload=payload,
        scheduled_at=sched,
        admin_id=admin_data["admin_id"],
    )
    return RedirectResponse("/broadcasts?ok=1", status_code=303)
