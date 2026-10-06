from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.deps import get_session, templates
from src.database.models import TariffPeriod
from src.database.repositories import TariffsRepo

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_tariffs(
    request: Request,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    items = await TariffsRepo(session).list_all()
    return templates.TemplateResponse(
        "tariffs.html",
        {
            "request": request,
            "active_page": "tariffs",
            "items": items,
            "periods": [p.value for p in TariffPeriod],
        },
    )


@router.post("/create")
async def create(
    name: str = Form(...),
    description: str = Form(""),
    min_amount: Decimal = Form(...),
    max_amount: Decimal = Form(...),
    duration_days: int = Form(...),
    period: str = Form(...),
    period_n_days: int = Form(1),
    payout_percent: str = Form(""),
    payout_fixed: str = Form(""),
    body_included: str = Form("on"),
    sort_order: int = Form(0),
    max_purchases: int = Form(0),
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    pp = Decimal(payout_percent) if payout_percent else None
    pf = Decimal(payout_fixed) if payout_fixed else None
    await TariffsRepo(session).create(
        name=name,
        description=description or None,
        min_amount=min_amount,
        max_amount=max_amount,
        duration_days=duration_days,
        period=TariffPeriod(period),
        period_n_days=period_n_days,
        payout_percent=pp,
        payout_fixed=pf,
        body_included=(body_included in ("on", "1", "true")),
        sort_order=sort_order,
        max_purchases=max(0, max_purchases),
    )
    return RedirectResponse("/tariffs", status_code=303)


@router.post("/{tid}/update")
async def update(
    tid: int,
    name: str = Form(...),
    description: str = Form(""),
    min_amount: Decimal = Form(...),
    max_amount: Decimal = Form(...),
    duration_days: int = Form(...),
    period: str = Form(...),
    period_n_days: int = Form(1),
    payout_percent: str = Form(""),
    payout_fixed: str = Form(""),
    body_included: str = Form(""),
    sort_order: int = Form(0),
    max_purchases: int = Form(0),
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    pp = Decimal(payout_percent) if payout_percent else None
    pf = Decimal(payout_fixed) if payout_fixed else None
    await TariffsRepo(session).update(
        tid,
        name=name,
        description=description or None,
        min_amount=min_amount,
        max_amount=max_amount,
        duration_days=duration_days,
        period=period,
        period_n_days=period_n_days,
        payout_percent=pp,
        payout_fixed=pf,
        body_included=(body_included in ("on", "1", "true")),
        sort_order=sort_order,
        max_purchases=max(0, max_purchases),
    )
    return RedirectResponse("/tariffs", status_code=303)


@router.post("/{tid}/toggle")
async def toggle(
    tid: int,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    t = await TariffsRepo(session).get(tid)
    if t:
        await TariffsRepo(session).set_active(tid, not t.is_active)
    return RedirectResponse("/tariffs", status_code=303)
