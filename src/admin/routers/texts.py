from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import require_admin
from src.admin.deps import get_session, templates
from src.database.repositories import TextsRepo
from src.i18n import _load_locale, i18n

router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def list_texts(
    request: Request,
    lang: str = "ru",
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    defaults = _load_locale(lang)
    overrides = await TextsRepo(session).all_by_lang(lang)
    keys = sorted(set(defaults.keys()) | set(overrides.keys()))
    rows = [
        {
            "key": k,
            "default": defaults.get(k, ""),
            "override": overrides.get(k, ""),
        }
        for k in keys
    ]
    return templates.TemplateResponse(
        "texts.html",
        {"request": request, "active_page": "texts", "rows": rows, "lang": lang},
    )


@router.post("/save")
async def save(
    key: str = Form(...),
    lang: str = Form(...),
    value: str = Form(""),
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    repo = TextsRepo(session)
    if value.strip():
        await repo.set(key, lang, value)
    # перезагрузим in-memory кэш
    overrides_list = []
    for k in await repo.keys():
        for l in ("ru", "kg"):
            v = await repo.get(k, l)
            if v is not None:
                overrides_list.append((k, l, v))
    i18n.reload_overrides(overrides_list)
    return RedirectResponse(f"/texts?lang={lang}", status_code=303)
