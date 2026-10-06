import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.admin.auth import require_admin
from src.admin.deps import get_session
from src.database.models import Deposit, Payout, User, Withdrawal

router = APIRouter()


def _csv_response(headers: list[str], rows: list[list], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(headers)
    w.writerows(rows)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _xlsx_response(headers: list[str], rows: list[list], filename: str) -> StreamingResponse:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/users.{ext}")
async def export_users(
    ext: str,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(select(User).order_by(User.id))
    rows = [
        [
            u.id,
            u.telegram_id,
            u.username or "",
            u.full_name or "",
            u.phone or "",
            u.lang,
            str(u.balance),
            u.is_blocked,
            u.created_at.isoformat() if u.created_at else "",
        ]
        for u in res.scalars()
    ]
    headers = ["id", "telegram_id", "username", "full_name", "phone", "lang", "balance", "blocked", "created_at"]
    fname = f"users_{datetime.now(timezone.utc).strftime('%Y%m%d')}.{ext}"
    return _csv_response(headers, rows, fname) if ext == "csv" else _xlsx_response(headers, rows, fname)


@router.get("/deposits.{ext}")
async def export_deposits(
    ext: str,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(
        select(Deposit).options(joinedload(Deposit.tariff)).order_by(Deposit.id)
    )
    rows = [
        [
            d.id,
            d.user_id,
            d.tariff.name if d.tariff else "",
            str(d.amount),
            d.status,
            d.payout_bank or "",
            d.payout_number or "",
            d.created_at.isoformat() if d.created_at else "",
            d.started_at.isoformat() if d.started_at else "",
            d.ends_at.isoformat() if d.ends_at else "",
        ]
        for d in res.scalars()
    ]
    headers = ["id", "user_id", "tariff", "amount", "status", "bank", "number", "created", "started", "ends"]
    fname = f"deposits_{datetime.now(timezone.utc).strftime('%Y%m%d')}.{ext}"
    return _csv_response(headers, rows, fname) if ext == "csv" else _xlsx_response(headers, rows, fname)


@router.get("/payouts.{ext}")
async def export_payouts(
    ext: str,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(select(Payout).order_by(Payout.id))
    rows = [
        [p.id, p.deposit_id, p.user_id, str(p.amount), p.status, p.due_at.isoformat() if p.due_at else "", p.paid_at.isoformat() if p.paid_at else ""]
        for p in res.scalars()
    ]
    headers = ["id", "deposit_id", "user_id", "amount", "status", "due_at", "paid_at"]
    fname = f"payouts_{datetime.now(timezone.utc).strftime('%Y%m%d')}.{ext}"
    return _csv_response(headers, rows, fname) if ext == "csv" else _xlsx_response(headers, rows, fname)


@router.get("/withdrawals.{ext}")
async def export_withdrawals(
    ext: str,
    _: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    res = await session.execute(select(Withdrawal).order_by(Withdrawal.id))
    rows = [
        [
            w.id, w.user_id, str(w.amount), w.bank, w.number, w.holder_name or "", w.status,
            w.created_at.isoformat() if w.created_at else "",
            w.processed_at.isoformat() if w.processed_at else "",
        ]
        for w in res.scalars()
    ]
    headers = ["id", "user_id", "amount", "bank", "number", "holder", "status", "created", "processed"]
    fname = f"withdrawals_{datetime.now(timezone.utc).strftime('%Y%m%d')}.{ext}"
    return _csv_response(headers, rows, fname) if ext == "csv" else _xlsx_response(headers, rows, fname)
