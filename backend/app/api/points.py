from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import get_current_user
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.points import PointTransaction, UserPoints
from app.models.rbac import User
from app.schemas.common import success
from app.services.points import RedeemCodeError, get_or_create_points, redeem_code

router = APIRouter(tags=["Points"])


class RedeemRequest(BaseModel):
    code: str


@router.get("/points/me")
async def my_points(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_or_create_points(db, current_user.id)
    recent_result = await db.execute(
        select(PointTransaction)
        .where(PointTransaction.user_id == current_user.id)
        .order_by(PointTransaction.created_at.desc())
        .limit(20)
    )
    recent = [
        {
            "id": str(t.id),
            "amount": t.amount,
            "type": t.type,
            "ref": t.ref,
            "tokens": t.tokens,
            "created_at": t.created_at.isoformat() if t.created_at else "",
        }
        for t in recent_result.scalars().all()
    ]
    await db.commit()
    return success(request, {
        "balance": row.balance,
        "total_granted": row.total_granted,
        "total_consumed": row.total_consumed,
        "recent": recent,
    })


@router.get("/points/usage")
async def points_usage(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    start = datetime.now(UTC) - timedelta(days=29)
    result = await db.execute(
        select(
            func.date(PointTransaction.created_at).label("day"),
            func.coalesce(func.sum(PointTransaction.tokens), 0).label("tokens"),
            func.coalesce(func.sum(PointTransaction.amount), 0).label("points"),
        )
        .where(
            PointTransaction.user_id == current_user.id,
            PointTransaction.type == "consume",
            PointTransaction.created_at >= start,
        )
        .group_by(func.date(PointTransaction.created_at))
        .order_by(func.date(PointTransaction.created_at))
    )
    by_day = {day: (tokens, points) for day, tokens, points in result.all()}
    days = []
    for offset in range(30):
        day = (datetime.now(UTC) - timedelta(days=offset)).date()
        tokens, points = by_day.get(day, (0, 0))
        days.append({"date": str(day), "tokens": int(tokens), "points": int(points)})
    days.reverse()
    return success(request, {"days": days})


@router.post("/points/redeem")
async def redeem(
    request: Request,
    data: RedeemRequest,
    current_user: User = Depends(get_current_user),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await redeem_code(db, current_user.id, data.code)
    except RedeemCodeError as exc:
        code = str(exc)
        raise ApiError(status_code=400, code=code.upper(), message="兑换码无效或已被使用")
    return success(request, result)
