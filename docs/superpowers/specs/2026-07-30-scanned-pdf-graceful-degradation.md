# Scanned PDF Graceful Degradation & Structured Extraction Results

## Goal

Replace the current opaque `"(binary file, type: application/pdf, ...)"` fallback
with structured extraction metadata so that the Agent Planner can make informed
decisions instead of retry-loops. Add page-count awareness for all PDF reads.

## Current State

`extract_file_text` in `file_reader.py` returns:

```python
# Success
{"text": "extracted content...", "truncated": false}

# Failure (all formats)
{"text": "(binary file, type: application/pdf, size: 245KB, no text extracted)", "truncated": false}
```

When pypdf opens a scanned PDF, `page.extract_text()` returns empty strings for
every page. The function returns `None` (no text extracted), falling through to
the generic binary fallback. The Agent receives this opaque message and cannot
distinguish "this PDF has no text" from "the extraction tool failed" or "the
file is corrupt."

Result: Agent retries with web search or re-reads the same file, burning steps
and context.

## Proposed Architecture

### Structured Result Format

Replace the string-only `text` field with a richer result dict:

```python
{
    "text": "extracted content or error description",
    "truncated": false,
    "format": "pdf",
    "pages": 3,
    "pages_with_text": 0,
    "extraction_status": "no_text_found",
    "format_metadata": {"page_count": 3}
}
```

### Extraction Status Enum

| Status | Meaning | Fallback text |
|--------|---------|--------------|
| `success` | Text extracted normally | actual content |
| `truncated` | Text extracted but capped at 50KB | content + truncation note |
| `no_text_found` | PDF opened, pages found, but all pages empty | "该PDF共3页，但无法提取文字内容（可能为扫描件或图片型PDF）。请尝试使用含有文字层的PDF文件。" |
| `too_large` | File exceeds size limit | "(file too large: {size} bytes, max {max})" |
| `unsupported_format` | MIME type not in extractor list | "(binary file, type: {type}, size: {size} bytes, no text extraction available)" |

### Modified _extract_pdf

```python
def _extract_pdf(content: bytes) -> dict | None:
    """Returns None only for parse errors (corrupt file)."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = len(reader.pages)
        parts = []
        pages_with_text = 0
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text and page_text.strip():
                parts.append(page_text)
                pages_with_text += 1
        
        text = "\n".join(parts) if parts else ""
        
        return {
            "text": text,
            "pages": pages,
            "pages_with_text": pages_with_text,
            "extraction_status": "success" if text else "no_text_found",
        }
    except Exception:
        return None
```

### Modified extract_file_text Router

All format-specific extractors now return `dict | None` (was `str | None`).
The router at `extract_file_text` uses the structured dict to compose the final
user-facing `text` field.

```python
def extract_file_text(media_type, content):
    # ... file size check unchanged ...
    
    result = None
    if media_type in _TEXT_MIME_TYPES:
        text = _extract_text_encoded(content)
        if text is not None:
            result = {"text": text, "status": "success"}
    elif media_type == _PDF_MIME_TYPE:
        result = _extract_pdf(content)
    # ... other formats unchanged, each returning dict | None ...
    
    if result is None:
        # Parse error (corrupt file)
        return {"text": f"(文件已损坏，无法解析: {media_type})", "truncated": False}
    
    if result.get("status") == "no_text_found":
        pages = result.get("pages", "?")
        return {
            "text": f"(该文件为{media_type}格式，共{pages}页，但无法提取文字内容。可能为扫描件或图片型PDF。建议：请上传含有文字层的PDF文件。)",
            "truncated": False,
        }
    
    text = result.get("text", "")
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        return {"text": text, "truncated": True}
    
    return {"text": text, "truncated": False}
```

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/agent/file_reader.py` | Per-extractor return dicts; router uses structured metadata; new PDF page counting |
| `backend/tests/test_file_reader.py` | Update assertions to check new `pages`/`status` fields; add scanned PDF test |

## Non-Goals

- OCR integration (pytesseract/pdf2image) — deferred to separate spec
- Streaming large PDFs page-by-page (current single-pass is sufficient)
- Other format extractors (docx, xlsx, pptx) — keep returning simple dicts for now
