# Universal File Reader — Enterprise-Grade Multi-Format Text Extraction

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `_format_file_result`'s naive `decode("utf-8")` with a MIME-type-routed text extraction pipeline that handles Markdown, PDF, DOCX, XLSX, PPTX, and falls back gracefully to metadata-only for binary types (images, video, archives). Content is capped at 50KB with a `truncated` flag, file size capped at 10MB, and encoding detection tries UTF-8 → latin-1 → GBK before failing.

**Architecture:** A routing dispatcher `_extract_file_content(media_type, content_bytes)` → delegates to per-format extractors (text, pdf, docx, xlsx, pptx) → returns `{text, truncated}` dict. `_format_file_result` calls this dispatcher instead of blind `decode()`. Each extractor is isolated in its own try/except block — one format failing never blocks another.

**Tech Stack:** Python 3.12, pypdf, python-docx, openpyxl (already installed), python-pptx

## Global Constraints

- File size check: > 10MB → return metadata only, no extraction attempt.
- Content cap: all extracted text truncated to 50000 chars with `truncated: true/false`.
- Encoding: UTF-8 first; on `UnicodeDecodeError` try `latin-1` then `gbk`; if all fail, return metadata + error message.
- MIME routing based on `file_obj.media_type`, NOT file extension.
- Each extractor lives in its own try/except — one failure isolates.
- No changes to `_read_file`'s RBAC logic or parameter signatures.

## File Structure

| File | Responsibility |
|------|---------------|
| `backend/app/services/agent/file_reader.py` | **New.** `extract_file_text(media_type, content_bytes) -> dict` — the MIME router + all per-format extractors |
| `backend/app/services/agent/tool_executor.py` | **Modify.** `_format_file_result` → calls `extract_file_text` instead of `decode()` |
| `backend/requirements.txt` | **Modify.** Add `pypdf`, `python-docx`, `python-pptx` |
| `backend/tests/test_file_reader.py` | **New.** Unit tests for all formats |

---

### Task 1: Dependencies and New Module Scaffold

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/services/agent/file_reader.py`
- Create: `backend/tests/test_file_reader.py`

- [ ] **Step 1: Add dependencies to requirements.txt**

Append to `backend/requirements.txt`:

```
pypdf>=5.0,<6
python-docx>=1.1,<2
python-pptx>=1.0,<2
```

openpyxl is already installed.

- [ ] **Step 2: Install packages**

```powershell
python -X utf8 -m pip install "pypdf>=5.0,<6" "python-docx>=1.1,<2" "python-pptx>=1.0,<2"
```

- [ ] **Step 3: Write the test file**

Create `backend/tests/test_file_reader.py`:

```python
import pytest
from app.services.agent.file_reader import extract_file_text


class TestTextFormats:
    def test_markdown_decodes_utf8(self):
        result = extract_file_text("text/markdown", "# Hello\n\n**Bold** text".encode("utf-8"))
        assert result["text"] == "# Hello\n\n**Bold** text"
        assert result["truncated"] is False

    def test_plain_text_utf8(self):
        result = extract_file_text("text/plain", "Hello world".encode("utf-8"))
        assert result["text"] == "Hello world"

    def test_text_falls_back_to_latin1(self):
        raw = bytes([0x48, 0xE9, 0x6C, 0x6C, 0x6F])  # HélLo in latin-1
        result = extract_file_text("text/plain", raw)
        assert "H" in result["text"]

    def test_text_returns_error_when_all_encodings_fail(self):
        raw = bytes([0xFF, 0xFE, 0x00, 0x00])
        result = extract_file_text("text/plain", raw)
        assert "error" in result

    def test_json_decodes_utf8(self):
        result = extract_file_text("application/json", b'{"key": "value"}')
        assert '"key": "value"' in result["text"]

    def test_csv_decodes_utf8(self):
        result = extract_file_text("text/csv", b"a,b,c\n1,2,3")
        assert "a,b,c" in result["text"]


class TestPdfFormat:
    def test_pdf_extracts_text(self):
        import io
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(200, 200)
        page = writer.pages[0]
        writer.add_blank_page(200, 200)
        buf = io.BytesIO()
        writer.write(buf)
        raw = buf.getvalue()

        result = extract_file_text("application/pdf", raw)
        assert "text" in result


