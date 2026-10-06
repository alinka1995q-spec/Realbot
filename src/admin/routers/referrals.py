from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.deps import get_session, templates
from src.database.repositories import ReferralsRepo

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_referrals(
    request: Request,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    top = await ReferralsRepo(session).top_referrers(limit=50)
    total = await ReferralsRepo(session).sum_total()
    return templates.TemplateResponse(
        "referrals.html",
        {"request": request, "active_page": "referrals", "top": top, "total": total},
    )
