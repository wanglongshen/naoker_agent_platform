"""Task 2：标题感知切分（512/64）的测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.rag.chunking import Chunk, chunk_markdown
from app.services.rag.parsing import parse_source_file

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "var" / "kb_industry" / "markdown"


def test_chunk_keeps_section_path_and_size():
    md = "# 投放手册\n\n## 出价策略\n\n" + "出价策略说明。" * 120 + "\n\n## 预算\n\n预算建议。"
    chunks = chunk_markdown(md, size=200, overlap=20)
    assert chunks[0].section_path.startswith("投放手册")
    assert all(len(c.content) <= 240 for c in chunks)
    assert any("出价策略" in c.section_path for c in chunks)
    assert chunks[-1].section_path.endswith("预算")


def test_chunk_index_is_sequential_and_type_is_chunk():
    md = "# 标题\n\n" + "段落内容。" * 300
    chunks = chunk_markdown(md, size=100, overlap=10)
    assert chunks
    assert all(isinstance(c, Chunk) for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_chunk_aggregates_paragraphs_before_splitting():
    md = "# 标题\n\n" + "甲" * 100 + "\n\n" + "乙" * 100
    chunks = chunk_markdown(md, size=300, overlap=0)
    assert len(chunks) == 1
    assert "甲" * 100 in chunks[0].content
    assert "乙" * 100 in chunks[0].content


def test_chunk_overlap_repeats_previous_tail():
    md = "# 标题\n\n" + "句子内容测试。" * 200
    chunks = chunk_markdown(md, size=200, overlap=30)
    assert len(chunks) > 2
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.content.startswith(prev.content[-30:])


def test_chunk_does_not_carry_overlap_across_sections():
    md = "# 第一章\n\n" + "甲" * 180 + "\n\n# 第二章\n\n" + "乙" * 180
    chunks = chunk_markdown(md, size=200, overlap=20)
    second = next(c for c in chunks if c.section_path == "第二章")
    assert not second.content.startswith("甲")


def test_chunk_splits_oversized_sentence_without_loss():
    body = "长" * 950
    chunks = chunk_markdown("# 标题\n\n" + body, size=200, overlap=20)
    assert len(chunks) >= 5
    assert all(len(c.content) <= 220 for c in chunks)
    assert sum(c.content.count("长") for c in chunks) >= 950


def test_chunk_keeps_sentence_boundaries():
    md = "# 标题\n\n" + "这是一个测试句子。" * 60
    chunks = chunk_markdown(md, size=120, overlap=0)
    assert all(c.content.endswith("。") for c in chunks)


def test_chunk_empty_markdown_returns_empty_list():
    assert chunk_markdown("") == []
    assert chunk_markdown("\n\n  \n") == []


def test_chunk_heading_only_document_still_yields_one_chunk():
    """纯标题文档（一图读懂/一页纸类微内容）不应被丢弃。"""
    chunks = chunk_markdown("# 虚假促销玩法 规则解读")
    assert len(chunks) == 1
    assert "虚假促销玩法" in chunks[0].content
    assert chunks[0].index == 0


def test_chunk_fallback_respects_size_limit():
    chunks = chunk_markdown("# " + "标题" * 400, size=100, overlap=10)
    assert len(chunks) == 1
    assert len(chunks[0].content) <= 110


@pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="kb_industry 素材不在本机")
def test_chunk_real_sample_is_bounded_and_has_sections():
    sample = next(iter(sorted(SAMPLE_DIR.glob("*.md"))))
    doc = parse_source_file(sample)
    chunks = chunk_markdown(doc.markdown)

    assert chunks
    assert all(c.content.strip() for c in chunks)
    assert max(len(c.content) for c in chunks) <= 512 + 64
    assert all('"insert"' not in c.content for c in chunks)
    assert all(c.index == i for i, c in enumerate(chunks))
    assert any(c.section_path for c in chunks)


@pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="kb_industry 素材不在本机")
def test_chunk_real_large_sample_covers_document():
    matches = sorted(SAMPLE_DIR.glob("aJpo4GTEqyeH-*.md"))
    if not matches:
        pytest.skip("未找到大样本 aJpo4GTEqyeH-*.md")

    doc = parse_source_file(matches[0])
    chunks = chunk_markdown(doc.markdown)

    assert len(chunks) > 20
    assert max(len(c.content) for c in chunks) <= 512 + 64
    total = sum(len(c.content) for c in chunks)
    assert total >= len(doc.markdown) * 0.85
    assert any(c.section_path for c in chunks)
