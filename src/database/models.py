"""ER-схема проекта.

Таблицы:
    users            - Telegram-пользователи
    admins           - администраторы и модераторы
    tariffs          - тарифные планы
    requisites       - реквизиты для приёма депозитов
    deposits         - депозиты пользователей
    payouts          - запланированные/исполненные выплаты по депозитам
    withdrawals      - заявки на вывод средств
    referrals        - связи реферал-реферер (фиксируется один раз при /start)
    referral_earnings- журнал реферальных начислений
    balance_changes  - история изменений внутреннего баланса
    broadcasts       - рассылки
    bot_texts        - редактируемые тексты бота (i18n)
    settings_kv      - произвольные настройки (ключ-значение)
    admin_logs       - аудит действий администраторов
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

# JSON-тип, работающий и в SQLite (JSON), и в PostgreSQL (JSONB)
JSONType = JSON().with_variant(JSONB(), "postgresql")
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.connection import Base


# ---------- enum-ы статусов ----------
class DepositStatus(StrEnum):
    PENDING = "pending"        # ждёт подтверждения админом
    ACTIVE = "active"          # подтверждён, идут выплаты
    COMPLETED = "completed"    # отработал срок
    REJECTED = "rejected"      # отклонён админом
    CANCELLED = "cancelled"    # ручное закрытие админом


class PayoutStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class WithdrawalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TariffPeriod(StrEnum):
    DAILY = "daily"
    EVERY_N_DAYS = "every_n_days"
    AT_END = "at_end"


class AdminRole(StrEnum):
    ADMIN = "admin"
    MODERATOR = "moderator"


class BalanceChangeReason(StrEnum):
    REFERRAL = "referral"
    PAYOUT = "payout"
    WITHDRAWAL = "withdrawal"
    MANUAL_CREDIT = "manual_credit"
    MANUAL_DEBIT = "manual_debit"
    ADJUSTMENT = "adjustment"


class BroadcastStatus(StrEnum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# ---------- модели ----------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    lang: Mapped[str] = mapped_column(String(8), default="ru")

    referrer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    referrer_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, server_default="0")

    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    blocked_reason: Mapped[Optional[str]] = mapped_column(Text)

    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    referrer: Mapped[Optional["User"]] = relationship(remote_side="User.id", lazy="noload")
    deposits: Mapped[list["Deposit"]] = relationship(back_populates="user", lazy="noload")

    def __repr__(self) -> str:
        return f"<User #{self.id} tg={self.telegram_id} balance={self.balance}>"


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(128))
    username: Mapped[Optional[str]] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default=AdminRole.ADMIN.value)
    is_root: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text)

    min_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    duration_days: Mapped[int] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(16), default=TariffPeriod.DAILY.value)
    period_n_days: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    # либо процент от тела за одну выплату, либо абсолютная сумма
    payout_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4))
    payout_fixed: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))

    # включает ли выплата возврат тела (true = аннуитет, false = тело отдельно в конце)
    body_included: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Максимум депозитов этого тарифа на одного пользователя (0 = без лимита)
    max_purchases: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Bank(Base):
    """Справочник банков/способов для приёма и вывода (с категориями)."""

    __tablename__ = "banks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    category: Mapped[str] = mapped_column(
        String(64), default="Банки", server_default="Банки", index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Requisite(Base):
    __tablename__ = "requisites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bank: Mapped[str] = mapped_column(String(64))          # MBank / O!Деньги / USDT TRC20 / ...
    number: Mapped[str] = mapped_column(String(128))       # карта / телефон / адрес кошелька
    holder_name: Mapped[Optional[str]] = mapped_column(String(128))
    comment: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Deposit(Base):
    __tablename__ = "deposits"
    __table_args__ = (
        Index("ix_deposits_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id", ondelete="RESTRICT"))
    requisite_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("requisites.id", ondelete="SET NULL")
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(
        String(16), default=DepositStatus.PENDING.value, index=True
    )

    # чек о переводе от пользователя
    receipt_file_id: Mapped[Optional[str]] = mapped_column(String(255))
    receipt_hash: Mapped[Optional[str]] = mapped_column(String(128), index=True)

    # реквизиты, КУДА получать выплаты
    payout_full_name: Mapped[Optional[str]] = mapped_column(String(255))
    payout_bank: Mapped[Optional[str]] = mapped_column(String(64))
    payout_number: Mapped[Optional[str]] = mapped_column(String(128))

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    rejected_reason: Mapped[Optional[str]] = mapped_column(Text)
    confirmed_by_admin_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )

    user: Mapped["User"] = relationship(back_populates="deposits", lazy="noload")
    tariff: Mapped["Tariff"] = relationship(lazy="joined")
    payouts: Mapped[list["Payout"]] = relationship(back_populates="deposit", lazy="noload")


class Payout(Base):
    __tablename__ = "payouts"
    __table_args__ = (
        Index("ix_payouts_status_due", "status", "due_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deposit_id: Mapped[int] = mapped_column(ForeignKey("deposits.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default=PayoutStatus.PENDING.value)
    seq: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # номер выплаты по депозиту

    paid_by_admin_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )

    deposit: Mapped["Deposit"] = relationship(back_populates="payouts", lazy="noload")


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    bank: Mapped[str] = mapped_column(String(64))
    number: Mapped[str] = mapped_column(String(128))
    holder_name: Mapped[Optional[str]] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(String(16), default=WithdrawalStatus.PENDING.value, index=True)
    rejected_reason: Mapped[Optional[str]] = mapped_column(Text)
    processed_by_admin_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ReferralEarning(Base):
    __tablename__ = "referral_earnings"
    __table_args__ = (
        Index("ix_referral_earnings_to", "to_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    deposit_id: Mapped[int] = mapped_column(ForeignKey("deposits.id", ondelete="CASCADE"))
    level: Mapped[int] = mapped_column(Integer)            # 1, 2 или 3
    percent: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BalanceChange(Base):
    __tablename__ = "balance_changes"
    __table_args__ = (
        Index("ix_balance_changes_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))  # знак: + или -
    reason: Mapped[str] = mapped_column(String(32))
    ref_id: Mapped[Optional[int]] = mapped_column(Integer)   # id связанного объекта (payout/withdrawal/referral_earning)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admins.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[Optional[str]] = mapped_column(Text)
    media_type: Mapped[Optional[str]] = mapped_column(String(16))   # photo, video, none
    media_file_id: Mapped[Optional[str]] = mapped_column(String(255))

    audience: Mapped[str] = mapped_column(String(32))               # all/active/with_deposit/without_deposit/by_tariff
    audience_payload: Mapped[Optional[dict]] = mapped_column(JSONType)  # доп. фильтр (tariff_id etc)

    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(16), default=BroadcastStatus.SCHEDULED.value)
    created_by_admin_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BotText(Base):
    __tablename__ = "bot_texts"
    __table_args__ = (
        UniqueConstraint("key", "lang", name="uq_bot_texts_key_lang"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), index=True)
    lang: Mapped[str] = mapped_column(String(8))
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SettingsKV(Base):
    __tablename__ = "settings_kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AdminLog(Base):
    __tablename__ = "admin_logs"
    __table_args__ = (
        Index("ix_admin_logs_admin_created", "admin_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("admins.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[Optional[str]] = mapped_column(String(32))   # deposit/user/tariff/...
    target_id: Mapped[Optional[int]] = mapped_column(Integer)
    payload: Mapped[Optional[dict]] = mapped_column(JSONType)
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserChatMessage(Base):
    """Журнал переписки пользователя с ботом (для просмотра в админке)."""

    __tablename__ = "user_chat_messages"
    __table_args__ = (
        Index("ix_user_chat_messages_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    direction: Mapped[str] = mapped_column(String(4))  # 'in' / 'out'
    text: Mapped[Optional[str]] = mapped_column(Text)
    media_type: Mapped[Optional[str]] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
