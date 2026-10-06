from src.database.repositories.admins import AdminsRepo
from src.database.repositories.balance import BalanceRepo
from src.database.repositories.banks import BanksRepo
from src.database.repositories.broadcasts import BroadcastsRepo
from src.database.repositories.deposits import DepositsRepo
from src.database.repositories.payouts import PayoutsRepo
from src.database.repositories.referrals import ReferralsRepo
from src.database.repositories.requisites import RequisitesRepo
from src.database.repositories.settings import SettingsRepo
from src.database.repositories.tariffs import TariffsRepo
from src.database.repositories.texts import TextsRepo
from src.database.repositories.users import UsersRepo
from src.database.repositories.withdrawals import WithdrawalsRepo

__all__ = [
    "AdminsRepo",
    "BalanceRepo",
    "BanksRepo",
    "BroadcastsRepo",
    "DepositsRepo",
    "PayoutsRepo",
    "ReferralsRepo",
    "RequisitesRepo",
    "SettingsRepo",
    "TariffsRepo",
    "TextsRepo",
    "UsersRepo",
    "WithdrawalsRepo",
]
