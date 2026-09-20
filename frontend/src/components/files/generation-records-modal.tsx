"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, Empty, List, Modal, Pagination, Tag } from "antd";
import { listGenerations, getGenerationTimeline, type GenerationLog, type GenerationTimelineStep } from "@/lib/api";

const PAGE_SIZE = 10;

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function truncate(text: string, max: number): string {
  if (!text || text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function StatusTag({ log }: { log: GenerationLog }) {
  if (log.status === "succeeded") {
    return <Tag color="green">{log.feishu_doc_url ? "已同步飞书" : "成功"}</Tag>;
  }
  if (log.status === "failed") {
    return <Tag color="red">失败</Tag>;
  }
  return <Tag color="default">待处理</Tag>;
}

interface GenerationRecordsModalProps {
  open: boolean;
  folderId?: string | null;
  onClose: () => void;
}

export default function GenerationRecordsModal({ open, folderId, onClose }: GenerationRecordsModalProps) {
  const [logs, setLogs] = useState<GenerationLog[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [detailLog, setDetailLog] = useState<GenerationLog | null>(null);
  const [timeline, setTimeline] = useState<GenerationTimelineStep[] | null>(null);

  const fetchRecords = useCallback(
    async (targetPage: number) => {
      setLoading(true);
      try {
        const data = await listGenerations({
          folderId: folderId || null,
          page: targetPage,
          pageSize: PAGE_SIZE,
        });
        setLogs(data.logs);
        setTotal(data.total);
        setPage(targetPage);
      } catch {
        setLogs([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [folderId],
  );

  useEffect(() => {
    if (open) {
      setDetailLog(null);
      fetchRecords(1);
    }
  }, [open, fetchRecords]);

  useEffect(() => {
    if (!detailLog) {
      setTimeline(null);
      return;
    }
    let alive = true;
    getGenerationTimeline(detailLog.id)
      .then((d) => {
        if (alive) setTimeline(d.steps);
      })
      .catch(() => {
        if (alive) setTimeline([]);
      });
    return () => {
      alive = false;
    };
  }, [detailLog]);

  return (
    <>
      <Modal open={open} title="生成记录" footer={null} onCancel={onClose} width={720}>
        {logs.length === 0 && !loading ? (
          <Empty description="暂无生成记录" />
        ) : (
          <List
            dataSource={logs}
            loading={loading}
            renderItem={(log) => (
              <List.Item
                actions={[
                  <Button key="detail" size="small" onClick={() => setDetailLog(log)}>
                    详情
                  </Button>,
                ]}
              >
                <div style={{ width: "100%" }}>
                  <StatusTag log={log} />
                  <div style={{ fontSize: 13, marginTop: 4 }}>{truncate(log.input_text, 60)}</div>
                  <div style={{ fontSize: 12, color: "#888", marginTop: 4 }}>
                    {formatTime(log.created_at)}
                  </div>
                </div>
              </List.Item>
            )}
          />
        )}
        {total > PAGE_SIZE && (
          <Pagination
            current={page}
            pageSize={PAGE_SIZE}
            total={total}
            onChange={(next) => fetchRecords(next)}
            showTotal={(t) => `共 ${t} 条`}
            style={{ marginTop: 12 }}
          />
        )}
      </Modal>

      <Modal open={detailLog !== null} title="生成详情" footer={null} onCancel={() => setDetailLog(null)} width={640}>
        {detailLog && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ fontSize: 12, color: "#888" }}>{formatTime(detailLog.created_at)}</div>
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>输入内容</div>
              <div
                style={{
                  maxHeight: 240,
                  overflowY: "auto",
                  fontSize: 13,
                  whiteSpace: "pre-wrap",
                  background: "#fafafa",
                  padding: 8,
                  borderRadius: 4,
                }}
              >
                {detailLog.input_text}
              </div>
            </div>
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>生成结果</div>
              <div
                style={{
                  maxHeight: 240,
                  overflowY: "auto",
                  fontSize: 13,
                  whiteSpace: "pre-wrap",
                  background: "#fafafa",
                  padding: 8,
                  borderRadius: 4,
                }}
              >
                {truncate(detailLog.final_answer, 2000)}
              </div>
            </div>
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>过程稿</div>
              {timeline === null ? (
                <div style={{ fontSize: 13, color: "#888" }}>加载中…</div>
              ) : timeline.length === 0 ? (
                <div style={{ fontSize: 13, color: "#888" }}>暂无过程记录</div>
              ) : (
                <div
                  style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 360, overflowY: "auto" }}
                >
                  {timeline.map((step, idx) => (
                    <TimelineStepView key={idx} step={step} />
                  ))}
                </div>
              )}
            </div>
            {detailLog.feishu_doc_url && (
              <div>
                <a href={detailLog.feishu_doc_url} target="_blank" rel="noreferrer">
                  打开飞书文档
                </a>
              </div>
            )}
            {detailLog.error && <div style={{ color: "#cf1322", fontSize: 13 }}>{detailLog.error}</div>}
          </div>
        )}
      </Modal>
    </>
  );
}

const STEP_META: Record<string, { icon: string; label: string; color: string }> = {
  thought: { icon: "💭", label: "思考", color: "#2f54eb" },
  tool: { icon: "🔧", label: "工具", color: "#722ed1" },
  answer: { icon: "📄", label: "答案", color: "#52c41a" },
  terminal: { icon: "✅", label: "完成", color: "#52c41a" },
};

function TimelineStepView({ step }: { step: GenerationTimelineStep }) {
  const isFailed = step.type === "terminal" && step.status === "failed";
  const [expanded, setExpanded] = useState(isFailed);
  const meta = STEP_META[step.type] ?? { icon: "•", label: step.type, color: "#888" };
  return (
    <div
      style={{
        border: `1px solid ${isFailed ? "#ff4d4f" : "#f0f0f0"}`,
        borderRadius: 8,
        padding: "8px 10px",
        background: isFailed ? "#fff2f0" : "#fafafa",
        cursor: "pointer",
      }}
      onClick={() => setExpanded((v) => !v)}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
        <span>{meta.icon}</span>
        <span style={{ fontWeight: 600, color: meta.color }}>
          {step.type === "tool"
            ? `${meta.label} · ${step.action_type}${step.step_index !== undefined ? `（步骤 ${step.step_index + 1}）` : ""}`
            : `${meta.label}${step.step_index !== undefined ? `（步骤 ${step.step_index + 1}）` : ""}`}
        </span>
        {step.duration_seconds !== undefined && (
          <span style={{ color: "#888" }}>耗时 {step.duration_seconds.toFixed(1)}s</span>
        )}
        {isFailed && <span style={{ color: "#cf1322" }}>失败</span>}
        <span style={{ marginLeft: "auto", color: "#bbb" }}>{expanded ? "收起" : "展开"}</span>
      </div>
      {expanded && (
        <div style={{ marginTop: 8, fontSize: 13, whiteSpace: "pre-wrap" }}>
          {step.type === "tool" ? (
            <>
              {step.input && Object.keys(step.input).length > 0 && (
                <pre style={{ background: "#fff", borderRadius: 4, padding: 8, fontSize: 12, margin: "0 0 8px" }}>
                  {JSON.stringify(step.input, null, 2)}
                </pre>
              )}
              {step.observation && <div style={{ color: "#444" }}>{step.observation}</div>}
            </>
          ) : step.type === "terminal" && step.error ? (
            <div style={{ color: "#cf1322" }}>{step.error}</div>
          ) : (
            <div>{step.content ?? ""}</div>
          )}
        </div>
      )}
    </div>
  );
}
