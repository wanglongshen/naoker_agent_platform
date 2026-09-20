"use client";

import { useEffect, useState } from "react";
import { Button, Empty, InputNumber, Modal, Space, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { adminCreateRedeemCodes, adminListRedeemCodes } from "@/lib/api";

interface RedeemCodeRow {
  code: string;
  points: number;
  used_by: string | null;
  used_at: string | null;
  created_at: string;
}

interface RedeemCodesModalProps {
  open: boolean;
  onClose: () => void;
}

const PAGE_SIZE = 20;

const TIERS = [100, 500, 1000, 5000];

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN");
}

export default function RedeemCodesModal({ open, onClose }: RedeemCodesModalProps) {
  const [points, setPoints] = useState<number | null>(100);
  const [count, setCount] = useState<number | null>(1);
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState<string[]>([]);
  const [codes, setCodes] = useState<RedeemCodeRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  async function loadCodes(targetPage: number) {
    setLoading(true);
    try {
      const data = await adminListRedeemCodes(targetPage, PAGE_SIZE);
      setCodes(data.codes ?? []);
      setTotal(data.total ?? 0);
      setPage(targetPage);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "加载兑换码失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) {
      setGenerated([]);
      void loadCodes(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function handleGenerate() {
    if (!points || points <= 0 || !count || count < 1) {
      message.warning("请输入有效的积点与数量");
      return;
    }
    setGenerating(true);
    try {
      const data = await adminCreateRedeemCodes(points, count);
      setGenerated(data.codes ?? []);
      void loadCodes(1);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "生成失败");
    } finally {
      setGenerating(false);
    }
  }

  async function handleCopy(code: string) {
    try {
      await navigator.clipboard.writeText(code);
      message.success("已复制");
    } catch {
      // clipboard unavailable; ignore
    }
  }

  const columns: ColumnsType<RedeemCodeRow> = [
    {
      title: "兑换码",
      key: "code",
      render: (_, row) => <span style={{ fontFamily: "monospace" }}>{row.code}</span>,
    },
    {
      title: "积点",
      key: "points",
      width: 90,
      render: (_, row) => row.points.toLocaleString(),
    },
    {
      title: "状态",
      key: "status",
      width: 90,
      render: (_, row) => (row.used_by ? <Tag>已使用</Tag> : <Tag color="green">未使用</Tag>),
    },
    {
      title: "创建时间",
      key: "created_at",
      width: 180,
      render: (_, row) => (
        <span style={{ fontSize: 12, color: "#888" }}>{row.created_at ? formatTime(row.created_at) : "—"}</span>
      ),
    },
  ];

  return (
    <Modal
      title="兑换码管理"
      open={open}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnHidden
    >
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>生成兑换码</div>
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          {TIERS.map((tier) => {
            const active = points === tier;
            return (
              <div
                key={tier}
                onClick={() => setPoints(tier)}
                style={{
                  flex: 1,
                  textAlign: "center",
                  cursor: "pointer",
                  background: active ? "#FFF0E4" : "#fff",
                  border: `1px solid ${active ? "#D96313" : "#f0e6dd"}`,
                  borderRadius: 10,
                  padding: "10px 6px",
                }}
              >
                <div style={{ fontSize: 15, fontWeight: 700, color: active ? "#B94F0C" : "#2A1812" }}>
                  {tier.toLocaleString()}
                </div>
                <div style={{ fontSize: 10, color: "#9c8b7d", marginTop: 2 }}>
                  = {(tier * 10000).toLocaleString()} token
                </div>
              </div>
            );
          })}
        </div>
        <Space wrap>
          <InputNumber
            placeholder="积点"
            min={1}
            max={1000000}
            value={points}
            onChange={(v) => setPoints(v)}
            style={{ width: 120 }}
          />
          <InputNumber
            placeholder="数量"
            min={1}
            max={50}
            value={count}
            onChange={(v) => setCount(v)}
            style={{ width: 100 }}
          />
          <Button type="primary" loading={generating} onClick={() => void handleGenerate()}>
            生成
          </Button>
        </Space>
        {generated.length > 0 && (
          <div style={{ marginTop: 12 }}>
            {generated.map((code) => (
              <div key={code} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                <span style={{ fontFamily: "monospace" }}>{code}</span>
                <Button size="small" onClick={() => void handleCopy(code)}>
                  复制
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>历史兑换码</div>
      <Table
        rowKey="code"
        columns={columns}
        dataSource={codes}
        loading={loading}
        pagination={{
          current: page,
          pageSize: PAGE_SIZE,
          total,
          onChange: (p) => void loadCodes(p),
          showSizeChanger: false,
        }}
        locale={{ emptyText: <Empty description="暂无兑换码" /> }}
        scroll={{ x: 560 }}
      />
    </Modal>
  );
}
