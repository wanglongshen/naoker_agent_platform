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
        raw = bytes([0x48, 0xE9, 0x6C, 0x6C, 0x6F])
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
