from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any

from app.services.agent.tool_executor import _WebContentParser, _normalize_text

logger = logging.getLogger("web_renderer")

MAX_RENDER_TEXT = 50_000

_DESKTOP_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_VIEWPORTS = [(1366, 768), (1440, 900), (1920, 1080)]


def _pick_user_agent() -> str:
    return random.choice(_DESKTOP_UAS)


def _stealth_js() -> str:
    return """
    delete navigator.webdriver;
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = window.chrome || { runtime: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    """


def _extract_douyin_json(html: str) -> str | None:
    """Extract Douyin embedded JSON (RENDER_DATA or __INITIAL_STATE__)."""
    # RENDER_DATA is HTML-escaped JSON in a script tag
    m = re.search(r'<script[^>]*id="RENDER_DATA"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        raw = m.group(1).strip()
        try:
            unescaped = raw.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("\\u003c", "<").replace("\\u003e", ">")
            data = json.loads(unescaped)
            return json.dumps(data, ensure_ascii=False)[:MAX_RENDER_TEXT]
        except json.JSONDecodeError:
            pass

    # window.__INITIAL_STATE__ assignment
    m2 = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.DOTALL)
    if m2:
        try:
            data = json.loads(m2.group(1))
            return json.dumps(data, ensure_ascii=False)[:MAX_RENDER_TEXT]
        except json.JSONDecodeError:
            pass

    return None


def _detect_platform(url: str) -> str:
    if "douyin.com" in url:
        return "douyin"
    if "xiaohongshu.com" in url:
        return "xiaohongshu"
    return "generic"


def _extract_platform_content(html: str, url: str) -> dict:
    platform = _detect_platform(url)
    parser = _WebContentParser(url)
    parser.feed(html[:100_000])
    text = _normalize_text(" ".join(parser.text_parts))[:MAX_RENDER_TEXT]

    if platform == "douyin":
        douyin_json = _extract_douyin_json(html)
        if douyin_json:
            # JSON contains far more info than visible text
            if len(douyin_json) > len(text):
                text = douyin_json[:MAX_RENDER_TEXT]

    return {
        "title": _normalize_text(" ".join(parser.title_parts))[:300],
        "text": text,
        "url": url,
        "status_code": 200,
        "platform": platform,
    }


def _parse_rendered_html(html: str, url: str, status_code: int = 200) -> dict:
    result = _extract_platform_content(html, url)
    result["status_code"] = status_code
    return result


async def render_page(
    url: str,
    cookies: list[dict] | None = None,
    timeout_seconds: float = 30.0,
    scroll_rounds: int = 4,
) -> dict:
    """Render a JS-heavy page with Playwright + scroll loop.

    Returns parsed content dict including platform-specific extraction.
    Raises RuntimeError on render failure.
    """
    try:
        from patchright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("patchright not installed") from exc

    await asyncio.sleep(random.uniform(1.0, 3.0))  # anti-bot delay

    async with async_playwright() as p:
        from app.core.config import get_browser_channel, get_settings

        _settings = get_settings()
        browser = await p.chromium.launch(
            headless=_settings.web_renderer_headless,
            channel=get_browser_channel(_settings),
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            width, height = random.choice(_VIEWPORTS)
            context = await browser.new_context(
                user_agent=_pick_user_agent(),
                viewport={"width": width, "height": height},
                locale="zh-CN",
            )
            await context.add_init_script(_stealth_js())

            if cookies:
                try:
                    await context.add_cookies(cookies)
                except Exception:
                    logger.warning("web_renderer_add_cookies_failed")

            page = await context.new_page()
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_seconds * 1000))
                status_code = response.status if response else 200

                # Smart wait: networkidle or fixed 3-5s
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    await page.wait_for_timeout(3000)

                # Scroll loop to trigger lazy loading
                for _ in range(scroll_rounds):
                    await page.mouse.wheel(0, random.randint(1500, 3000))
                    await page.wait_for_timeout(random.randint(800, 1200))

                html = await page.content()
                result = _parse_rendered_html(html, str(page.url), status_code)
                return result
            finally:
                await page.close()
        finally:
            await browser.close()


_LOGIN_HINTS = {
    "douyin": ("扫码登录", "验证码登录", "登录后畅享高清视频"),
    "xiaohongshu": ("登录后推荐更懂你的笔记", "新用户可直接登录"),
}

