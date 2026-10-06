from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.admin.auth import login_session, logout_session, verify_credentials
from src.admin.deps import get_session, templates
from src.config import get_settings
from src.database.repositories import AdminsRepo

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/login")
async def login_submit(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    if not verify_credentials(login, password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Неверные данные."},
            status_code=401,
        )
    settings = get_settings()
    repo = AdminsRepo(session)
    admin = await repo.get_by_tg(settings.root_admin_id)
    if admin is None:
        admin = await repo.add(settings.root_admin_id, name="Root", is_root=True)
    login_session(request, admin.id, admin.telegram_id)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    logout_session(request)
    return RedirectResponse("/login", status_code=303)
