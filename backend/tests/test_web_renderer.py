import asyncio
import pytest
from app.services.agent.web_renderer import _pick_user_agent, _stealth_js, _parse_rendered_html


class TestUserAgent:
    def test_returns_desktop_chrome_ua(self):
        ua = _pick_user_agent()
        assert "Chrome" in ua
        assert "Windows" in ua or "Macintosh" in ua

    def test_multiple_calls_vary(self):
        uas = {_pick_user_agent() for _ in range(5)}
        assert len(uas) > 1


class TestStealthJs:
    def test_contains_webdriver_override(self):
        js = _stealth_js()
        assert "navigator.webdriver" in js


class TestParseRenderedHtml:
    def test_extracts_title_and_text(self):
        html = "<html><head><title>测试标题</title></head><body><p>Hello 世界</p></body></html>"
        result = _parse_rendered_html(html, "https://example.com")
        assert result["title"] == "测试标题"
        assert "Hello 世界" in result["text"]
        assert result["url"] == "https://example.com"
        assert result["status_code"] == 200

    def test_truncates_long_text(self):
        html = f"<html><body><p>{'x' * 60000}</p></body></html>"
        result = _parse_rendered_html(html, "https://example.com")
        assert len(result["text"]) <= 50000


from app.services.agent.web_renderer import (
    _extract_samples_from_json,
    _detect_login_wall,
    _sample_url,
)


def test_extract_samples_from_douyin_aweme_list():
    data = {
        "aweme_list": [
            {
                "desc": "GAP成毅秋季大片",
                "author": {"nickname": "品牌情报局"},
                "statistics": {"digg_count": 1200},
                "share_url": "https://www.douyin.com/video/1001",
            },
            {
                "desc": "成毅代言现场",
                "author": {"nickname": "时尚前线"},
                "share_url": "https://www.douyin.com/video/1002",
            },
        ]
    }
    samples = _extract_samples_from_json(data, "douyin")
    assert len(samples) == 2
    assert samples[0]["title"] == "GAP成毅秋季大片"
    assert samples[0]["author"] == "品牌情报局"
    assert samples[0]["url"] == "https://www.douyin.com/video/1001"
    assert samples[0]["likes"] == 1200


def test_extract_samples_from_xiaohongshu_notes():
    data = {
        "note": {
            "noteList": [
                {
                    "title": "成毅同款穿搭",
                    "user": {"nickname": "穿搭博主"},
                    "interactInfo": {"likedCount": "3456"},
                    "noteId": "abc123",
                }
            ]
        }
    }
    samples = _extract_samples_from_json(data, "xiaohongshu")
    assert len(samples) == 1
    assert samples[0]["title"] == "成毅同款穿搭"
    assert samples[0]["author"] == "穿搭博主"
    assert "abc123" in samples[0]["url"]


def test_detect_login_wall_douyin():
    assert _detect_login_wall("douyin", "<html>扫码登录</html>") is True
    assert _detect_login_wall("douyin", "<html>大量正常内容</html>") is False


def test_detect_login_wall_xiaohongshu():
    assert _detect_login_wall("xiaohongshu", "登录后推荐更懂你的笔记") is True


def test_sample_url_falls_back_to_domain():
    assert "douyin.com" in _sample_url("douyin", "")


def test_search_request_validation():
    from app.workers.web_renderer import SearchRequest
    from pydantic import ValidationError

    req = SearchRequest(platform="douyin", keyword="GAP成毅", max_results=30)
    assert req.max_results == 30
    try:
        SearchRequest(platform="douyin", keyword="x", max_results=51)
        raise AssertionError("max_results must be capped at 50")
    except ValidationError:
        pass
    try:
        SearchRequest(platform="weibo", keyword="x")
        raise AssertionError("platform must be xiaohongshu or douyin")
    except ValidationError:
        pass


def test_search_endpoint_passes_configured_timeout(monkeypatch):
    from fastapi.testclient import TestClient
    import app.workers.web_renderer as ww
    from app.core.config import get_settings

    captured = {}

    async def fake_search_platform(platform, keyword, max_results, cookies, timeout_seconds=60.0):
        captured["timeout"] = timeout_seconds
        return {
            "samples": [],
            "sample_count": 0,
            "login_required": False,
            "platform": platform,
        }

    monkeypatch.setattr(ww, "search_platform", fake_search_platform)
    client = TestClient(ww.app)
    resp = client.post("/search", json={"platform": "douyin", "keyword": "x", "max_results": 10})
    assert resp.status_code == 200
    assert captured["timeout"] == get_settings().web_renderer_search_timeout_seconds


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
