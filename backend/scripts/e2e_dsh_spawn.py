# -*- coding: utf-8 -*-
"""端到端：admin 登录 → restart DSH 实例（真实 spawn dev_bin）→ 轮询状态 → proxy 可达。"""
import asyncio
import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE) as c:
        r = await c.post("/api/auth/login",
                         json={"username": "admin", "password": "ChangeMe-Strong1"})
        print("login:", r.status_code)
        if r.status_code != 200:
            print(r.text[:300])
            return 1
        csrf = (await c.get("/api/auth/csrf")).json().get("data", {}).get("token")
        print("csrf:", bool(csrf))
        # restart (spawn DSH)
        r = await c.post("/api/dsh/instances/me/restart",
                         headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"},
                         cookies=c.cookies)
        print("restart:", r.status_code, str(r.json())[:200])
        # poll status up to 90s
        for i in range(18):
            await asyncio.sleep(5)
            s = (await c.get("/api/dsh/instances/me")).json()
            data = s.get("data") or s
            print(f"  poll{i}: state={data.get('state')} port={data.get('port')} hint={data.get('error_hint')}")
            if data.get("state") == "running":
                break
        # proxy reachable?
        uid = data.get("user_id")
        r = await c.get(f"/api/dsh-proxy/{uid}/")
        print("proxy:",
              r.status_code, (len(r.text), r.text[:80]))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
