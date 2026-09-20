import pytest
from app.services.agent.web_renderer import (
    _extract_douyin_json,
    _extract_platform_content,
)


class TestDouyinExtraction:
    def test_extracts_render_data_json(self):
        html = '<script id="RENDER_DATA" type="application/json">' + \
            '{"0":{"aweme":"video","desc":"测试视频标题","author":{"nickname":"作者A"}}}' + \
            "</script>"
        result = _extract_douyin_json(html)
        assert result is not None
        assert "测试视频标题" in result or "video" in result

    def test_extracts_initial_state(self):
        html = '<script>window.__INITIAL_STATE__={"aweme":{"desc":"标题B"}};</script>'
        result = _extract_douyin_json(html)
        assert result is not None

    def test_no_embedded_json_returns_none(self):
        html = "<html><head><title>只有标题</title></head></html>"
        assert _extract_douyin_json(html) is None


class TestPlatformContent:
    def test_douyin_platform_includes_json_text(self):
        html = '<script id="RENDER_DATA" type="application/json">{"0":{"aweme":"video","desc":"视频标题"}}</script>'
        result = _extract_platform_content(html, "https://www.douyin.com")
        assert result["platform"] == "douyin"
        assert "视频标题" in result["text"]
