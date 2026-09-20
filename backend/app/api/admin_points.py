from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.csrf import require_csrf
from app.core.dependencies import require_super_admin
from app.core.errors import ApiError
from app.db.session import get_db
from app.models.points import RedeemCode, UserPoints
from app.models.rbac import User
from app.schemas.common import success
from app.services.points import _new_code, grant_points

router = APIRouter(tags=["AdminPoints"])


class GrantRequest(BaseModel):
    user_id: uuid.UUID
    points: int
    description: str = ""


class CreateCodesRequest(BaseModel):
    points: int
    count: int = 1


@router.get("/admin/points/all")
async def admin_points_all(
    request: Request,
    _admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserPoints))
    users = [
        {"user_id": str(p.user_id), "balance": p.balance}
        for p in result.scalars().all()
    ]
    return success(request, {"users": users})


@router.post("/admin/points/grant")
async def admin_grant(
    request: Request,
    data: GrantRequest,
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    if data.points <= 0 or data.points > 1_000_000:
        raise ApiError(status_code=400, code="INVALID_POINTS", message="积点数量无效")
    balance = await grant_points(db, data.user_id, data.points, "grant", ref="admin", description=data.description)
    return success(request, {"balance": balance})


@router.post("/admin/redeem-codes")
async def admin_create_codes(
    request: Request,
    data: CreateCodesRequest,
    _admin: User = Depends(require_super_admin),
    _csrf=Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    if data.points <= 0 or data.points > 1_000_000 or data.count < 1 or data.count > 50:
        raise ApiError(status_code=400, code="INVALID_INPUT", message="参数无效")
    codes = []
    for _ in range(data.count):
        code = _new_code()
        db.add(RedeemCode(code=code, points=data.points, created_by=_admin.id))
        codes.append(code)
    await db.commit()
    return success(request, {"codes": codes})


@router.get("/admin/redeem-codes")
async def admin_list_codes(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    total = len((await db.execute(select(RedeemCode.code))).all())
    result = await db.execute(
        select(RedeemCode).order_by(RedeemCode.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    codes = [
        {
            "code": c.code,
            "points": c.points,
            "used_by": str(c.used_by) if c.used_by else None,
            "used_at": c.used_at.isoformat() if c.used_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else "",
        }
        for c in result.scalars().all()
    ]
    return success(request, {"codes": codes, "total": total})
