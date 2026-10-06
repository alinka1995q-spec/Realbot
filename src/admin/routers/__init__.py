from src.admin.routers.admins import router as admins_router
from src.admin.routers.auth import router as auth_router
from src.admin.routers.banks import router as banks_router
from src.admin.routers.broadcasts import router as broadcasts_router
from src.admin.routers.dashboard import router as dashboard_router
from src.admin.routers.deposits import router as deposits_router
from src.admin.routers.export import router as export_router
from src.admin.routers.payouts import router as payouts_router
from src.admin.routers.referrals import router as referrals_router
from src.admin.routers.requisites import router as requisites_router
from src.admin.routers.settings import router as settings_router
from src.admin.routers.tariffs import router as tariffs_router
from src.admin.routers.texts import router as texts_router
from src.admin.routers.users import router as users_router
from src.admin.routers.withdrawals import router as withdrawals_router

__all__ = [
    "admins_router",
    "auth_router",
    "banks_router",
    "broadcasts_router",
    "dashboard_router",
    "deposits_router",
    "export_router",
    "payouts_router",
    "referrals_router",
    "requisites_router",
    "settings_router",
    "tariffs_router",
    "texts_router",
    "users_router",
    "withdrawals_router",
]
