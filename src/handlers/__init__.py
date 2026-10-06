from aiogram import Router

from src.handlers import (
    admin as admin_handlers,
    balance as balance_handlers,
    deposit as deposit_handlers,
    fallback as fallback_handlers,
    payout as payout_handlers,
    referral as referral_handlers,
    start as start_handlers,
    support as support_handlers,
)


def all_routers() -> list[Router]:
    return [
        start_handlers.router,
        deposit_handlers.router,
        payout_handlers.router,
        referral_handlers.router,
        balance_handlers.router,
        support_handlers.router,
        admin_handlers.router,
        fallback_handlers.router,  # catch-all - всегда последний
    ]
