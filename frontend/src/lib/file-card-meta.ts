export type FileTypeIconKey = "text" | "doc" | "pdf" | "image" | "generic";

const TEXT_EXTENSIONS = new Set(["md", "markdown", "txt", "text"]);
const DOC_EXTENSIONS = new Set(["doc", "docx"]);
const PDF_EXTENSIONS = new Set(["pdf"]);
const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico"]);

function extensionOf(name: string): string {
  const idx = name.lastIndexOf(".");
  if (idx < 0 || idx === name.length - 1) return "";
  return name.slice(idx + 1).toLowerCase();
}

export function getFileTypeIconKey(file: { name: string; type?: string }): FileTypeIconKey {
  const mime = (file.type || "").toLowerCase();
  if (mime.startsWith("image/")) return "image";
  if (mime === "application/pdf") return "pdf";
  if (mime.startsWith("text/") || mime === "application/json" || mime.includes("markdown")) {
    const ext = extensionOf(file.name);
    if (ext && ext !== "md" && ext !== "markdown" && ext !== "txt") return "generic";
    return "text";
  }
  const ext = extensionOf(file.name);
  if (TEXT_EXTENSIONS.has(ext)) return "text";
  if (DOC_EXTENSIONS.has(ext)) return "doc";
  if (PDF_EXTENSIONS.has(ext)) return "pdf";
  if (IMAGE_EXTENSIONS.has(ext)) return "image";
  return "generic";
}

export function getFileFormatLabel(file: { name: string; type?: string }): string {
  const key = getFileTypeIconKey(file);
  const ext = extensionOf(file.name);
  if (key === "text") {
    if (ext === "md" || ext === "markdown") return "Markdown";
    return "文本";
  }
  if (key === "doc") return "Word 文档";
  if (key === "pdf") return "PDF";
  if (key === "image") return "图片";
  return ext ? ext.toUpperCase() : "文件";
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)}KB`;
  const mb = kb / 1024;
  const rounded = Math.round(mb * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}MB`;
}