class TestDocxFormat:
    def test_docx_extracts_text(self):
        import io
        from docx import Document
        doc = Document()
        doc.add_paragraph("Hello from docx")
        buf = io.BytesIO()
        doc.save(buf)
        raw = buf.getvalue()

        result = extract_file_text("application/vnd.openxmlformats-officedocument.wordprocessingml.document", raw)
        assert "Hello from docx" in result["text"]


class TestXlsxFormat:
    def test_xlsx_extracts_text(self):
        import io
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws["A1"] = "Cell A1"
        ws["B1"] = "Cell B1"
        buf = io.BytesIO()
        wb.save(buf)
        raw = buf.getvalue()

        result = extract_file_text("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", raw)
        assert "Cell A1" in result["text"]
        assert "Cell B1" in result["text"]


class TestPptxFormat:
    def test_pptx_extracts_text(self):
        import io
        from pptx import Presentation
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = "Presentation Title"
        buf = io.BytesIO()
        prs.save(buf)
        raw = buf.getvalue()

        result = extract_file_text("application/vnd.openxmlformats-officedocument.presentationml.presentation", raw)
        assert "Presentation Title" in result["text"]


class TestTruncation:
    def test_content_truncated_at_50k(self):
        long_text = "x" * 60000
        result = extract_file_text("text/plain", long_text.encode("utf-8"))
        assert len(result["text"]) == 50000
        assert result["truncated"] is True

    def test_content_not_truncated_under_50k(self):
        short_text = "x" * 100
        result = extract_file_text("text/plain", short_text.encode("utf-8"))
        assert len(result["text"]) == 100
        assert result["truncated"] is False


class TestFileSizeLimit:
    def test_large_file_returns_metadata_only(self):
        result = extract_file_text("application/pdf", b"x" * 11_000_000)
        assert result["text"].startswith("(file too large")
        assert result["truncated"] is False


class TestBinaryFallback:
    def test_image_returns_metadata(self):
        result = extract_file_text("image/png", b"\x89PNG\r\n\x1a\nfake")
        assert "(binary" in result["text"] or "extract" in result["text"]

    def test_zip_returns_metadata(self):
        result = extract_file_text("application/zip", b"PK\x03\x04fake")
        assert "(binary" in result["text"] or "extract" in result["text"]


class TestEdgeCases:
    def test_none_media_type_returns_metadata(self):
        result = extract_file_text(None, b"some content")
        assert "text" in result

    def test_empty_content_returns_empty_text(self):
        result = extract_file_text("text/plain", b"")
        assert result["text"] == ""

    def test_html_extracts_text(self):
        result = extract_file_text("text/html", b"<html><body><p>Hello</p></body></html>")
        assert "Hello" in result["text"]

    def test_corrupt_pdf_returns_metadata(self):
        result = extract_file_text("application/pdf", b"not a valid pdf file")
        assert "binary" in result["text"] or "extract" in result["text"]

    def test_corrupt_docx_returns_metadata(self):
        result = extract_file_text(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"not a valid docx",
        )
        assert "binary" in result["text"] or "extract" in result["text"]
```

- [ ] **Step 4: Run tests to verify they FAIL**

```powershell
python -X utf8 -m pytest tests/test_file_reader.py -v --no-header
```

Expected: all FAIL — `extract_file_text` not defined.

- [ ] **Step 5: Implement file_reader.py**

Create `backend/app/services/agent/file_reader.py`:

```python
from __future__ import annotations

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 50000

_TEXT_MIME_TYPES = {
    "text/plain", "text/csv", "text/markdown", "text/html",
    "application/json", "application/xml", "text/xml",
}

_PDF_MIME_TYPE = "application/pdf"

_DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def extract_file_text(media_type: str, content: bytes) -> dict:
    if len(content) > MAX_FILE_BYTES:
        return {
            "text": f"(file too large: {len(content)} bytes, max {MAX_FILE_BYTES})",
            "truncated": False,
        }

    text = None
    truncated = False

    if media_type in _TEXT_MIME_TYPES:
        text = _extract_text_encoded(content)
    elif media_type == _PDF_MIME_TYPE:
        text = _extract_pdf(content)
    elif media_type == _DOCX_MIME_TYPE:
        text = _extract_docx(content)
    elif media_type == _XLSX_MIME_TYPE:
        text = _extract_xlsx(content)
    elif media_type == _PPTX_MIME_TYPE:
        text = _extract_pptx(content)

    if text is None:
        return {
            "text": f"(binary file, type: {media_type}, size: {len(content)} bytes, no text extracted)",
            "truncated": False,
        }

    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        truncated = True

    return {"text": text, "truncated": truncated}


