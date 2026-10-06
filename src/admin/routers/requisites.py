from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from collections import OrderedDict

from src.admin.auth import require_admin
from src.admin.deps import get_session, templates
from src.database.repositories import BanksRepo, RequisitesRepo

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_requisites(
    request: Request,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    items = await RequisitesRepo(session).list_all()
    banks = await BanksRepo(session).list_active()
    # фиксированный порядок категорий
    CATEGORY_ORDER = ["Банк", "Криптовалюта", "КриптоБот"]
    grouped: "OrderedDict[str, list[str]]" = OrderedDict()
    for cat in CATEGORY_ORDER:
        cat_banks = [b.name for b in banks if b.category == cat]
        if cat_banks:
            grouped[cat] = cat_banks
    # любые экзотические категории — в конец
    for b in banks:
        if b.category not in grouped:
            grouped.setdefault(b.category, []).append(b.name)
    return templates.TemplateResponse(
        "requisites.html",
        {
            "request": request,
            "active_page": "requisites",
            "items": items,
            "banks_by_category": grouped,
        },
    )


@router.post("/create")
async def create(
    bank: str = Form(...),
    number: str = Form(...),
    holder_name: str = Form(""),
    comment: str = Form(""),
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await RequisitesRepo(session).create(
        bank=bank, number=number, holder_name=holder_name or None, comment=comment or None
    )
    return RedirectResponse("/requisites", status_code=303)


@router.post("/{rid}/toggle")
async def toggle(
    rid: int,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    r = await RequisitesRepo(session).get(rid)
    if r:
        await RequisitesRepo(session).set_active(rid, not r.is_active)
    return RedirectResponse("/requisites", status_code=303)


@router.post("/{rid}/update")
async def update(
    rid: int,
    bank: str = Form(...),
    number: str = Form(...),
    holder_name: str = Form(""),
    comment: str = Form(""),
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    await RequisitesRepo(session).update(
        rid, bank=bank, number=number, holder_name=holder_name or None, comment=comment or None
    )
    return RedirectResponse("/requisites", status_code=303)
