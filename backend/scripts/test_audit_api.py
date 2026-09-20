import asyncio, sys, httpx, json
sys.path.insert(0, ".")

async def test():
    # First login to get token
    async with httpx.AsyncClient() as c:
        # Login
        r = await c.post("http://localhost:8000/api/auth/login", json={"username": "admin", "password": "ChangeMe-Strong1"})
        print(f"Login: {r.status_code}")
        cookies = r.cookies
        
        # Get CSRF token
        r2 = await c.get("http://localhost:8000/api/auth/csrf", cookies=cookies)
        print(f"CSRF: {r2.status_code}")
        csrf_data = r2.json()
        csrf_token = csrf_data.get("data", {}).get("token", "")
        
        # Hit audit API
        r3 = await c.get("http://localhost:8000/api/agent/audit/sessions?page=1&page_size=3", 
                         cookies=cookies,
                         headers={"X-CSRF-Token": csrf_token})
        print(f"Audit: {r3.status_code}")
        if r3.status_code != 200:
            print(f"Body: {r3.text[:500]}")
        else:
            data = r3.json()
            items = data.get("data", {}).get("items", [])
            print(f"Sessions: {len(items)}")
            for item in items[:3]:
                print(f"  {item.get('title','?')[:40]} | dn={item.get('owner_display_name','?')}")

asyncio.run(test())
