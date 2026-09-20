import json
from pathlib import Path

from scripts.rag_library_report import build_report, render_markdown

MANIFEST = Path(__file__).resolve().parents[2] / "var" / "kb_industry" / "manifest" / "manifest.json"


def test_report_covers_all_items_with_library_and_rule():
    items = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))["items"]
    rows = build_report(items)
    assert len(rows) == 601
    assert all(row.library_name for row in rows)
    assert all(row.matched_rule for row in rows)


def test_markdown_has_one_line_per_document():
    items = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))["items"][:5]
    text = render_markdown(build_report(items))
    assert text.startswith("# 知识库分配报告")
    assert text.count("| ") >= 5
