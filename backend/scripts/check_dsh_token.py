# -*- coding: utf-8 -*-
"""端到端验证：DSH connector 平台令牌 访问 files 与 proxy 路由。"""
import asyncio
import sys
import uuid

import httpx

sys.path.insert(0, ".")
from app.core.security import mint_platform_token, decode_platform_token  # noqa: E402
from app.db.session import async_session_factory  # noqa: E402
from sqlalchemy import select  # noqa: E402
from app.models.rbac import User  # noqa: E402

BASE = "http://127.0.0.1:8000"


async def main():
    async with async_session_factory() as s:
        uid = (await s.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    tok = mint_platform_token(str(uid), 300)
    assert decode_platform_token(tok) == str(uid)
    assert decode_platform_token("junk-token") is None
    async with httpx.AsyncClient(base_url=BASE) as c:
        r = await c.get("/api/files", params={"page_size": 1},
                        headers={"X-Platform-Token": tok})
        print("files(token):", r.status_code, str(r.text)[:120])
        r2 = await c.get("/api/files", params={"page_size": 1})
        print("files(no auth):", r2.status_code)
        r3 = await c.get(f"/api/dsh-proxy/{uid}/", headers={"X-Platform-Token": tok})
        print("proxy(token):", r3.status_code)
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
