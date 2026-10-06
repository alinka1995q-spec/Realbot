from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.deps import get_session, templates
from src.database.repositories import SettingsRepo

router = APIRouter()


KEYS = [
    ("ref_percent_l1", "Реф. процент L1 (%)"),
    ("ref_percent_l2", "Реф. процент L2 (%)"),
    ("ref_percent_l3", "Реф. процент L3 (%)"),
    ("min_withdrawal", "Мин. сумма вывода"),
    ("support_username", "Контакт поддержки (@username или ссылка)"),
    ("require_active_deposit_for_withdraw_ref", "Требовать активный депозит для вывода реф. бонусов (true/false)"),
    ("required_channel", "Обязательный канал (@username или t.me/...)"),
    ("required_group", "Обязательная группа (@username или t.me/...)"),
    ("investors_group_invite", "Инвайт в группу вкладчиков (после подтверждения депозита)"),
]


@router.get("", response_class=HTMLResponse)
async def view_settings(
    request: Request,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    repo = SettingsRepo(session)
    values = {}
    for k, _label in KEYS:
        values[k] = await repo.get(k, "") or ""
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "active_page": "settings", "keys": KEYS, "values": values},
    )


@router.post("/save")
async def save(
    request: Request,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    repo = SettingsRepo(session)
    for k, _label in KEYS:
        if k in form:
            await repo.set(k, str(form.get(k, "")))
    return RedirectResponse("/settings", status_code=303)