_SAMPLE_KEYS = {
    "douyin": {
        "title": ("desc",),
        "author": ("author", "nickname"),
        "url": ("share_url",),
        "likes": ("statistics", "digg_count"),
        "collect": ("statistics", "collect_count"),
        "comment": ("statistics", "comment_count"),
        "cover": ("video", "cover", "url_list"),
        "tags": ("text_extra",),
    },
    "xiaohongshu": {
        "title": ("title",),
        "author": ("user", "nickname"),
        "url": ("noteId",),
        "likes": ("interactInfo", "likedCount"),
        "collect": ("interactInfo", "collectedCount"),
        "comment": ("interactInfo", "commentCount"),
        "cover": ("imageList",),
        "tags": ("tagList",),
    },
}


def _json_get(node: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _sample_url(platform: str, url_or_id: Any) -> str:
    if not url_or_id:
        if platform == "douyin":
            return "https://www.douyin.com"
        return "https://www.xiaohongshu.com"
    if isinstance(url_or_id, str) and "://" in url_or_id:
        return url_or_id
    if platform == "douyin":
        return f"https://www.douyin.com/video/{url_or_id}"
    return f"https://www.xiaohongshu.com/explore/{url_or_id}"


def _extract_samples_from_json(data: Any, platform: str) -> list[dict[str, Any]]:
    """启发式递归提取样本：遍历 JSON 树，收集含标题/账号键的节点。"""
    keys = _SAMPLE_KEYS[platform]
    samples: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        title = _json_get(node, keys["title"])
        if isinstance(title, str) and title.strip():
            url = _sample_url(platform, _json_get(node, keys["url"]))
            if url and url not in seen_urls:
                seen_urls.add(url)
                author = _json_get(node, keys["author"])
                likes = _json_get(node, keys["likes"])
                collect = _json_get(node, keys["collect"])
                comment = _json_get(node, keys["comment"])
                cover = _json_get(node, keys["cover"])
                tags = _json_get(node, keys["tags"])
                samples.append(
                    {
                        "title": title.strip()[:200],
                        "author": str(author).strip()[:80] if author else "",
                        "url": url,
                        "likes": int(likes) if isinstance(likes, (int, float, str)) and str(likes).isdigit() else None,
                        "collect_count": int(collect) if isinstance(collect, (int, float, str)) and str(collect).isdigit() else None,
                        "comment_count": int(comment) if isinstance(comment, (int, float, str)) and str(comment).isdigit() else None,
                        "cover_image": _first_cover(platform, cover),
                        "topic_tags": _extract_tags(platform, tags),
                    }
                )
        for value in node.values():
            walk(value)

    walk(data)
    return samples


def _first_cover(platform: str, cover: Any) -> str | None:
    if platform == "douyin":
        if isinstance(cover, list) and cover:
            return str(cover[0])
        return None
    if isinstance(cover, list) and cover:
        for item in cover:
            if isinstance(item, dict):
                u = item.get("urlDefault") or item.get("url") or item.get("url_pre")
                if u:
                    return str(u)
    return None


def _extract_tags(platform: str, tags: Any) -> list[str]:
    if platform == "douyin":
        if isinstance(tags, list):
            out = []
            for item in tags:
                if isinstance(item, dict):
                    name = item.get("hashtag_name")
                    if name:
                        out.append(str(name))
            return out[:20]
        return []
    if isinstance(tags, list):
        out = []
        for item in tags:
            if isinstance(item, dict):
                name = item.get("name")
                if name:
                    out.append(str(name))
        return out[:20]
    return []


def _detect_login_wall(platform: str, text: str) -> bool:
    hints = _LOGIN_HINTS.get(platform, ())
    return any(hint in text for hint in hints)


def _extract_links(html: str, platform: str) -> list[str]:
    pattern = {
        "douyin": r"https?://www\.douyin\.com/video/\d+",
        "xiaohongshu": r"https?://www\.xiaohongshu\.com/(?:explore|discovery/item)/[A-Za-z0-9]+",
    }[platform]
    return list(dict.fromkeys(re.findall(pattern, html)))


SEARCH_URLS = {
    "xiaohongshu": "https://www.xiaohongshu.com/search_result?keyword={keyword}",
    "douyin": "https://www.douyin.com/search/{keyword}",
}

_SEARCH_SCROLL_ROUNDS = 8


async def search_platform(
    platform: str,
    keyword: str,
    max_results: int = 30,
    cookies: list[dict] | None = None,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """渲染平台搜索页并滚动加载，提取样本列表。"""
    from urllib.parse import quote

    url = SEARCH_URLS[platform].format(keyword=quote(keyword, safe=""))

    import playwright.async_api as playwright_async

    async with playwright_async.async_playwright() as p:
        from app.core.config import get_browser_channel, get_settings

        _settings = get_settings()
        browser = await p.chromium.launch(
            headless=_settings.web_renderer_headless,
            channel=get_browser_channel(_settings),
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            width, height = random.choice(_VIEWPORTS)
            context = await browser.new_context(
                user_agent=_pick_user_agent(),
                viewport={"width": width, "height": height},
                locale="zh-CN",
            )
            await context.add_init_script(_stealth_js())
            if cookies:
                try:
                    await context.add_cookies(cookies)
                except Exception:
                    logger.warning("web_renderer_add_cookies_failed")
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    await page.wait_for_timeout(4000)

                samples: list[dict[str, Any]] = []
                for _round in range(_SEARCH_SCROLL_ROUNDS):
                    await page.mouse.wheel(0, random.randint(1500, 3000))
                    await page.wait_for_timeout(random.randint(900, 1400))
                    html = await page.content()
                    new_samples = _parse_search_html(html, platform, url)
                    for sample in new_samples:
                        if sample["url"] and not any(
                            s["url"] == sample["url"] for s in samples
                        ):
                            samples.append(sample)
                    if len(samples) >= max_results or not new_samples:
                        break
                    if _detect_login_wall(platform, " ".join(s["title"] for s in new_samples)):
                        break
                samples = samples[:max_results]
                return {
                    "samples": samples,
                    "sample_count": len(samples),
                    "login_required": _detect_login_wall(platform, html),
                    "platform": platform,
                }
            finally:
                await page.close()
        finally:
            await browser.close()


def _parse_search_html(html: str, platform: str, page_url: str) -> list[dict[str, Any]]:
    """搜索页 HTML → 样本列表。优先 JSON，兜底文本+链接。"""
    raw_json = None
    if platform == "douyin":
        raw = _extract_douyin_json(html)
        if raw:
            try:
                raw_json = json.loads(raw)
            except json.JSONDecodeError:
                raw_json = None
    else:
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", html, re.DOTALL)
        if m:
            try:
                raw_json = json.loads(m.group(1))
            except json.JSONDecodeError:
                raw_json = None

    if raw_json:
        samples = _extract_samples_from_json(raw_json, platform)
        if samples:
            return samples

    parser = _WebContentParser(page_url)
    parser.feed(html[:100_000])
    text = _normalize_text(" ".join(parser.text_parts))
    samples = []
    for link in _extract_links(html, platform):
        samples.append({"title": text[:80], "author": "", "url": link, "likes": None})
    logger.warning("platform_search_parse_fallback", extra={"platform": platform})
    return samples


def _extract_detail_from_json(data: Any, platform: str) -> dict[str, Any]:
    """详情页 JSON → 详情字段。返回 dict，键与卡片字段一致（详情为准）。"""
    keys = _SAMPLE_KEYS[platform]
    out: dict[str, Any] = {}

    def find(node: Any) -> None:
        nonlocal out
        if isinstance(node, list):
            for item in node:
                find(item)
            return
        if not isinstance(node, dict):
            return
        title = _json_get(node, keys["title"])
        if isinstance(title, str) and title.strip() and not out.get("title"):
            url = _sample_url(platform, _json_get(node, keys["url"]))
            if url:
                out["title"] = title.strip()[:200]
                out["url"] = url
                author = _json_get(node, keys["author"])
                if author:
                    out["author"] = str(author).strip()[:80]
                likes = _json_get(node, keys["likes"])
                if isinstance(likes, (int, float, str)) and str(likes).isdigit():
                    out["like_count"] = int(likes)
                collect = _json_get(node, keys["collect"])
                if isinstance(collect, (int, float, str)) and str(collect).isdigit():
                    out["collect_count"] = int(collect)
                comment = _json_get(node, keys["comment"])
                if isinstance(comment, (int, float, str)) and str(comment).isdigit():
                    out["comment_count"] = int(comment)
                out["cover_image"] = _first_cover(platform, _json_get(node, keys["cover"]))
                out["topic_tags"] = _extract_tags(platform, _json_get(node, keys["tags"]))
                desc = _json_get(node, ("desc",)) or _json_get(node, ("note", "desc",))
                if isinstance(desc, str) and desc.strip():
                    out["content"] = desc.strip()[:20000]
                if platform == "xiaohongshu":
                    t = _json_get(node, ("time",))
                    if isinstance(t, (int, float)) and t:
                        out["published_at"] = _ts_to_iso(t, millis=True)
                else:
                    t = _json_get(node, ("create_time",))
                    if isinstance(t, (int, float)) and t:
                        out["published_at"] = _ts_to_iso(t, millis=False)
        for value in node.values():
            find(value)

    find(data)
    return out


def _ts_to_iso(ts: float, millis: bool = False) -> str:
    from datetime import UTC, datetime

    if millis:
        ts = ts / 1000.0
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def _extract_detail_from_html(html: str, platform: str, page_url: str) -> dict[str, Any]:
    """详情页 HTML 兜底：文本 + 链接，尽力取标题/正文。"""
    parser = _WebContentParser(page_url)
    parser.feed(html[:200_000])
    text = _normalize_text(" ".join(parser.text_parts))
    title = ""
    content = ""
    if text:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            title = lines[0][:200]
            content = "\n".join(lines[1:])[:20000]
    return {"title": title, "content": content, "url": page_url}


async def fetch_note_detail(
    platform: str,
    url: str,
    cookies: list[dict] | None = None,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """渲染笔记详情页并提取字段。错误以 error 字段返回，不抛异常。"""
    import playwright.async_api as playwright_async
    from app.core.config import get_browser_channel, get_settings

    _settings = get_settings()
    try:
        async with playwright_async.async_playwright() as p:
            channel = get_browser_channel()
            browser = await p.chromium.launch(
                channel=channel,
                headless=_settings.web_renderer_headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=_pick_user_agent(),
                locale="zh-CN",
            )
            if cookies:
                try:
                    await context.add_cookies(cookies)
                except Exception:
                    logger.warning("web_renderer_add_cookies_failed")
            page = await context.new_page()
            await page.add_init_script(_stealth_js())
            html = ""
            try:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_seconds * 1000))
                except Exception:
                    await page.goto(url, wait_until="commit", timeout=int(timeout_seconds * 1000))
                await page.wait_for_timeout(3000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)
                html = await page.content()
            finally:
                await browser.close()
    except Exception as exc:
        return {
            "platform": platform,
            "url": url,
            "title": None,
            "content": None,
            "published_at": None,
            "like_count": None,
            "collect_count": None,
            "comment_count": None,
            "topic_tags": [],
            "author": None,
            "image_urls": [],
            "login_required": False,
            "error": f"render failed: {type(exc).__name__}: {str(exc)[:200]}",
        }

    login_required = _detect_login_wall(platform, html)
    detail: dict[str, Any] = {}
    if platform == "douyin":
        raw = _extract_douyin_json(html)
        if raw:
            try:
                detail = _extract_detail_from_json(json.loads(raw), platform)
            except (json.JSONDecodeError, TypeError):
                detail = {}
    else:
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});\s*</script>", html, re.DOTALL)
        if m:
            try:
                detail = _extract_detail_from_json(json.loads(m.group(1)), platform)
            except (json.JSONDecodeError, TypeError):
                detail = {}
    if not detail.get("title"):
        fallback = _extract_detail_from_html(html, platform, url)
        detail = {**fallback, **detail}
    return {
        "platform": platform,
        "url": url,
        "title": detail.get("title"),
        "content": detail.get("content"),
        "published_at": detail.get("published_at"),
        "like_count": detail.get("like_count"),
        "collect_count": detail.get("collect_count"),
        "comment_count": detail.get("comment_count"),
        "topic_tags": detail.get("topic_tags") or [],
        "author": detail.get("author"),
        "image_urls": [],
        "login_required": login_required,
        "error": None,
    }
