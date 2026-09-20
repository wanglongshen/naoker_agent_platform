from __future__ import annotations

import math
import secrets
import string
import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.points import PointTransaction, RedeemCode, UserPoints

settings = get_settings()

CODE_ALPHABET = string.ascii_uppercase + string.digits


class InsufficientPointsError(Exception):
    pass


class RedeemCodeError(Exception):
    pass


def tokens_to_points(tokens: int) -> int:
    if tokens <= 0:
        return 0
    return max(1, math.ceil(tokens / settings.points_tokens_per_point))


def _new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"


async def get_or_create_points(db: AsyncSession, user_id: uuid.UUID) -> UserPoints:
    row = await db.get(UserPoints, user_id)
    if row is not None:
        return row
    row = UserPoints(user_id=user_id, balance=settings.points_initial_grant,
                     total_granted=settings.points_initial_grant)
    db.add(row)
    db.add(PointTransaction(
        user_id=user_id, amount=settings.points_initial_grant,
        type="grant", ref="welcome", tokens=None,
    ))
    await db.flush()
    return row


async def deduct_for_run(db: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID, tokens: int) -> int:
    points = tokens_to_points(tokens)
    if points <= 0:
        return 0
    result = await db.execute(
        update(UserPoints)
        .where(UserPoints.user_id == user_id, UserPoints.balance >= points)
        .values(balance=UserPoints.balance - points, total_consumed=UserPoints.total_consumed + points)
        .returning(UserPoints.balance)
    )
    if result.scalar_one_or_none() is None:
        raise InsufficientPointsError(f"balance below {points}")
    db.add(PointTransaction(
        user_id=user_id, amount=-points, type="consume",
        ref=str(run_id), tokens=tokens,
    ))
    await db.commit()
    return points


async def grant_points(db: AsyncSession, user_id: uuid.UUID, points: int, type_: str,
                       ref: str = "", description: str = "") -> int:
    row = await get_or_create_points(db, user_id)
    row.balance += points
    row.total_granted += points
    db.add(PointTransaction(
        user_id=user_id, amount=points, type=type_,
        ref=ref or description,
    ))
    await db.commit()
    return row.balance


async def redeem_code(db: AsyncSession, user_id: uuid.UUID, code: str) -> dict:
    normalized = code.strip().upper()
    row = await db.get(RedeemCode, normalized)
    if row is None:
        raise RedeemCodeError("invalid_code")
    if row.used_by is not None:
        raise RedeemCodeError("code_reused")
    result = await db.execute(
        update(RedeemCode)
        .where(RedeemCode.code == normalized, RedeemCode.used_by.is_(None))
        .values(used_by=user_id)
    )
    if result.rowcount != 1:
        raise RedeemCodeError("code_reused")
    balance = await grant_points(db, user_id, row.points, "redeem", ref=normalized)
    return {"points": row.points, "balance": balance}
