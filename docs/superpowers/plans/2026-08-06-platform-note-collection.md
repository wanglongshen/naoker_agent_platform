# 平台笔记采集入库（小红书/抖音 9 字段符合）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 小红书/抖音平台搜索的笔记样本完整落库（9 字段 + 详情页补齐），闸门从 150 硬阈值改为 40 保底放行，提供 owner 隔离的查询接口。

**Architecture:** 采集链路扩展现有 `fetch_platform_search` 工具：卡片字段扩展 → 受限并发抓详情页（新 `/detail` 端点）→ upsert 入库 `platform_notes` 表 → 服务端查库统计该平台去重总数（`platform_total`）幂等累计 → 闸门按 40 保底判定。

**Tech Stack:** FastAPI / SQLAlchemy 2.0 async / alembic / Playwright / asyncio

## Global Constraints

- 40 保底放行：清洗后有效样本 <40 → 挂起等确认；≥40 → 放行（40-149 观察提示差距，不强制挂起）——需求文档《会议记录功能补充 v1》3.4
- 9 字段：title / content / image_urls / like_count / collect_count / comment_count / author / published_at / topic_tags + url（去重键）
- 去重键 `(owner_user_id, url)` 唯一
- 详情抓取：并发 3 + 同平台 ≥1s 间隔 + 单条 8s 超时；失败/登录墙留空不阻塞，计 `detail_failed`
- 入库失败不阻塞采集（try/except + 日志）
- 累计口径：`platform_total` = 服务端查库去重 url 数（幂等覆盖，不叠加）
- `project_id` 列预留恒 NULL（**无 FK**——项目表不存在，注释注明）
- 详情页/搜索页请求一律注入 owner 的 cookie（无 cookie 则渲染后检测登录墙）
- /detail url 校验：仅 http(s) 且 host ∈ {www.xiaohongshu.com, www.douyin.com}
- 查询接口 owner 隔离服务端强制；content 返回截断 500 字
- 测试命令均从 `C:\01_agent_loop_pro\backend` 运行（conda env 01-rbac）：`python -X utf8 -m pytest <file> -q`
- 提交时只 `git add` 自己任务的文件（工作区常有其他会话的文件）

---

### Task 1: platform_notes 模型 + alembic 迁移

**Files:**
- Create: `backend/app/models/platform_note.py`
- Create: `backend/alembic/versions/a1b2c3d4e5f6_add_platform_notes.py`
- Modify: `backend/app/models/__init__.py`（聚合导入）
- Test: `backend/tests/test_platform_note_model.py`

**Interfaces:**
- Produces: `PlatformNote` ORM 类（字段：id/owner_user_id/project_id/platform/keyword/url/title/content/image_urls/like_count/collect_count/comment_count/author/published_at/topic_tags/collected_at/updated_at；唯一约束 uq_platform_notes_owner_url；索引 ix_platform_notes_owner_platform / ix_platform_notes_owner_keyword）

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_platform_note_model.py`：

```python
import uuid
from datetime import UTC, datetime

import pytest


@pytest.mark.asyncio
async def test_platform_note_create_and_unique_constraint(api_db):
    from app.models.platform_note import PlatformNote
    from sqlalchemy import select

    owner = uuid.uuid4()
    now = datetime.now(UTC)
    note = PlatformNote(
        owner_user_id=owner,
        platform="xiaohongshu",
        keyword="成毅",
        url="https://www.xiaohongshu.com/explore/abc123",
        title="测试笔记",
        content="正文内容",
        image_urls=["https://img.example.com/1.jpg"],
        like_count=10,
        collect_count=5,
        comment_count=2,
        author="作者A",
        topic_tags=["成毅", "旅行"],
        collected_at=now,
    )
    api_db.add(note)
    await api_db.commit()

    rows = (await api_db.execute(select(PlatformNote).where(PlatformNote.owner_user_id == owner))).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "测试笔记"
    assert rows[0].image_urls == ["https://img.example.com/1.jpg"]
    assert rows[0].topic_tags == ["成毅", "旅行"]
    assert rows[0].project_id is None

    # 同 owner 同 url 违反唯一约束
    dup = PlatformNote(
        owner_user_id=owner,
        platform="douyin",
        keyword="x",
        url="https://www.xiaohongshu.com/explore/abc123",
        title="重复",
    )
    api_db.add(dup)
    with pytest.raises(Exception):
        await api_db.commit()
    await api_db.rollback()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -X utf8 -m pytest tests/test_platform_note_model.py -q`
Expected: FAIL（ModuleNotFoundError / 无表 platform_notes）

- [ ] **Step 3: 创建模型**

创建 `backend/app/models/platform_note.py`：

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PlatformNote(Base):
    """平台笔记样本（小红书/抖音采集）。project_id 为项目隔离预留，本轮恒 NULL（无 FK，项目表未建）。"""

    __tablename__ = "platform_notes"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "url", name="uq_platform_notes_owner_url"),
        Index("ix_platform_notes_owner_platform", "owner_user_id", "platform"),
        Index("ix_platform_notes_owner_keyword", "owner_user_id", "keyword"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collect_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    topic_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
```

修改 `backend/app/models/__init__.py`：在现有导入后加 `from app.models.platform_note import PlatformNote`，并把 `PlatformNote` 加入 `__all__`。

- [ ] **Step 4: 运行确认通过**

Run: `python -X utf8 -m pytest tests/test_platform_note_model.py -q`
Expected: PASS

