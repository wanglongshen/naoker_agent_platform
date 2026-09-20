"""Task 2：Quill delta JSON 素材解析为 Markdown 的测试。

真实素材（var/kb_industry/markdown/*.md）格式：前 6 行元数据头 + 一行 Quill delta JSON。
标题/正文均来自 delta；headings 以 `*` 标记 op（attributes.heading）或标准 Quill
换行 op 表示；表格内容在独立 group 中，由主流程的 aceTable 标记引用。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.rag.parsing import ParsedDoc, delta_json_to_markdown, parse_source_file

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "var" / "kb_industry" / "markdown"
LARGE_SAMPLE_GLOB = "aJpo4GTEqyeH-*.md"

REAL_HEADER = (
    "# 商家申诉管理规则\n"
    "\n"
    "> 来源: 抖音电商官方学习中心(school.jinritemai.com) · 官方公开课程\n"
    "> URL: https://school.jinritemai.com/doudian/web/article/101652\n"
    "> 字数: 17267 · 折算页数: 21.6(A4 约800字/页估算)\n"
    "> 浏览量: 1471859 · 更新时间: 2025-03-17\n"
    "\n"
)


def _marker_payload() -> dict:
    return {
        "version": 2,
        "deltas": {
            "0": {
                "ops": [
                    {"attributes": {"lmkr": "1", "heading": "h1"}, "insert": "*"},
                    {"attributes": {"bold": "true"}, "insert": "投放手册"},
                    {"insert": "\n"},
                    {"attributes": {"lmkr": "1", "heading": "h2"}, "insert": "*"},
                    {"insert": "出价策略"},
                    {"insert": "\n"},
                    {"attributes": {"list": "bullet1", "lmkr": "1"}, "insert": "*"},
                    {"insert": "第一条要点"},
                    {"insert": "\n"},
                    {"attributes": {"lmkr": "1"}, "insert": " "},
                    {"insert": "普通段落。"},
                    {"insert": "\n"},
                ],
                "zoneId": "0",
                "zoneType": "Z",
            }
        },
        "attachments": [],
    }


def test_delta_json_to_markdown_restores_headings_and_text():
    payload = {
        "version": 2,
        "deltas": {
            "d1": {
                "ops": [
                    {"insert": "小店随心推产品手册"},
                    {"insert": "\n", "attributes": {"heading": 1}},
                ]
            },
            "d2": {
                "ops": [
                    {"insert": "全域投放包含直播与短视频两种模式。"},
                    {"insert": "\n"},
                ]
            },
        },
        "attachments": [],
    }
    md = delta_json_to_markdown(payload)
    assert md.startswith("# 小店随心推产品手册")
    assert "全域投放包含直播与短视频两种模式。" in md


def test_delta_json_to_markdown_handles_marker_headings_and_drops_markers():
    md = delta_json_to_markdown(_marker_payload())
    assert "# 投放手册" in md
    assert "## 出价策略" in md
    assert "第一条要点" in md
    assert "普通段落。" in md
    assert "*" not in md
    assert "{" not in md
    assert md.index("# 投放手册") < md.index("## 出价策略") < md.index("第一条要点")


def test_delta_json_to_markdown_accepts_attachments_first_payload():
    payload = {
        "attachments": [{"id": "a1", "type": "image", "name": "x.png"}],
        "deltas": {"0": {"ops": [{"insert": "正文"}, {"insert": "\n"}]}},
    }
    assert delta_json_to_markdown(payload).strip() == "正文"


def test_delta_json_to_markdown_inlines_table_cells_in_place():
    payload = {
        "deltas": {
            "0": {
                "ops": [
                    {"insert": "表格前段落"},
                    {"insert": "\n"},
                    {"attributes": {"lmkr": "1", "aceTable": "R1 C1"}, "insert": "*"},
                    {"insert": "\n"},
                    {"insert": "表格后段落"},
                    {"insert": "\n"},
                ],
                "zoneType": "Z",
            },
            "R1": {
                "ops": [
                    {"attributes": {"rowHeight": "39"}, "insert": {"id": "rA"}},
                    {"attributes": {"rowHeight": "39"}, "insert": {"id": "rB"}},
                ],
                "zoneType": "R",
            },
            "C1": {
                "ops": [
                    {"attributes": {"colWidth": "77"}, "insert": {"id": "cA"}},
                    {"attributes": {"colWidth": "88"}, "insert": {"id": "cB"}},
                ],
                "zoneType": "C",
            },
            "xrAxcA": {"ops": [{"insert": "场景"}, {"insert": "\n"}], "zoneType": "Z"},
            "xrAxcB": {"ops": [{"insert": "定义"}, {"insert": "\n"}], "zoneType": "Z"},
            "xrBxcA": {"ops": [{"insert": "违规申诉"}, {"insert": "\n"}], "zoneType": "Z"},
            "xrBxcB": {"ops": [{"insert": "商家不认可处置"}, {"insert": "\n"}], "zoneType": "Z"},
        },
        "attachments": [],
    }
    md = delta_json_to_markdown(payload)
    lines = md.splitlines()
    assert "| 场景 | 定义 |" in md
    assert "| --- | --- |" in md
    assert "| 违规申诉 | 商家不认可处置 |" in md
    assert lines.index("表格前段落") < lines.index("| 场景 | 定义 |") < lines.index("表格后段落")


@pytest.mark.parametrize("payload", [{}, {"deltas": None}, {"deltas": {"0": {}}}])
def test_delta_json_to_markdown_tolerates_broken_payload(payload):
    assert delta_json_to_markdown(payload) == ""


def test_parse_source_file_parses_header_and_delta(tmp_path: Path):
    doc_path = tmp_path / "101652-demo.md"
    doc_path.write_text(
        REAL_HEADER + json.dumps(_marker_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    doc = parse_source_file(doc_path)

    assert isinstance(doc, ParsedDoc)
    assert doc.title == "商家申诉管理规则"
    assert doc.markdown.startswith("# 投放手册")
    assert doc.source_meta["source"] == "抖音电商官方学习中心(school.jinritemai.com) · 官方公开课程"
    assert doc.source_meta["source_url"] == (
        "https://school.jinritemai.com/doudian/web/article/101652"
    )
    assert doc.source_meta["word_count"] == 17267
    assert doc.source_meta["views"] == 1471859
    assert doc.source_meta["updated_at"] == "2025-03-17"
    assert doc.source_meta["file"] == "101652-demo.md"
    assert doc.source_meta["attachment_count"] == 0


def test_parse_source_file_records_attachments_count(tmp_path: Path):
    payload = _marker_payload()
    payload["attachments"] = [
        {"id": "a1", "type": "image", "name": "1.png"},
        {"id": "a2", "type": "file", "name": "2.pdf"},
    ]
    doc_path = tmp_path / "doc.md"
    doc_path.write_text(REAL_HEADER + json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    doc = parse_source_file(doc_path)

    assert doc.source_meta["attachment_count"] == 2


def test_parse_source_file_image_only_delta_does_not_fall_back_to_raw_json(tmp_path: Path):
    payload = {
        "version": 2,
        "deltas": {
            "0": {
                "ops": [
                    {"insert": " "},
                    {"insert": "\n"},
                    {
                        "insert": " ",
                        "attributes": {
                            "IMAGE": "true",
                            "fileSrc": "https://example.com/a.png",
                        },
                    },
                    {"insert": "\n"},
                ]
            }
        },
        "attachments": [{"id": "a1", "type": "image"}],
    }
    doc_path = tmp_path / "image-only.md"
    doc_path.write_text(REAL_HEADER + json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    doc = parse_source_file(doc_path)

    assert doc.source_meta["parse_mode"] == "delta"
    assert doc.markdown == ""
    assert doc.title == "商家申诉管理规则"
    assert doc.source_meta["attachment_count"] == 1


def test_parse_source_file_falls_back_to_plain_text_on_broken_json(tmp_path: Path):
    doc_path = tmp_path / "broken.md"
    doc_path.write_text(REAL_HEADER + "{not valid json", encoding="utf-8")

    doc = parse_source_file(doc_path)

    assert doc.title == "商家申诉管理规则"
    assert "{not valid json" in doc.markdown
    assert doc.source_meta["source_url"] == (
        "https://school.jinritemai.com/doudian/web/article/101652"
    )
    assert doc.source_meta["parse_mode"] == "text"


def test_parse_source_file_treats_plain_markdown_without_header(tmp_path: Path):
    doc_path = tmp_path / "plain.md"
    doc_path.write_text("# 纯 Markdown 标题\n\n正文段落。\n", encoding="utf-8")

    doc = parse_source_file(doc_path)

    assert doc.title == "纯 Markdown 标题"
    assert doc.markdown.startswith("# 纯 Markdown 标题")
    assert "正文段落。" in doc.markdown


@pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="kb_industry 素材不在本机")
def test_parse_real_sample_yields_markdown_and_meta():
    sample = next(iter(sorted(SAMPLE_DIR.glob("*.md"))))
    doc = parse_source_file(sample)

    assert doc.title
    assert len(doc.markdown) > 500
    assert not doc.markdown.lstrip().startswith('{"version"')
    assert '"insert"' not in doc.markdown
    assert '"deltas"' not in doc.markdown
    assert "aceTable" not in doc.markdown
    assert doc.source_meta["file"] == sample.name
    assert doc.source_meta["parse_mode"] == "delta"


@pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="kb_industry 素材不在本机")
def test_parse_real_large_sample_is_clean():
    matches = sorted(SAMPLE_DIR.glob(LARGE_SAMPLE_GLOB))
    if not matches:
        pytest.skip(f"未找到大样本 {LARGE_SAMPLE_GLOB}")

    doc = parse_source_file(matches[0])

    # 该文件头部「字数 239307」实为 JSON 字符数；delta 正文（含表格单元格）约 1.9 万字
    assert len(doc.markdown) > 10_000
    assert doc.title
    assert doc.source_meta["attachment_count"] > 0
    assert '"insert"' not in doc.markdown
    assert "\\n" not in doc.markdown
    assert doc.source_meta["parse_mode"] == "delta"