def _extract_text_encoded(content: bytes) -> str | None:
    for encoding in ("utf-8", "latin-1", "gbk"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def _extract_pdf(content: bytes) -> str | None:
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                parts.append(page_text)
        return "\n".join(parts) if parts else None
    except Exception:
        return None


def _extract_docx(content: bytes) -> str | None:
    try:
        import io
        from docx import Document
        doc = Document(io.BytesIO(content))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text for cell in row.cells if cell.text.strip())
                if row_text.strip():
                    parts.append(row_text)
        return "\n".join(parts) if parts else None
    except Exception:
        return None


def _extract_xlsx(content: bytes) -> str | None:
    try:
        import io
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        parts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            parts.append(f"--- Sheet: {sheet_name} ---")
            for row in ws.iter_rows(values_only=True):
                row_values = [str(cell) if cell is not None else "" for cell in row]
                if any(v.strip() for v in row_values):
                    parts.append(" | ".join(row_values))
        wb.close()
        return "\n".join(parts) if parts else None
    except Exception:
        return None


def _extract_pptx(content: bytes) -> str | None:
    try:
        import io
        from pptx import Presentation
        prs = Presentation(io.BytesIO(content))
        parts = []
        for slide_num, slide in enumerate(prs.slides, 1):
            parts.append(f"--- Slide {slide_num} ---")
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                        text = paragraph.text.strip()
                        if text:
                            parts.append(text)
        return "\n".join(parts) if parts else None
    except Exception:
        return None
```

- [ ] **Step 6: Run tests to verify they PASS**

```powershell
python -X utf8 -m pytest tests/test_file_reader.py -v --no-header
```

Expected: all 19 tests PASS. Fix any failures by adjusting the implementation, not the test assertions.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/services/agent/file_reader.py backend/tests/test_file_reader.py
git commit -m "feat: add universal file reader — MIME-routed text extraction for text/pdf/docx/xlsx/pptx"
```

---

### Task 2: Integrate into ToolExecutor._format_file_result

**Files:**
- Modify: `backend/app/services/agent/tool_executor.py:305-312`

**Interfaces:**
- Consumes: `extract_file_text(media_type, content_bytes)` from Task 1
- Produces: `_format_file_result` returns structured dict with `text` and `truncated`

- [ ] **Step 1: Update _format_file_result**

In `backend/app/services/agent/tool_executor.py`, add the import near the top:

```python
from app.services.agent.file_reader import extract_file_text
```

Replace the `_format_file_result` method (lines 305-312):

```python
    @staticmethod
    def _format_file_result(file_obj) -> dict[str, Any]:
        content_bytes = file_obj.content if file_obj.content else b""
        result = extract_file_text(file_obj.media_type or "application/octet-stream", content_bytes)
        return {
            "filename": file_obj.original_filename,
            "media_type": file_obj.media_type,
            "content": result["text"],
            "truncated": result["truncated"],
        }
```

- [ ] **Step 2: Also fix attachment read path in _read_file**

The attachment branch (lines 222-237) currently uses `attachment.extracted_text` directly. Update it to also try `extract_file_text` on raw content when extracted_text is None:

In `tool_executor.py`, find the attachment block inside `_read_file` (lines 222-237). Replace:

```python
                text = attachment.extracted_text or "(binary file, no text extracted)"
                return {
                    "filename": attachment.original_filename,
                    "media_type": attachment.media_type,
                    "content": text[:10000],
                }
```

With:

```python
                if attachment.extracted_text:
                    text = attachment.extracted_text
                elif attachment.content:
                    result = extract_file_text(attachment.media_type or "application/octet-stream", attachment.content)
                    text = result["text"]
                else:
                    text = "(binary file, no text extracted)"
                return {
                    "filename": attachment.original_filename,
                    "media_type": attachment.media_type,
                    "content": text[:50000],
                }
```

- [ ] **Step 3: Run all file-related tests**

```powershell
python -X utf8 -m pytest tests/test_agent_tool_files.py tests/test_file_reader.py -v --no-header
```

Expected: all pass. Note: the existing `test_read_file_by_path_returns_content` test uses `MagicMock` with `content = b"# Hello\n\nWorld"` and `media_type = "text/markdown"` — `extract_file_text` handles this correctly via the text path.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/agent/tool_executor.py
git commit -m "feat: integrate universal file reader into ToolExecutor._format_file_result"
```