- [ ] **Step 5: 写 alembic 迁移**

创建 `backend/alembic/versions/a1b2c3d4e5f6_add_platform_notes.py`：

```python
"""add platform_notes table

Revision ID: a1b2c3d4e5f6
Revises: 523b18158695
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "523b18158695"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("keyword", sa.String(200), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("image_urls", postgresql.JSONB(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("collect_count", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("published_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("topic_tags", postgresql.JSONB(), nullable=True),
        sa.Column("collected_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_user_id", "url", name="uq_platform_notes_owner_url"),
    )
    op.create_index("ix_platform_notes_owner_platform", "platform_notes", ["owner_user_id", "platform"])
    op.create_index("ix_platform_notes_owner_keyword", "platform_notes", ["owner_user_id", "keyword"])


def downgrade() -> None:
    op.drop_index("ix_platform_notes_owner_keyword", table_name="platform_notes")
    op.drop_index("ix_platform_notes_owner_platform", table_name="platform_notes")
    op.drop_table("platform_notes")
```

- [ ] **Step 6: 验证迁移可生成**

Run: `python -X utf8 -m alembic upgrade head`
Expected: 无错误输出；表创建成功。随后 Run: `python -X utf8 -c "import asyncio; from app.db.session import async_session_factory; from sqlalchemy import text; asyncio.run((lambda s: None)(None))"` 不需要——直接用 SQL 验证：
`python -X utf8 -c "import asyncio; from app.db.session import async_session_factory; from sqlalchemy import text
async def m():
    async with async_session_factory() as s:
        r = await s.execute(text(\"SELECT count(*) FROM pg_tables WHERE tablename='platform_notes'\"))
        print('platform_notes exists:', r.scalar() == 1)
asyncio.run(m())"`
Expected: `platform_notes exists: True`

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/platform_note.py backend/app/models/__init__.py backend/alembic/versions/a1b2c3d4e5f6_add_platform_notes.py backend/tests/test_platform_note_model.py
git commit -m "feat: platform_notes model and alembic migration"
```

---

### Task 2: 解析器字段扩展 + /detail 端点

**Files:**
- Modify: `backend/app/services/agent/web_renderer.py`（`_SAMPLE_KEYS`、`_extract_samples_from_json`、新增 `fetch_note_detail` + `_extract_detail_from_json` + `_extract_detail_from_html`）
- Modify: `backend/app/workers/web_renderer.py`（新增 `/detail` 端点 + `NoteDetailRequest`）
- Test: `backend/tests/test_web_renderer.py`

**Interfaces:**
- Consumes: 现有 `render_page`、`_extract_douyin_json`、`_WebContentParser`、`_normalize_text`、`_detect_login_wall`（均在同一文件）
- Produces: `fetch_note_detail(url: str, platform: str, cookies: list[dict] | None, timeout_seconds: float = 60.0) -> dict`（键：platform/url/title/content/published_at/like_count/collect_count/comment_count/topic_tags/author/image_urls/login_required/error）；workers `POST /detail` 端点（请求 `{platform, url, cookies?}`，响应同上结构 + error: None 或 error: str）

- [ ] **Step 1: 写失败测试（卡片字段扩展）**

在 `backend/tests/test_web_renderer.py` 追加：

```python
def test_extract_samples_includes_extended_fields():
    from app.services.agent.web_renderer import _extract_samples_from_json

    payload = {
        "data": {
            "noteList": [
                {
                    "title": "秋季穿搭指南",
                    "user": {"nickname": "穿搭博主"},
                    "noteId": "note_a1",
                    "interactInfo": {"likedCount": 100, "collectedCount": 50, "commentCount": 8},
                    "imageList": [{"urlDefault": "https://img.example.com/a.jpg"}],
                    "tagList": [{"name": "穿搭"}, {"name": "秋季"}],
                }
            ]
        }
    }
    samples = _extract_samples_from_json(payload, "xiaohongshu")
    assert len(samples) == 1
    s = samples[0]
    assert s["title"] == "秋季穿搭指南"
    assert s["url"] == "https://www.xiaohongshu.com/explore/note_a1"
    assert s["likes"] == 100
    assert s["collect_count"] == 50
    assert s["comment_count"] == 8
    assert s["cover_image"] == "https://img.example.com/a.jpg"
    assert s["topic_tags"] == ["穿搭", "秋季"]


