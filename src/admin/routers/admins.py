from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.deps import get_session, templates
from src.database.models import AdminRole
from src.database.repositories import AdminsRepo

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_admins(
    request: Request,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    items = await AdminsRepo(session).list_all()
    return templates.TemplateResponse(
        "admins.html",
        {"request": request, "active_page": "admins", "items": items, "roles": [r.value for r in AdminRole]},
    )


@router.post("/create")
async def create(
    telegram_id: int = Form(...),
    name: str = Form(""),
    username: str = Form(""),
    role: str = Form("admin"),
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await AdminsRepo(session).add(
        telegram_id,
        name=name or None,
        username=username or None,
        role=AdminRole(role),
    )
    return RedirectResponse("/admins", status_code=303)


@router.post("/{aid}/delete")
async def delete(
    aid: int,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await AdminsRepo(session).remove(aid)
    return RedirectResponse("/admins", status_code=303)
