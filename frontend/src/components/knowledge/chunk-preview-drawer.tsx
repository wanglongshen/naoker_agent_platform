"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert, Drawer, Empty, Pagination, Spin, Typography } from "antd";
import { ragApi, type RagDocument } from "@/lib/rag-api";

const PAGE_SIZE = 20;

interface ChunkRow {
  id: string;
  chunk_index: number;
  section_path: string | null;
  content: string;
}

interface ChunkPreviewDrawerProps {
  doc: RagDocument | null;
  open: boolean;
  onClose: () => void;
}

export default function ChunkPreviewDrawer({ doc, open, onClose }: ChunkPreviewDrawerProps) {
  const [items, setItems] = useState<ChunkRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const docId = doc?.id ?? null;

  const load = useCallback(async (p: number) => {
    if (!docId) return;
    setLoading(true);
    setError("");
    try {
      const result = await ragApi.listChunks(docId, p, PAGE_SIZE);
      setItems(result.items);
      setTotal(result.total);
      setPage(p);
    } catch {
      setError("加载切块失败");
    } finally {
      setLoading(false);
    }
  }, [docId]);

  useEffect(() => {
    if (!open || !docId) return;
    void (async () => {
      await load(1);
    })();
  }, [open, docId, load]);

  return (
    <Drawer
      title={doc ? `切块预览 · ${doc.title}` : "切块预览"}
      open={open}
      onClose={onClose}
      size="large"
      placement="right"
      destroyOnHidden
      styles={{ body: { padding: 16, display: "flex", flexDirection: "column", gap: 12 } }}
    >
      {error ? <Alert type="error" title={error} showIcon /> : null}
      {loading ? <Spin /> : null}

      {!loading && !error && items.length === 0 ? <Empty description="暂无切块" /> : null}

      {!loading && items.length > 0 ? (
        <div style={{ flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
          {items.map((chunk) => (
            <div
              key={chunk.id}
              style={{ border: "1px solid #f0ebe0", borderRadius: 8, padding: 12, background: "#fffdf9" }}
            >
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                #{chunk.chunk_index + 1}
                {chunk.section_path ? ` · ${chunk.section_path}` : ""}
              </Typography.Text>
              <Typography.Paragraph style={{ margin: "6px 0 0", fontSize: 13, lineHeight: 1.7 }}>
                {chunk.content}
              </Typography.Paragraph>
            </div>
          ))}
        </div>
      ) : null}

      {total > PAGE_SIZE ? (
        <div style={{ textAlign: "right" }}>
          <Pagination
            current={page}
            pageSize={PAGE_SIZE}
            total={total}
            showSizeChanger={false}
            onChange={(p) => void load(p)}
          />
        </div>
      ) : null}
    </Drawer>
  );
}
