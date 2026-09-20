import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.services.feishu.service import markdown_to_blocks


class TestMarkdownToBlocks:
    def test_heading_and_paragraph(self):
        blocks = markdown_to_blocks("# 标题\n\n这是正文")
        assert len(blocks) == 2
        assert blocks[0]["block_type"] == 3  # heading1
        assert blocks[1]["block_type"] == 2  # paragraph

    def test_bullet_list(self):
        blocks = markdown_to_blocks("- 项目A\n- 项目B")
        assert len(blocks) == 2
        assert blocks[0]["block_type"] == 12  # bullet

    def test_table_rows_split(self):
        blocks = markdown_to_blocks("| 列1 | 列2 |\n|---|---|\n| A | B |")
        assert len(blocks) >= 1  # header row as table

    def test_paragraph_block_uses_text_field(self):
        blocks = markdown_to_blocks("这是正文")
        assert blocks[0]["block_type"] == 2
        assert "paragraph" not in blocks[0]
        assert blocks[0]["text"]["elements"][0]["text_run"]["content"] == "这是正文"

    def test_heading_block_uses_heading_field(self):
        blocks = markdown_to_blocks("## 二级标题")
        assert blocks[0]["block_type"] == 4
        assert "heading2" in blocks[0]

    def test_bullet_block_uses_bullet_field(self):
        blocks = markdown_to_blocks("- 项目A")
        assert blocks[0]["block_type"] == 12
        assert "bullet" in blocks[0]
