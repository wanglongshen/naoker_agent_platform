"use client";

import { useState, useEffect } from "react";
import { Drawer, Result, Skeleton, Button } from "antd";
import { FileUnknownOutlined, DownloadOutlined } from "@ant-design/icons";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { FileListItem } from "@/types/file";

interface PreviewDrawerProps {
  open: boolean;
  file: FileListItem | null;
  onClose: () => void;
}

function classifyPreview(mediaType: string): "pdf" | "image" | "video" | "audio" | "markdown" | "text" | "document" | "unsupported" {
  if (mediaType === "application/pdf") return "pdf";
  if (mediaType.startsWith("image/")) return "image";
  if (mediaType.startsWith("video/")) return "video";
  if (mediaType.startsWith("audio/")) return "audio";
  if (mediaType === "text/markdown") return "markdown";
  if (
    mediaType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    mediaType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" ||
    mediaType === "application/vnd.openxmlformats-officedocument.presentationml.presentation"
  ) {
    return "document";
  }
  if (mediaType.startsWith("text/") || mediaType === "application/json") return "text";
  return "unsupported";
}

const TEXT_CATEGORIES = ["text", "markdown", "document"];

function classifyHref(href: string | undefined): { href: string; external: boolean } {
  if (!href) return { href: "", external: false };
  if (href.includes("\\")) return { href: "", external: false };
  try {
    const url = new URL(href);
    return ["http:", "https:", "mailto:"].includes(url.protocol)
      ? { href, external: true }
      : { href: "", external: false };
  } catch {
    return { href: "", external: false };
  }
}

const mdComponents = {
  a: ({ href, children, ...props }: any) => {
    const { href: safeHref, external } = classifyHref(href);
    return (
      <a href={safeHref} {...(external ? { target: "_blank", rel: "noreferrer noopener" } : {})} {...props}>
        {children}
        {external ? <span className="sr-only">（在新标签页中打开）</span> : null}
      </a>
    );
  },
  table: ({ children, ...props }: any) => (
    <div className="table-scroll" tabIndex={0}><table {...props}>{children}</table></div>
  ),
  pre: ({ children, ...props }: any) => (
    <div className="code-scroll" tabIndex={0}><pre {...props}>{children}</pre></div>
  ),
};

export default function PreviewDrawer({ open, file, onClose }: PreviewDrawerProps) {
  const [textContent, setTextContent] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open && file) {
      const category = classifyPreview(file.media_type);
      if (TEXT_CATEGORIES.includes(category)) {
        setLoading(true);
        const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
        fetch(`${base}/api/files/${file.id}/preview`, { credentials: "include" })
          .then((r) => r.json())
          .then((d) => { setTextContent(d.data?.content ?? ""); setLoading(false); })
          .catch(() => { setTextContent("无法加载文本内容。"); setLoading(false); });
      }
    }
  }, [open, file]);

  function renderPreview() {
    if (!file) return null;
    if (loading) return <Skeleton active paragraph={{ rows: 12 }} />;

    const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
    const url = `${base}/api/files/${file.id}/download`;
    const category = classifyPreview(file.media_type);

    switch (category) {
      case "pdf":
        return <iframe src={url} style={{ width: "100%", height: "100%", border: "none", flex: 1 }} title={file.original_filename} />;
      case "image":
        return <div style={{ textAlign: "center", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}><img src={url} alt={file.original_filename} style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }} /></div>;
      case "video":
        return <video controls style={{ width: "100%", height: "100%", objectFit: "contain" }} src={url} />;
      case "audio":
        return <div style={{ height: "100%", display: "flex", alignItems: "center" }}><audio controls style={{ width: "100%" }} src={url} /></div>;
      case "text":
      case "document":
        return <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", height: "100%", overflow: "auto", background: "var(--warm-surface, #faf8f5)", padding: 16, borderRadius: 8, fontSize: 13, lineHeight: 1.6 }}>{textContent}</pre>;
      case "markdown":
        return (
          <div style={{ height: "100%", overflow: "auto", fontSize: 14, lineHeight: 1.7, padding: 8 }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml components={mdComponents}>{textContent}</ReactMarkdown>
          </div>
        );
      default:
        return (
          <Result
            icon={<FileUnknownOutlined />}
            title="预览不可用"
            subTitle={`文件类型 "${file.media_type}" 暂不支持在线预览`}
            extra={<Button type="primary" icon={<DownloadOutlined />} href={url} download={file.original_filename}>下载文件</Button>}
          />
        );
    }
  }

  return (
    <Drawer title={file?.original_filename ?? "预览"} open={open} onClose={onClose} size="large" placement="right" destroyOnHidden styles={{ body: { padding: 16, height: "calc(100vh - 55px)", display: "flex", flexDirection: "column" } }}>
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {renderPreview()}
      </div>
    </Drawer>
  );
}
