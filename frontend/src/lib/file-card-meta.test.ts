import { describe, it, expect } from "vitest";
import {
  formatFileSize,
  getFileFormatLabel,
  getFileTypeIconKey,
} from "./file-card-meta";

describe("getFileTypeIconKey", () => {
  it("maps markdown and text to text", () => {
    expect(getFileTypeIconKey({ name: "a.md", type: "text/markdown" })).toBe("text");
    expect(getFileTypeIconKey({ name: "b.txt", type: "text/plain" })).toBe("text");
    expect(getFileTypeIconKey({ name: "c.markdown" })).toBe("text");
  });

  it("maps docx/doc to doc", () => {
    expect(getFileTypeIconKey({ name: "d.docx" })).toBe("doc");
    expect(getFileTypeIconKey({ name: "e.doc", type: "application/msword" })).toBe("doc");
  });

  it("maps pdf to pdf", () => {
    expect(getFileTypeIconKey({ name: "f.pdf", type: "application/pdf" })).toBe("pdf");
  });

  it("maps images to image", () => {
    expect(getFileTypeIconKey({ name: "g.png", type: "image/png" })).toBe("image");
    expect(getFileTypeIconKey({ name: "h.webp" })).toBe("image");
  });

  it("falls back to generic for unknown types", () => {
    expect(getFileTypeIconKey({ name: "i.xlsx" })).toBe("generic");
    expect(getFileTypeIconKey({ name: "j" })).toBe("generic");
  });
});

describe("getFileFormatLabel", () => {
  it("labels markdown distinctly", () => {
    expect(getFileFormatLabel({ name: "a.md", type: "text/markdown" })).toBe("Markdown");
    expect(getFileFormatLabel({ name: "b.markdown" })).toBe("Markdown");
  });

  it("labels other text as 文本", () => {
    expect(getFileFormatLabel({ name: "c.txt", type: "text/plain" })).toBe("文本");
  });

  it("labels doc, pdf, image", () => {
    expect(getFileFormatLabel({ name: "d.docx" })).toBe("Word 文档");
    expect(getFileFormatLabel({ name: "e.pdf" })).toBe("PDF");
    expect(getFileFormatLabel({ name: "f.png" })).toBe("图片");
  });

  it("labels unknown by uppercase extension, extensionless as 文件", () => {
    expect(getFileFormatLabel({ name: "g.xlsx" })).toBe("XLSX");
    expect(getFileFormatLabel({ name: "h" })).toBe("文件");
  });
});

describe("formatFileSize", () => {
  it("formats bytes", () => {
    expect(formatFileSize(512)).toBe("512B");
  });

  it("formats kilobytes as integers", () => {
    expect(formatFileSize(8192)).toBe("8KB");
    expect(formatFileSize(1536)).toBe("2KB");
  });

  it("formats megabytes with one decimal", () => {
    expect(formatFileSize(1258291)).toBe("1.2MB");
    expect(formatFileSize(10_485_760)).toBe("10MB");
  });
});