def test_extract_samples_douyin_extended_fields():
    from app.services.agent.web_renderer import _extract_samples_from_json

    payload = {
        "aweme_list": [
            {
                "desc": "抖音视频标题",
                "author": {"nickname": "作者B"},
                "share_url": "https://www.douyin.com/video/888",
                "statistics": {"digg_count": 200, "collect_count": 30, "comment_count": 5},
                "video": {"cover": {"url_list": ["https://img.example.com/d.jpg"]}},
                "text_extra": [{"hashtag_name": "旅行"}],
            }
        ]
    }
    samples = _extract_samples_from_json(payload, "douyin")
    assert len(samples) == 1
    s = samples[0]
    assert s["likes"] == 200
    assert s["collect_count"] == 30
    assert s["comment_count"] == 5
    assert s["cover_image"] == "https://img.example.com/d.jpg"
    assert s["topic_tags"] == ["旅行"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -X utf8 -m pytest tests/test_web_renderer.py -q`
Expected: FAIL（collect_count/cover_image 缺失）

- [ ] **Step 3: 实现卡片字段扩展**

修改 `backend/app/services/agent/web_renderer.py`：

`_SAMPLE_KEYS` 改为：

```python
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
```

`_extract_samples_from_json` 中样本构造替换为：

```python
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
```

在同文件新增两个辅助函数（放在 `_extract_samples_from_json` 之后）：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `python -X utf8 -m pytest tests/test_web_renderer.py -q`
Expected: PASS

- [ ] **Step 5: 写失败测试（详情提取）**

继续追加：

```python
def test_extract_detail_from_douyin_json():
    from app.services.agent.web_renderer import _extract_detail_from_json

    payload = {
        "aweme_detail": {
            "desc": "详情标题",
            "author": {"nickname": "作者C"},
            "create_time": 1750000000,
            "statistics": {"digg_count": 999, "collect_count": 88, "comment_count": 66},
            "text_extra": [{"hashtag_name": "美食"}],
        }
    }
    d = _extract_detail_from_json(payload, "douyin")
    assert d["title"] == "详情标题"
    assert d["author"] == "作者C"
    assert d["like_count"] == 999
    assert d["collect_count"] == 88
    assert d["comment_count"] == 66
    assert d["topic_tags"] == ["美食"]
    assert d["published_at"] is not None


def test_extract_detail_from_xiaohongshu_json():
    from app.services.agent.web_renderer import _extract_detail_from_json

    payload = {
        "note": {
            "title": "小红书详情标题",
            "desc": "这是一段正文内容，包含完整描述。",
            "user": {"nickname": "作者D"},
            "time": 1750000000000,
            "interactInfo": {"likedCount": 11, "collectedCount": 22, "commentCount": 33},
            "tagList": [{"name": "护肤"}],
        }
    }
    d = _extract_detail_from_json(payload, "xiaohongshu")
    assert d["title"] == "小红书详情标题"
    assert d["content"] == "这是一段正文内容，包含完整描述。"
    assert d["author"] == "作者D"
    assert d["like_count"] == 11
    assert d["collect_count"] == 22
    assert d["comment_count"] == 33
    assert d["topic_tags"] == ["护肤"]
    assert d["published_at"] is not None
```

- [ ] **Step 6: 运行确认失败**

Run: `python -X utf8 -m pytest tests/test_web_renderer.py -q`
Expected: FAIL（_extract_detail_from_json 不存在）

- [ ] **Step 7: 实现详情提取与 fetch_note_detail**

在 `backend/app/services/agent/web_renderer.py` 追加：

```python
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
                await context.add_cookies(cookies)
            page = await context.new_page()
            await page.add_init_script(_stealth_js)
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
```

确认文件顶部有 `import json`、`import re`（已有 `_extract_douyin_json` 使用它们；如无则补）。

- [ ] **Step 8: 运行确认通过**

Run: `python -X utf8 -m pytest tests/test_web_renderer.py -q`
Expected: PASS

- [ ] **Step 9: /detail 端点 + 测试**

在 `backend/app/workers/web_renderer.py` 的 SearchRequest 后加：

```python
class NoteDetailRequest(BaseModel):
    platform: str = Field(pattern="^(xiaohongshu|douyin)$")
    url: str = Field(min_length=1, max_length=2000)
    cookies: list[dict] | None = None


_ALLOWED_DETAIL_HOSTS = ("www.xiaohongshu.com", "www.douyin.com", "xiaohongshu.com", "douyin.com")


def _validate_detail_url(url: str) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("unsupported_url_scheme")
    host = (parsed.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in _ALLOWED_DETAIL_HOSTS):
        raise ValueError("unsupported_url_host")
```

端点（加在 search 端点后）：

```python
@app.post("/detail")
async def note_detail(req: NoteDetailRequest) -> dict:
    from app.core.config import get_settings

    try:
        _validate_detail_url(req.url)
    except ValueError as exc:
        return {
            "platform": req.platform,
            "url": req.url,
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
            "error": str(exc),
        }
    timeout = get_settings().web_renderer_search_timeout_seconds
    try:
        result = await fetch_note_detail(
            req.platform, req.url, req.cookies, timeout_seconds=timeout
        )
        result["error"] = result.get("error") or None
        return result
    except Exception as exc:
        return {
            "platform": req.platform,
            "url": req.url,
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
            "error": f"internal: {type(exc).__name__}: {str(exc)[:200]}",
        }
```

workers 文件顶部 import 增加 `from app.services.agent.web_renderer import fetch_note_detail`（检查现有 import 行，把 fetch_note_detail 加进去）。

在 `backend/tests/test_web_renderer.py` 追加：

```python
def test_detail_url_validation():
    from app.workers.web_renderer import _validate_detail_url
    from urllib.parse import urlparse

    _validate_detail_url("https://www.xiaohongshu.com/explore/abc")
    _validate_detail_url("https://www.douyin.com/video/123")
    for bad in ("ftp://www.xiaohongshu.com/x", "https://evil.com/x", "https://www.baidu.com/x"):
        try:
            _validate_detail_url(bad)
            raise AssertionError(f"must reject {bad}")
        except ValueError:
            pass


def test_detail_endpoint_rejects_foreign_host(monkeypatch):
    from fastapi.testclient import TestClient
    import app.workers.web_renderer as ww

    resp = TestClient(ww.app).post(
        "/detail",
        json={"platform": "xiaohongshu", "url": "https://evil.com/x"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "error" in body
    assert "unsupported_url_host" in body["error"]
```

- [ ] **Step 10: 运行确认通过**

Run: `python -X utf8 -m pytest tests/test_web_renderer.py -q`
Expected: PASS（含既有 /search 测试）

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/agent/web_renderer.py backend/app/workers/web_renderer.py backend/tests/test_web_renderer.py
git commit -m "feat: note detail fetch endpoint and extended sample fields"
```

---

### Task 3: 工具层——详情抓取 + 清洗 + 入库

**Files:**
- Create: `backend/app/repositories/platform_note_repository.py`
- Modify: `backend/app/services/agent/tool_executor.py`（`_fetch_platform_search` 扩展）
- Test: `backend/tests/test_agent_tool_files.py`（追加 TestPlatformNotePersist）

**Interfaces:**
- Consumes: `fetch_note_detail`（Task 2 产出）、`POST /detail` 端点契约（Task 2）
- Produces: `platform_note_repository.upsert(session, owner_user_id, platform, keyword, sample: dict) -> bool`；`platform_note_repository.count_platform(session, owner_user_id, platform) -> int`；`_fetch_platform_search` 返回新增键 `stored_count` / `detail_failed` / `platform_total`，note 文案更新

- [ ] **Step 1: 写失败测试（repository upsert/count）**

创建 `backend/tests/test_platform_note_repository.py`：

```python
import uuid

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_upsert_inserts_then_updates_same_url(api_db):
    from app.models.platform_note import PlatformNote
    from app.repositories.platform_note_repository import (
        count_platform,
        upsert,
    )

    owner = uuid.uuid4()
    sample = {
        "title": "第一条",
        "author": "作者A",
        "url": "https://www.xiaohongshu.com/explore/n1",
        "likes": 10,
        "collect_count": 5,
        "comment_count": 2,
        "cover_image": None,
        "topic_tags": [],
        "content": "正文v1",
        "published_at": None,
    }
    assert await upsert(api_db, owner, "xiaohongshu", "成毅", sample) is True
    await api_db.commit()

    sample2 = {**sample, "title": "第一条(更新)", "content": "正文v2", "likes": 99}
    assert await upsert(api_db, owner, "xiaohongshu", "成毅", sample2) is True
    await api_db.commit()

    rows = (
        await api_db.execute(
            select(PlatformNote).where(PlatformNote.owner_user_id == owner)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "第一条(更新)"
    assert rows[0].content == "正文v2"
    assert rows[0].like_count == 99
    assert await count_platform(api_db, owner, "xiaohongshu") == 1


@pytest.mark.asyncio
async def test_count_platform_isolates_owner_and_platform(api_db):
    from app.repositories.platform_note_repository import count_platform, upsert

    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    base = {"title": "t", "author": "", "url_prefix": "https://www.xiaohongshu.com/explore/"}
    for i, url in enumerate(["n1", "n2", "n3"]):
        await upsert(api_db, owner_a, "xiaohongshu", "k", {**base, "url": base["url_prefix"] + url})
    await upsert(api_db, owner_b, "xiaohongshu", "k", {**base, "url": base["url_prefix"] + "n9"})
    await upsert(api_db, owner_a, "douyin", "k", {**base, "url": "https://www.douyin.com/video/1"})
    await api_db.commit()
    assert await count_platform(api_db, owner_a, "xiaohongshu") == 3
    assert await count_platform(api_db, owner_b, "xiaohongshu") == 1
    assert await count_platform(api_db, owner_a, "douyin") == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `python -X utf8 -m pytest tests/test_platform_note_repository.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 repository**

创建 `backend/app/repositories/platform_note_repository.py`：

```python
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform_note import PlatformNote


async def upsert(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    platform: str,
    keyword: str,
    sample: dict,
) -> bool:
    """按 (owner_user_id, url) upsert。返回是否执行成功（异常不吞，由调用方处理）。"""
    now = datetime.now(UTC)
    url = sample.get("url")
    if not url or not sample.get("title"):
        return False
    values = {
        "owner_user_id": owner_user_id,
        "platform": platform,
        "keyword": keyword,
        "url": str(url),
        "title": str(sample["title"])[:500],
        "content": (str(sample.get("content"))[:20000] if sample.get("content") else None),
        "image_urls": sample.get("image_urls") or None,
        "like_count": sample.get("like_count") or sample.get("likes"),
        "collect_count": sample.get("collect_count"),
        "comment_count": sample.get("comment_count"),
        "author": (str(sample.get("author"))[:200] if sample.get("author") else None),
        "published_at": sample.get("published_at"),
        "topic_tags": sample.get("topic_tags") or None,
        "collected_at": now,
        "updated_at": now,
    }
    stmt = (
        insert(PlatformNote)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_platform_notes_owner_url",
            set_={
                "title": values["title"],
                "content": values["content"],
                "image_urls": values["image_urls"],
                "like_count": values["like_count"],
                "collect_count": values["collect_count"],
                "comment_count": values["comment_count"],
                "author": values["author"],
                "published_at": values["published_at"],
                "topic_tags": values["topic_tags"],
                "keyword": values["keyword"],
                "updated_at": now,
            },
        )
    )
    await session.execute(stmt)
    return True


async def count_platform(
    session: AsyncSession, owner_user_id: uuid.UUID, platform: str
) -> int:
    result = await session.execute(
        select(func.count(func.distinct(PlatformNote.url))).where(
            PlatformNote.owner_user_id == owner_user_id,
            PlatformNote.platform == platform,
        )
    )
    return int(result.scalar() or 0)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -X utf8 -m pytest tests/test_platform_note_repository.py -q`
Expected: PASS

- [ ] **Step 5: 写失败测试（工具层扩展）**

在 `backend/tests/test_agent_tool_files.py` 追加类：

```python
class TestPlatformNotePersist:
    async def test_fetch_platform_search_persists_and_returns_stored_count(
        self, monkeypatch
    ):
        import httpx
        from app.services.agent.tool_executor import ToolExecutor

        ToolExecutor._last_platform_search_at = {}

        search_response = {
            "samples": [
                {
                    "title": "笔记一",
                    "author": "A",
                    "url": "https://www.xiaohongshu.com/explore/n1",
                    "likes": 1,
                },
                {
                    "title": "",
                    "author": "",
                    "url": "",
                    "likes": None,
                },  # 清洗应丢弃
            ],
            "sample_count": 2,
            "login_required": False,
            "platform": "xiaohongshu",
            "error": None,
        }
        detail_calls = []

        class FakeSearchResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return search_response

        async def fake_post(self, url, json=None, timeout=None):
            nonlocal_platform = json.get("platform") if json else None
            if url.endswith("/search"):
                return FakeSearchResponse()
            # /detail
            detail_calls.append(json)
            return _FakeJson(
                {
                    "platform": json["platform"],
                    "url": json["url"],
                    "title": "笔记一",
                    "content": "正文全文",
                    "published_at": "2026-08-01T00:00:00+00:00",
                    "like_count": 10,
                    "collect_count": 5,
                    "comment_count": 2,
                    "topic_tags": ["护肤"],
                    "author": "A",
                    "image_urls": [],
                    "login_required": False,
                    "error": None,
                }
            )

        class _FakeJson:
            def __init__(self, data):
                self._d = data

            def raise_for_status(self):
                pass

            def json(self):
                return self._d

        # 屏蔽真实入库：monkeypatch repository
        import app.repositories.platform_note_repository as pnr

        upserted = []

        async def fake_upsert(session, owner_user_id, platform, keyword, sample):
            upserted.append(sample)
            return True

        async def fake_count(session, owner_user_id, platform):
            return 1

        monkeypatch.setattr(pnr, "upsert", fake_upsert)
        monkeypatch.setattr(pnr, "count_platform", fake_count)
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

        # 工具内的入库是独立 session（async_session_factory）——patch 它
        import app.db.session as dbs

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def execute(self, *a, **k):
                raise AssertionError("execute should not be reached (repo patched)")

        monkeypatch.setattr(dbs, "async_session_factory", lambda: FakeSession())

        result = await ToolExecutor()._fetch_platform_search(
            {"platform": "xiaohongshu", "keyword": "成毅", "max_results": 10},
            owner_user_id=__import__("uuid").UUID("4c40bada-b2e6-45ea-b1b2-a2e43e663072"),
        )
        assert result["sample_count"] == 2
        assert result["stored_count"] == 1
        assert result["platform_total"] == 1
        assert len(upserted) == 1
        assert upserted[0]["title"] == "笔记一"
        assert upserted[0]["content"] == "正文全文"
        assert len(detail_calls) == 1
        assert "150" in result["note"] and "40" in result["note"]
```

（注意：若 `_fetch_platform_search` 内部用 `async_session_factory` 的上下文管理器写法不同，以上 monkeypatch 方式不变——工具实现见 Step 6，测试与实现同写。）

- [ ] **Step 6: 运行确认失败**

Run: `python -X utf8 -m pytest tests/test_agent_tool_files.py::TestPlatformNotePersist -q`
Expected: FAIL（stored_count 不存在）

- [ ] **Step 7: 实现工具层扩展**

修改 `backend/app/services/agent/tool_executor.py`：

在 `_fetch_platform_search` 的现有返回段（`samples = data.get("samples") or []` 之后）替换为：

```python
        samples = data.get("samples") or []
        cleaned = [
            s
            for s in samples
            if s.get("title") and s.get("url") and s.get("url") != "https://www.douyin.com" and s.get("url") != "https://www.xiaohongshu.com"
        ]
        detail_failed = 0
        stored_count = 0
        platform_total = len(samples)
        if owner_user_id is not None and cleaned:
            sem = asyncio.Semaphore(3)

            async def fetch_detail(sample: dict) -> dict:
                nonlocal detail_failed
                async with sem:
                    now = time.monotonic()
                    last = ToolExecutor._last_detail_at.get(platform, 0.0)
                    wait = 1.0 - (now - last)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    ToolExecutor._last_detail_at[platform] = time.monotonic()
                    try:
                        async with httpx.AsyncClient(
                            timeout=httpx.Timeout(8.0)
                        ) as client:
                            resp = await client.post(
                                f"{settings.web_renderer_url.rstrip('/')}/detail",
                                json={
                                    "platform": platform,
                                    "url": sample["url"],
                                    "cookies": cookies if isinstance(cookies, list) else None,
                                },
                            )
                            resp.raise_for_status()
                            detail = resp.json()
                    except Exception:
                        detail_failed += 1
                        return sample
                    if detail.get("error") or detail.get("login_required"):
                        detail_failed += 1
                        return sample
                    merged = {**sample}
                    for k in (
                        "title",
                        "content",
                        "published_at",
                        "like_count",
                        "collect_count",
                        "comment_count",
                        "topic_tags",
                        "author",
                    ):
                        if detail.get(k) is not None:
                            merged[k] = detail[k]
                    return merged

            cleaned = await asyncio.gather(*(fetch_detail(s) for s in cleaned))
            try:
                from app.db.session import async_session_factory
                from app.repositories.platform_note_repository import (
                    count_platform,
                    upsert,
                )

                async with async_session_factory() as session:
                    for sample in cleaned:
                        ok = await upsert(
                            session, owner_user_id, platform, keyword, sample
                        )
                        if ok:
                            stored_count += 1
                    await session.commit()
                    platform_total = await count_platform(
                        session, owner_user_id, platform
                    )
            except Exception:
                logger.warning("platform_note_persist_failed", exc_info=True)
        visible = cleaned[:20]
        note_parts = [f"该平台累计 {platform_total}/40（保底）/150（期望）条（由系统统计）"]
        if platform_total < 150 and platform_total >= 40:
            note_parts.append(f"已达标 40，距 150 期望还差 {150 - platform_total} 条，继续搜索可补充")
        if detail_failed:
            note_parts.append(f"{detail_failed} 条详情抓取失败（可能需登录或受风控）")
        if data.get("login_required"):
            note_parts.append("平台登录态不足，部分内容可能无法获取；可提示用户登录")
        return {
            "platform": platform,
            "keyword": keyword,
            "sample_count": len(cleaned),
            "samples": visible,
            "total_available": len(cleaned),
            "stored_count": stored_count,
            "detail_failed": detail_failed,
            "platform_total": platform_total,
            "login_required": bool(data.get("login_required")),
            "note": "；".join(note_parts),
        }
```

并在类属性处加：

```python
    _last_platform_search_at: dict[str, float] = {}
    _last_detail_at: dict[str, float] = {}
```

（注意：`settings` 在 `_fetch_platform_search` 内已有引用——确认该函数内已有 `settings`（用于 `web_renderer_search_timeout_seconds` 的 httpx 配置），如无则函数开头加 `settings = get_settings()`；`logger` 为模块级。）

- [ ] **Step 8: 运行确认通过**

Run: `python -X utf8 -m pytest tests/test_agent_tool_files.py::TestPlatformNotePersist tests/test_agent_tool_files.py::TestFetchPlatformSearch -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/repositories/platform_note_repository.py backend/app/services/agent/tool_executor.py backend/tests/test_platform_note_repository.py backend/tests/test_agent_tool_files.py
git commit -m "feat: persist platform notes with detail fetch and platform_total count"
```

---

### Task 4: 闸门 40 保底 + 幂等累计

**Files:**
- Modify: `backend/app/services/agent/loop.py`（`_accumulate_platform_samples`、`_check_platform_sample_gate`）
- Test: `backend/tests/test_agent_loop.py`（TestPlatformSampleGate）

**Interfaces:**
- Consumes: `_fetch_platform_search` 返回的 `platform_total`（Task 3 产出）
- Produces: 无（内部行为）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_agent_loop.py` 的 TestPlatformSampleGate 内更新/追加：

```python
    async def test_gate_hangs_below_40(self):
        from app.services.agent.loop import AgentLoopService, _QuestionHangSignal

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        st.platform_samples = {"douyin": 10}
        st.platform_sample_urls = {"douyin": {"u1"}}
        st.research_ok = True
        try:
            service._check_platform_sample_gate(st)
            raise AssertionError("must hang below 40")
        except _QuestionHangSignal as hang:
            assert hang.questions[0]["question"]
            assert "40" in hang.questions[0]["question"]
            assert "150" not in hang.questions[0]["question"]
            assert st.stage == "awaiting_question"
            assert st.hung_from_stage == "content"

    async def test_gate_passes_at_40(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        st.platform_samples = {"xiaohongshu": 40}
        st.platform_sample_urls = {"xiaohongshu": {f"u{i}" for i in range(40)}}
        st.research_ok = True
        service._check_platform_sample_gate(st)  # 不抛异常即通过

    async def test_accumulate_uses_platform_total_idempotently(self):
        from app.services.agent.loop import AgentLoopService

        service = AgentLoopService.__new__(AgentLoopService)
        st = await self._make_state(service)
        service._accumulate_platform_samples(
            st,
            {
                "platform": "douyin",
                "platform_total": 42,
                "samples": [{"url": "https://www.douyin.com/video/1"}],
                "sample_count": 1,
            },
        )
        assert st.platform_samples["douyin"] == 42
        # 重复搜索（重试/同关键词再来一次）幂等：仍 42
        service._accumulate_platform_samples(
            st,
            {
                "platform": "douyin",
                "platform_total": 42,
                "samples": [{"url": "https://www.douyin.com/video/1"}],
                "sample_count": 1,
            },
        )
        assert st.platform_samples["douyin"] == 42
```

- [ ] **Step 2: 运行确认失败**

Run: `python -X utf8 -m pytest tests/test_agent_loop.py::TestPlatformSampleGate -q`
Expected: FAIL（150 逻辑未改 / accumulate 未用 platform_total）

- [ ] **Step 3: 实现**

修改 `backend/app/services/agent/loop.py`：

`_accumulate_platform_samples` 替换为：

```python
    def _accumulate_platform_samples(self, st: _RunWorkflowState, observation: dict) -> None:
        platform = observation.get("platform")
        if platform not in ("xiaohongshu", "douyin"):
            return
        total = observation.get("platform_total")
        if isinstance(total, int) and total >= 0:
            # 服务端查库去重总数，幂等覆盖（重试/重复搜索不叠加）
            st.platform_samples[platform] = total
            return
        urls = st.platform_sample_urls.setdefault(platform, set())
        added = 0
        for sample in observation.get("samples") or []:
            url = sample.get("url")
            if url and url not in urls:
                urls.add(url)
                added += 1
        st.platform_samples[platform] = st.platform_samples.get(platform, 0) + added
```

`_check_platform_sample_gate` 替换为：

```python
    def _check_platform_sample_gate(self, st: _RunWorkflowState) -> None:
        if not st.platform_samples:
            return
        missing = [
            (platform, count)
            for platform, count in st.platform_samples.items()
            if count < 40 and platform not in st.platform_waived
        ]
        if not missing:
            return
        platform, count = max(missing, key=lambda item: item[1])
        label = "小红书" if platform == "xiaohongshu" else "抖音"
        questions = [
            {
                "question": (
                    f"平台样本不足：{label} 平台累计 {count} 条，未达到保底 40 条目标。"
                    "已尝试关键词见上方工具记录。是否换关键词继续搜索补充样本，"
                    "或确认接受当前样本数继续生成方案？"
                ),
                "affects": "40条样本保底",
            }
        ]
        st.stage = "awaiting_question"
        st.hung_from_stage = "content"
        raise _QuestionHangSignal(questions)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -X utf8 -m pytest tests/test_agent_loop.py::TestPlatformSampleGate -q`
Expected: PASS（既有测试如断言 150 文案的需同步更新——检查 TestPlatformSampleGate 中引用 "150条样本硬闸门" 或 150 文案的断言，改为 40 语义）

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/agent/loop.py backend/tests/test_agent_loop.py
git commit -m "fix: platform sample gate 40 floor with idempotent platform_total count"
```

---

### Task 5: 查询接口 GET /api/agent/platform-notes

**Files:**
- Modify: `backend/app/api/agent.py`（新增端点）
- Modify: `backend/app/repositories/platform_note_repository.py`（新增 `list_notes`）
- Test: `backend/tests/test_agent_api.py`（追加类）

**Interfaces:**
- Consumes: `PlatformNote`（Task 1）、`get_current_user`（agent.py 已有）、`success` 包装（已有）
- Produces: `GET /api/agent/platform-notes?keyword=&platform=&limit=&offset=` → `{items, total}`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_agent_api.py` 追加：

```python
class TestPlatformNotesApi:
    async def test_list_platform_notes_owner_isolated(
        self, admin_client, ordinary_client, api_db, csrf_headers
    ):
        from app.repositories.platform_note_repository import upsert

        await upsert(
            api_db,
            self._owner_id(),
            "xiaohongshu",
            "成毅",
            {"title": "笔记A", "url": "https://www.xiaohongshu.com/explore/na1", "content": "正文内容很长" * 50},
        )
        await api_db.commit()

        resp = await ordinary_client.get("/api/agent/platform-notes")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["total"] == 0
        assert body["items"] == []

    async def test_list_platform_notes_filters_and_truncates(
        self, admin_client, api_db, csrf_headers
    ):
        from app.repositories.platform_note_repository import upsert

        owner = self._owner_id()
        await upsert(api_db, owner, "xiaohongshu", "成毅", {"title": "笔记B", "url": "https://www.xiaohongshu.com/explore/nb1"})
        await upsert(api_db, owner, "douyin", "成毅", {"title": "视频C", "url": "https://www.douyin.com/video/9"})
        await api_db.commit()

        resp = await admin_client.get("/api/agent/platform-notes?platform=xiaohongshu")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["total"] == 1
        assert body["items"][0]["title"] == "笔记B"

        resp2 = await admin_client.get("/api/agent/platform-notes?keyword=不存在词")
        assert resp2.json()["data"]["total"] == 0

    async def test_list_platform_notes_requires_auth(self):
        from app.core.dependencies import get_current_user
        from fastapi.testclient import TestClient

        # 未登录
        resp = await self._unauth_get()
        assert resp.status_code == 401

    @staticmethod
    def _owner_id():
        import uuid

        return uuid.UUID("4c40bada-b2e6-45ea-b1b2-a2e43e663072")
```

**实现前先看既有测试的 client/未登录模式**：`tests/test_agent_api.py` 已有 `admin_client`/`ordinary_client` fixture 与未登录 401 的既有写法（如 `test_audit...` 或列表端点），**跟随该文件的既有模式**（上面 `_unauth_get` 是示意——按既有未登录测试的实际写法实现，例如直接用 `client.get` 不带 cookie 并断言 401）。

- [ ] **Step 2: 运行确认失败**

Run: `python -X utf8 -m pytest tests/test_agent_api.py::TestPlatformNotesApi -q`
Expected: FAIL（404 端点不存在）

- [ ] **Step 3: 实现 list_notes + 端点**

`backend/app/repositories/platform_note_repository.py` 追加：

```python
async def list_notes(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    keyword: str | None = None,
    platform: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PlatformNote], int]:
    conditions = [PlatformNote.owner_user_id == owner_user_id]
    if keyword:
        conditions.append(PlatformNote.keyword == keyword)
    if platform:
        conditions.append(PlatformNote.platform == platform)
    total = int(
        (
            await session.execute(
                select(func.count(PlatformNote.id)).where(*conditions)
            )
        ).scalar()
        or 0
    )
    rows = (
        (
            await session.execute(
                select(PlatformNote)
                .where(*conditions)
                .order_by(PlatformNote.collected_at.desc())
                .limit(min(limit, 200))
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total
```

`backend/app/api/agent.py` 追加端点（放在文件合适位置——检查现有 GET 端点结构跟随）：

```python
@router.get("/platform-notes")
async def list_platform_notes(
    request: Request,
    keyword: str = Query("", max_length=200),
    platform: str = Query("", max_length=32),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.repositories.platform_note_repository import list_notes

    rows, total = await list_notes(
        db,
        current_user.id,
        keyword or None,
        platform or None,
        limit,
        offset,
    )
    items = [
        {
            "id": str(n.id),
            "platform": n.platform,
            "keyword": n.keyword,
            "url": n.url,
            "title": n.title,
            "content": (n.content[:500] if n.content else None),
            "image_urls": n.image_urls or [],
            "like_count": n.like_count,
            "collect_count": n.collect_count,
            "comment_count": n.comment_count,
            "author": n.author,
            "published_at": n.published_at.isoformat() if n.published_at else None,
            "topic_tags": n.topic_tags or [],
            "collected_at": n.collected_at.isoformat(),
        }
        for n in rows
    ]
    return success(request, {"items": items, "total": total})
```

确认 `agent.py` 顶部已有 `Query`、`Request`、`Depends`、`get_current_user`、`success`、`User`、`AsyncSession`、`get_db` 的 import（跟随文件现有风格，缺则补）。

- [ ] **Step 4: 运行确认通过**

Run: `python -X utf8 -m pytest tests/test_agent_api.py::TestPlatformNotesApi -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/agent.py backend/app/repositories/platform_note_repository.py backend/tests/test_agent_api.py
git commit -m "feat: platform notes query API with owner isolation"
```

---

### Task 6: 全量回归 + 迁移执行 + 服务重启

**Files:** 无新增（回归）

- [ ] **Step 1: 后端全量回归**

Run: `python -X utf8 -m pytest tests -q`
Expected: 全部通过或仅有已知预存失败（记录并对比——失败若涉及本计划文件必须修复）

- [ ] **Step 2: 确认生产迁移已执行**

Run: `python -X utf8 -m alembic current`
Expected: `a1b2c3d4e5f6 (head)`——若 Task 1 已 upgrade 则为当前值；确认 DB 表存在：
`python -X utf8 -c "import asyncio; from app.db.session import async_session_factory; from sqlalchemy import text
async def m():
    async with async_session_factory() as s:
        r = await s.execute(text(\"SELECT count(*) FROM pg_tables WHERE tablename='platform_notes'\"))
        print('platform_notes exists:', r.scalar() == 1)
asyncio.run(m())"`
Expected: `platform_notes exists: True`

- [ ] **Step 3: 重启 web_renderer 与 Worker**

停止并重启两个服务（worker 独立进程不吃 --reload）：

```powershell
$all = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "web_renderer|agent_worker" }
foreach ($p in $all) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
Start-Process -FilePath "X:\python\anaconda\envs\01-rbac\python.exe" -ArgumentList "-m","app.workers.web_renderer" -WorkingDirectory "C:\01_agent_loop_pro\backend" -WindowStyle Hidden
Start-Process -FilePath "X:\python\anaconda\envs\01-rbac\python.exe" -ArgumentList "-m","app.workers.agent_worker" -WorkingDirectory "C:\01_agent_loop_pro\backend" -RedirectStandardOutput "$env:TEMP\opencode\worker_out.log" -RedirectStandardError "$env:TEMP\opencode\worker_err.log" -WindowStyle Hidden
```

验证两个进程存活（Get-CimInstance 匹配命令行为 web_renderer/agent_worker）。

- [ ] **Step 4: 端到端冒烟**

Run: `python -X utf8 "$env:TEMP\opencode\e2e_search_real.py"`（若存在；不存在则跳过）
Expected: 平台搜索返回（可能 login_required——无有效 cookie 时属预期）；若有 cookie，`platform_total` 随入库增长

- [ ] **Step 5: Commit（如无代码改动则跳过）**

---

## Self-Review

**Spec 覆盖**：
- platform_notes 表（9 字段+溯源+project_id 预留）→ Task 1 ✓
- 卡片字段扩展（collect/comment/cover/tags）→ Task 2 ✓
- 详情页（/detail 端点 + fetch_note_detail + 超时/登录墙/错误语义）→ Task 2 ✓
- 受限并发抓取（Semaphore(3) + 1s 间隔 + 8s 超时 + 失败留空 + detail_failed）→ Task 3 ✓
- upsert 入库（唯一键 + 失败不阻塞）→ Task 3 ✓
- 清洗（空标题/无链接丢弃）→ Task 3（cleaned 过滤）✓
- 闸门 40 保底（<40 挂起 / ≥40 放行 / 40-149 提示）→ Task 4 ✓
- 累计口径 platform_total 幂等（spec §7.2 修正：由 stored_count 改为服务端查库去重总数——写计划时明确实现选择）→ Task 3+4 ✓
- 查询接口（owner 隔离/筛选/截断/401）→ Task 5 ✓
- 迁移与生产执行 → Task 1+6 ✓

**占位符扫描**：无 TBD/TODO；Task 5 测试的 `_unauth_get` 有明确指引（跟随既有模式——因既有测试模式需实现者查看文件）；Task 3 测试的 FakeSession 有明确实现指引。

**类型一致性**：`platform_total`（int）在 Task 3 产出、Task 4 accumulate 消费一致；`fetch_note_detail` 返回键在 Task 2 产出、Task 3 合并消费一致；repository 签名跨 Task 3/5 一致。
