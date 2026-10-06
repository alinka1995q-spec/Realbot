from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.deps import get_session, templates
from src.database.repositories import BanksRepo

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_banks(
    request: Request,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    items = await BanksRepo(session).list_all()
    return templates.TemplateResponse(
        "banks.html",
        {"request": request, "active_page": "banks", "items": items},
    )


@router.post("/create")
async def create(
    name: str = Form(...),
    category: str = Form("Банки"),
    sort_order: int = Form(0),
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    if name.strip():
        await BanksRepo(session).create(
            name=name.strip(), category=(category.strip() or "Банки"), sort_order=sort_order
        )
    return RedirectResponse("/banks", status_code=303)


@router.post("/{bid}/toggle")
async def toggle(
    bid: int,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    b = await BanksRepo(session).get(bid)
    if b:
        await BanksRepo(session).set_active(bid, not b.is_active)
    return RedirectResponse("/banks", status_code=303)


@router.post("/{bid}/update")
async def edit(
    bid: int,
    name: str = Form(...),
    category: str = Form("Банки"),
    sort_order: int = Form(0),
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await BanksRepo(session).update(
        bid, name=name.strip(), category=(category.strip() or "Банки"), sort_order=sort_order
    )
    return RedirectResponse("/banks", status_code=303)


@router.post("/{bid}/delete")
async def delete(
    bid: int,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await BanksRepo(session).delete(bid)
    return RedirectResponse("/banks", status_code=303)
