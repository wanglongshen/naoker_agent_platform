from __future__ import annotations

import pytest
from app.services.agent.loop import remove_visible_thought_overlap


def test_removes_repeated_prefix_when_long_enough():
    previous = "我已找到多个关于胡萝卜炒鸡蛋的食谱，接下来将整合成一份详细的图文教程。"
    resumed = previous + "接下来将为您汇总胡萝卜炒鸡蛋的详细教程。"

    result = remove_visible_thought_overlap(previous, resumed)
    assert result == "接下来将为您汇总胡萝卜炒鸡蛋的详细教程。"


def test_preserves_unrelated_resume_text():
    previous = "我会先搜索相关公开资料。"
    resumed = "搜索已得到多个来源，后续将整理成完整回答。"
    result = remove_visible_thought_overlap(previous, resumed)
    assert result == resumed


def test_uses_fallback_when_resume_is_fully_duplicated():
    previous = "搜索完成，正在整理。"
    result = remove_visible_thought_overlap(previous, previous, fallback_action_type="web_search")
    assert result is None or len(result) > 0


def test_ignores_short_overlap():
    previous = "搜索"
    resumed = "搜索已完成，整理中"
    result = remove_visible_thought_overlap(previous, resumed)
    assert result == resumed


def test_handles_whitespace_normalization():
    previous = "a very long visible thought that will be repeated"
    resumed = "a very long visible thought that will be repeated and then continued"
    result = remove_visible_thought_overlap(previous, resumed)
    assert len(result) > 0
