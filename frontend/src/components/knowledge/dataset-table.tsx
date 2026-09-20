"use client";

import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Dropdown, Input, Modal, Select, Space, Switch, Table, Tag, Tooltip, Typography, message } from "antd";
import type { MenuProps } from "antd";
import type { ColumnsType } from "antd/es/table";
import { DownOutlined, MoreOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import DataSurface from "@/components/ui/data-surface";
import { ragApi, type RagDocument } from "@/lib/rag-api";
import UploadModal from "./upload-modal";
import ChunkPreviewDrawer from "./chunk-preview-drawer";

type DocRow = RagDocument & { error_message?: string | null };

const PAGE_SIZE = 20;

const STATUS_OPTIONS = [
  { label: "全部状态", value: "" },
  { label: "已就绪", value: "ready" },
  { label: "排队中", value: "pending" },
  { label: "处理中", value: "processing" },
  { label: "失败", value: "failed" },
  { label: "已禁用", value: "disabled" },
];

const STATUS_META: Record<string, { color: string; label: string }> = {
  ready: { color: "green", label: "已就绪" },
  pending: { color: "gold", label: "排队中" },
  processing: { color: "blue", label: "处理中" },
  partial: { color: "orange", label: "部分成功" },
  failed: { color: "red", label: "失败" },
  disabled: { color: "default", label: "已禁用" },
};

function formatTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function hostOf(url: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export default function DatasetTable({ libraryId }: { libraryId: string }) {
  const [items, setItems] = useState<DocRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [actionError, setActionError] = useState("");
  const [actingId, setActingId] = useState<string | null>(null);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [previewDoc, setPreviewDoc] = useState<DocRow | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DocRow | null>(null);
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [batchActing, setBatchActing] = useState(false);

  const load = useCallback(
    async (p: number, kw: string, st: string, silent = false) => {
      if (!silent) setLoading(true);
      setError("");
      try {
        const result = await ragApi.listLibraryDocuments(libraryId, {
          page: p,
          pageSize: PAGE_SIZE,
          ...(kw ? { keyword: kw } : {}),
          ...(st ? { status: st } : {}),
        });
        setItems(result.items as DocRow[]);
        setTotal(result.total);
        setPage(result.page);
      } catch {
        setError("加载文档列表失败");
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [libraryId]
  );

  useEffect(() => {
    void (async () => {
      await load(1, "", "");
    })();
  }, [load]);

  const hasProcessing = items.some((item) => item.status === "pending" || item.status === "processing");

  useEffect(() => {
    if (!hasProcessing) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void load(page, keyword, status, true);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [hasProcessing, load, page, keyword, status]);

  async function handleToggle(record: DocRow) {
    setActingId(record.id);
    setActionError("");
    try {
      if (record.status === "disabled") {
        await ragApi.enable(record.id);
      } else {
        await ragApi.disable(record.id);
      }
      await load(page, keyword, status);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setActingId(null);
    }
  }

  async function handleBatchToggle(enable: boolean) {
    if (selectedRowKeys.length === 0) return;
    setBatchActing(true);
    setActionError("");
    try {
      await Promise.all(selectedRowKeys.map((id) => (enable ? ragApi.enable(String(id)) : ragApi.disable(String(id)))));
      message.success(enable ? "已批量启用" : "已批量禁用");
      setSelectedRowKeys([]);
      await load(page, keyword, status);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "批量操作失败");
    } finally {
      setBatchActing(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    setActionError("");
    try {
      await ragApi.deleteDocument(deleteTarget.id);
      message.success("文档已删除");
      setDeleteTarget(null);
      await load(page, keyword, status);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  }

  async function handleBatchDelete() {
    setDeleting(true);
    setActionError("");
    try {
      await Promise.all(selectedRowKeys.map((id) => ragApi.deleteDocument(String(id))));
      message.success("已批量删除");
      setSelectedRowKeys([]);
      setBatchDeleteOpen(false);
      await load(page, keyword, status);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "批量删除失败");
    } finally {
      setDeleting(false);
    }
  }

  function handleAction(key: string, record: DocRow) {
    if (key === "preview") setPreviewDoc(record);
    if (key === "source" && record.source_url) window.open(record.source_url, "_blank", "noopener,noreferrer");
    if (key === "rechunk") void handleReingest(record);
    if (key === "delete") setDeleteTarget(record);
  }

  async function handleReingest(record: DocRow) {
    setActionError("");
    try {
      await ragApi.reingestDocument(record.id);
      message.success("已重新入队，正在重新切分与向量化");
      await load(page, keyword, status);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "重新切分失败");
    }
  }


  const batchItems: MenuProps["items"] = [
    { key: "enable", label: "批量启用", disabled: batchActing },
    { key: "disable", label: "批量禁用", disabled: batchActing },
    { type: "divider" },
    { key: "delete", label: "批量删除", danger: true, disabled: batchActing },
  ];

  const columns: ColumnsType<DocRow> = [
    {
      title: "名称",
      dataIndex: "title",
      key: "title",
      ellipsis: true,
      render: (_: unknown, record: DocRow) => (
        <div>
          <div style={{ fontWeight: 600 }}>{record.title}</div>
          <div style={{ fontSize: 12, color: "#8b99ab" }}>
            {[hostOf(record.source_url), record.publisher].filter(Boolean).join(" · ") || "—"}
          </div>
        </div>
      ),
    },
    {
      title: "训练模式",
      key: "chunk_mode",
      width: 104,
      render: () => <Tag>直接分段</Tag>,
    },
    {
      title: "数据总量",
      dataIndex: "chunk_count",
      key: "chunk_count",
      width: 96,
      align: "center",
      render: (value: number) => (
        <span style={{ fontSize: 12 }}>
          <b>{value}</b> 块
        </span>
      ),
    },
    {
      title: "创建 / 更新时间",
      key: "timestamps",
      width: 176,
      render: (_: unknown, record: DocRow) => (
        <div style={{ fontSize: 12, color: "#8b99ab", lineHeight: 1.6 }}>
          <div>{formatTime(record.created_at)}</div>
          <div style={{ color: "#b3bcc7" }}>{formatTime(record.updated_at)}</div>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 96,
      render: (value: string, record: DocRow) => {
        const meta = STATUS_META[value] ?? { color: "default", label: value };
        if (value === "failed" && record.error_message) {
          return (
            <Tooltip title={record.error_message}>
              <Tag color={meta.color} title={record.error_message}>
                {meta.label}
              </Tag>
            </Tooltip>
          );
        }
        return <Tag color={meta.color}>{meta.label}</Tag>;
      },
    },
    {
      title: "启用",
      key: "enabled",
      width: 76,
      align: "center",
      render: (_: unknown, record: DocRow) => (
        <Switch
          checked={record.status !== "disabled"}
          loading={actingId === record.id}
          aria-label={record.title}
          onChange={() => void handleToggle(record)}
        />
      ),
    },
    {
      title: "",
      key: "actions",
      width: 56,
      render: (_: unknown, record: DocRow) => (
        <Dropdown
          trigger={["click"]}
          menu={{
            items: [
              { key: "preview", label: "预览切块" },
              { key: "source", label: "查看来源", disabled: !record.source_url },
              { key: "rechunk", label: "重新切分" },
              { type: "divider" },
              { key: "delete", label: "删除", danger: true },
            ],
            onClick: ({ key }) => handleAction(key, record),
          }}
        >
          <Button type="text" size="small" className="action-trigger" icon={<MoreOutlined />} aria-label="更多操作" />
        </Dropdown>
      ),
    },
  ];

  return (
    <>
      {error ? (
        <Alert
          type="error"
          title={error}
          showIcon
          style={{ marginBottom: 12 }}
          action={
            <Button size="small" onClick={() => void load(page, keyword, status)}>
              重新加载
            </Button>
          }
        />
      ) : null}
      <DataSurface>
        <div className="data-surface-toolbar">
          <Space wrap>
            <Input
              placeholder="搜索文档名 / 来源"
              prefix={<SearchOutlined />}
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onPressEnter={() => void load(1, keyword, status)}
              style={{ width: 220 }}
              allowClear
            />
            <Select
              value={status}
              onChange={(value) => {
                setStatus(value);
                void load(1, keyword, value);
              }}
              options={STATUS_OPTIONS}
              style={{ width: 140 }}
            />
            <Button onClick={() => void load(1, keyword, status)} autoInsertSpace={false}>
              查询
            </Button>
            <Dropdown
              menu={{
                items: batchItems,
                onClick: ({ key }) => {
                  if (key === "enable") void handleBatchToggle(true);
                  if (key === "disable") void handleBatchToggle(false);
                  if (key === "delete") setBatchDeleteOpen(true);
                },
              }}
              disabled={selectedRowKeys.length === 0}
            >
              <Button disabled={selectedRowKeys.length === 0}>
                批量操作 <DownOutlined />
              </Button>
            </Dropdown>
          </Space>
          <Space>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              共 {total} 篇文档
            </Typography.Text>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>
              新建 / 导入
            </Button>
          </Space>
        </div>

        {actionError ? (
          <div style={{ padding: "0 18px 12px" }}>
            <Alert type="error" title={actionError} showIcon />
          </div>
        ) : null}

        <Table
          rowKey="id"
          dataSource={items}
          columns={columns}
          loading={loading}
          size="small"
          rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p) => void load(p, keyword, status),
          }}
        />
      </DataSurface>

      <UploadModal
        libraryId={libraryId}
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onQueued={() => void load(page, keyword, status)}
      />

      <ChunkPreviewDrawer doc={previewDoc} open={previewDoc !== null} onClose={() => setPreviewDoc(null)} />

      <Modal
        title="删除文档"
        open={deleteTarget !== null}
        onCancel={() => setDeleteTarget(null)}
        onOk={() => void handleDelete()}
        okText="删除"
        cancelText="取消"
        okButtonProps={{ danger: true, autoInsertSpace: false }}
        confirmLoading={deleting}
        destroyOnHidden
      >
        <p>确认删除「{deleteTarget?.title}」吗？该操作不可撤销。</p>
      </Modal>

      <Modal
        title="批量删除文档"
        open={batchDeleteOpen}
        onCancel={() => setBatchDeleteOpen(false)}
        onOk={() => void handleBatchDelete()}
        okText="删除"
        cancelText="取消"
        okButtonProps={{ danger: true, autoInsertSpace: false }}
        confirmLoading={deleting}
        destroyOnHidden
      >
        <p>确认删除选中的 {selectedRowKeys.length} 篇文档吗？该操作不可撤销。</p>
      </Modal>
    </>
  );
}
