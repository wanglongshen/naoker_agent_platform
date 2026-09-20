"use client";

import { useState } from "react";
import { Alert, Button, Empty, Input, Progress, Select, Space, Spin, Tag, Typography } from "antd";
import { ragApi, type RagSearchHit } from "@/lib/rag-api";

const TOP_K_OPTIONS = [
  { label: "Top-K 3", value: 3 },
  { label: "Top-K 5", value: 5 },
  { label: "Top-K 10", value: 10 },
];

export default function SearchTestPanel({ libraryId }: { libraryId: string }) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [hits, setHits] = useState<RagSearchHit[] | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch() {
    const trimmed = query.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    try {
      const result = await ragApi.search(trimmed, topK, libraryId);
      setHits(result.items);
      setElapsedMs(result.elapsed_ms);
    } catch (err) {
      setHits(null);
      setElapsedMs(null);
      setError(err instanceof Error ? err.message : "检索失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <Space wrap>
        <Select value={topK} onChange={setTopK} options={TOP_K_OPTIONS} style={{ width: 110 }} aria-label="Top-K" />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          仅启用文档参与召回
        </Typography.Text>
      </Space>

      <Space.Compact style={{ width: "100%" }}>
        <Input
          placeholder="输入问题，验证本库召回效果"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPressEnter={() => void handleSearch()}
          allowClear
        />
        <Button type="primary" autoInsertSpace={false} loading={loading} onClick={() => void handleSearch()}>
          检索
        </Button>
      </Space.Compact>

      {elapsedMs !== null ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          命中 {hits?.length ?? 0} 个知识块 · {elapsedMs} ms
        </Typography.Text>
      ) : null}

      {error ? <Alert type="error" title={error} showIcon /> : null}
      {loading ? <Spin /> : null}

      {!loading && hits && hits.length === 0 ? <Empty description="未命中任何知识块" /> : null}

      {!loading && hits && hits.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {hits.map((hit, index) => (
            <div
              key={hit.chunk_id}
              style={{ border: "1px solid #f0ebe0", borderRadius: 10, padding: 14, background: "#fffdf9" }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
                <Space size={8} wrap>
                  <Tag color="green">命中 #{index + 1}</Tag>
                  <Typography.Text strong>{hit.title}</Typography.Text>
                  {hit.publisher ? <Tag>{hit.publisher}</Tag> : null}
                </Space>
                <Space size={8}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    相似度 {hit.score.toFixed(3)}
                  </Typography.Text>
                  <Progress
                    percent={Math.round(hit.score * 100)}
                    showInfo={false}
                    size="small"
                    style={{ width: 80, margin: 0 }}
                  />
                </Space>
              </div>

              {hit.section_path ? (
                <div style={{ marginTop: 6 }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {hit.section_path}
                  </Typography.Text>
                </div>
              ) : null}

              <Typography.Paragraph style={{ margin: "8px 0 0", fontSize: 13, lineHeight: 1.7 }}>
                {hit.content}
              </Typography.Paragraph>

              {hit.source_url ? (
                <a href={hit.source_url} target="_blank" rel="noreferrer noopener" style={{ fontSize: 12 }}>
                  来源链接
                </a>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
