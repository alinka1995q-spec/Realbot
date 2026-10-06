import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from src.admin.auth import is_authenticated
from src.admin.deps import templates  # noqa: F401
from src.admin.routers import (
    auth_router,
    banks_router,
    broadcasts_router,
    dashboard_router,
    deposits_router,
    export_router,
    payouts_router,
    referrals_router,
    requisites_router,
    settings_router,
    tariffs_router,
    texts_router,
    users_router,
    withdrawals_router,
    admins_router,
)
from src.config import get_settings
from src.database import init_models

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    yield


def build_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Deposit Bot Admin", lifespan=lifespan)
    app.add_middleware(SessionMiddleware, secret_key=settings.admin_secret, max_age=14 * 24 * 3600)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(deposits_router, prefix="/deposits")
    app.include_router(payouts_router, prefix="/payouts")
    app.include_router(withdrawals_router, prefix="/withdrawals")
    app.include_router(tariffs_router, prefix="/tariffs")
    app.include_router(requisites_router, prefix="/requisites")
    app.include_router(banks_router, prefix="/banks")
    app.include_router(users_router, prefix="/users")
    app.include_router(admins_router, prefix="/admins")
    app.include_router(referrals_router, prefix="/referrals")
    app.include_router(broadcasts_router, prefix="/broadcasts")
    app.include_router(texts_router, prefix="/texts")
    app.include_router(settings_router, prefix="/settings")
    app.include_router(export_router, prefix="/export")

    @app.get("/", include_in_schema=False)
    async def root(request: Request):
        if is_authenticated(request):
            return RedirectResponse("/dashboard", status_code=303)
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        # вместо raw json возвращаем человеку понятную страницу
        errors = []
        for e in exc.errors():
            loc = ".".join(str(p) for p in e.get("loc", []) if p not in ("body", "query"))
            errors.append(f"{loc}: {e.get('msg')}")
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "code": 400,
                "title": "Неверные данные формы",
                "message": "Проверь заполнение полей и попробуй ещё раз.",
                "details": errors,
                "back": request.headers.get("referer", "/dashboard"),
            },
            status_code=400,
        )

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return templates.TemplateResponse(
                "404.html", {"request": request}, status_code=404
            )
        if exc.status_code in (401, 403, 307):
            # для htmx нужен заголовок HX-Redirect (htmx сам выполнит client-side redirect)
            if request.headers.get("HX-Request") == "true":
                from fastapi.responses import Response

                return Response(
                    status_code=200,
                    headers={"HX-Redirect": "/login"},
                )
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "code": exc.status_code,
                "title": "Ошибка",
                "message": str(exc.detail) if exc.detail else "Что-то пошло не так",
                "details": [],
                "back": "/dashboard",
            },
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def on_unhandled(request: Request, exc: Exception):
        logger.exception("Unhandled %s on %s: %s", type(exc).__name__, request.url.path, exc)
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "code": 500,
                "title": "Внутренняя ошибка сервера",
                "message": "Что-то пошло не так. Попробуй обновить страницу.",
                "details": [f"{type(exc).__name__}: {exc}"],
                "back": "/dashboard",
            },
            status_code=500,
        )

    return app


app = build_app()
