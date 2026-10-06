from typing import Optional

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.repositories import AdminsRepo


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get("admin_id"))


def login_session(request: Request, admin_id: int, telegram_id: int) -> None:
    request.session["admin_id"] = admin_id
    request.session["telegram_id"] = telegram_id


def logout_session(request: Request) -> None:
    request.session.clear()


def require_admin(request: Request) -> dict:
    if not is_authenticated(request):
        # 401 - exception handler в app.py красиво редиректит и htmx, и браузер
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)
    return {
        "admin_id": request.session.get("admin_id"),
        "telegram_id": request.session.get("telegram_id"),
        "role": request.session.get("role", "admin"),
        "is_full_admin": request.session.get("is_full_admin", True),
        "ip": ip,
    }


def require_full_admin(request: Request) -> dict:
    """Только полноценный admin (не moderator). Web-вход всегда даёт полные права."""
    data = require_admin(request)
    if not data.get("is_full_admin", True):
        raise HTTPException(status_code=403, detail="forbidden")
    return data


async def current_admin(request: Request, session: AsyncSession) -> Optional[dict]:
    aid = request.session.get("admin_id")
    if aid is None:
        return None
    repo = AdminsRepo(session)
    items = await repo.list_all()
    for a in items:
        if a.id == aid:
            return {"id": a.id, "name": a.name, "telegram_id": a.telegram_id, "role": a.role, "is_root": a.is_root}
    return None


def verify_credentials(login: str, password: str) -> bool:
    """
    Если задан ADMIN_WEB_LOGIN - вход по строковому логину.
    Иначе - старый режим: логин = Telegram ID root-админа.
    """
    settings = get_settings()
    login = (login or "").strip()
    if settings.admin_web_login:
        return login == settings.admin_web_login and password == settings.admin_web_password
    try:
        tg = int(login)
    except ValueError:
        return False
    return tg == settings.root_admin_id and password == settings.admin_web_password
