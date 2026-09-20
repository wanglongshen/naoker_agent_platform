import asyncio
import httpx


async def main():
    async with httpx.AsyncClient(timeout=10) as client:
        async with client.stream("GET", "http://localhost:8000/api/stream-debug") as resp:
            t0 = asyncio.get_event_loop().time()
            print(f"Status: {resp.status_code}")
            async for line in resp.aiter_lines():
                t = asyncio.get_event_loop().time() - t0
                if line.strip():
                    print(f"[{t:.3f}s] {line[:100]}")


asyncio.run(main())
