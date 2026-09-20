"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Statistic, Typography } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { ragApi, type RagLibrary } from "@/lib/rag-api";
import { EmptyState, PageError, PageLoading } from "@/components/ui/view-states";
import LibraryCard from "./library-card";
import NewLibraryModal from "./new-library-modal";

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function LibraryGrid() {
  const router = useRouter();
  const [libraries, setLibraries] = useState<RagLibrary[]>([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await ragApi.listLibraries();
      setLibraries([...data].sort((a, b) => b.stats.doc_count - a.stats.doc_count));
      setError("");
    } catch {
      setError("加载知识库列表失败");
    } finally {
      setInitialLoading(false);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      await load();
    })();
  }, [load]);

  const totalDocs = libraries.reduce((sum, library) => sum + library.stats.doc_count, 0);
  const totalChunks = libraries.reduce((sum, library) => sum + library.stats.chunk_count, 0);
  const lastUpdated = libraries.reduce<string | null>((latest, library) => {
    const value = library.stats.last_updated_at;
    if (!value) return latest;
    return latest === null || value > latest ? value : latest;
  }, null);

  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 16,
        }}
      >
        <Typography.Text type="secondary">共 {libraries.length} 个知识库</Typography.Text>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          aria-label="新建知识库（工具栏）"
          onClick={() => setCreateOpen(true)}
        >
          新建知识库
        </Button>
      </div>

      {initialLoading ? (
        <PageLoading />
      ) : error && libraries.length === 0 ? (
        <PageError message={error} onRetry={() => void load()} />
      ) : libraries.length === 0 ? (
        <div style={{ padding: "36px 0" }}>
          <EmptyState message="还没有知识库，点击「新建知识库」开始组织文档。" />
        </div>
      ) : (
        <>
          <div
            className="page-summary"
            style={{
              gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
              marginTop: 0,
              marginBottom: 18,
              paddingBottom: 0,
            }}
          >
            <div className="summary-card">
              <Statistic title="知识库" value={libraries.length} />
            </div>
            <div className="summary-card">
              <Statistic title="文档总数" value={totalDocs} />
            </div>
            <div className="summary-card">
              <Statistic title="文本块总数" value={totalChunks} />
            </div>
            <div className="summary-card">
              <Statistic title="最近入库" value={formatTime(lastUpdated)} />
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 16,
            }}
          >
            {libraries.map((library) => (
              <LibraryCard
                key={library.id}
                library={library}
                onOpen={() => router.push(`/knowledge/${library.id}`)}
                onChanged={() => void load()}
              />
            ))}
            <button
              type="button"
              aria-label="新建知识库（占位卡片）"
              onClick={() => setCreateOpen(true)}
              style={{
                minHeight: 140,
                border: "1px dashed #d5c8be",
                borderRadius: 14,
                background: "#fffdf9",
                color: "#765f52",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 6,
              }}
            >
              <PlusOutlined /> 新建知识库
            </button>
          </div>
        </>
      )}

      <NewLibraryModal open={createOpen} onClose={() => setCreateOpen(false)} onSaved={() => void load()} />
    </>
  );
}
