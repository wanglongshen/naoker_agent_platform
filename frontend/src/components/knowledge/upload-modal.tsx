"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, InputNumber, Modal, Progress, Radio, Select, Tabs, Typography, Upload } from "antd";
import { InboxOutlined } from "@ant-design/icons";
import type { UploadFile } from "antd/es/upload/interface";
import { ragApi, type RagJob } from "@/lib/rag-api";

const ACCEPTED_EXTENSIONS = ["pdf", "docx", "xlsx", "pptx", "txt", "md", "csv", "html"];
const MAX_SIZE = 20 * 1024 * 1024;
const POLL_INTERVAL_MS = 3000;

function extensionOf(name: string): string {
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index + 1).toLowerCase() : "";
}

function isActive(job: RagJob): boolean {
  return job.status === "queued" || job.status === "running";
}

interface UploadModalProps {
  libraryId: string;
  open: boolean;
  onClose: () => void;
  onQueued: () => void;
}

export default function UploadModal({ libraryId, open, onClose, onQueued }: UploadModalProps) {
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [jobs, setJobs] = useState<RagJob[] | null>(null);
  const [tab, setTab] = useState<"upload" | "import">("upload");
  const [scope, setScope] = useState<"core" | "all">("core");
  const [category, setCategory] = useState<string | undefined>(undefined);
  const [limit, setLimit] = useState<number | null>(null);
  const [importing, setImporting] = useState(false);
  const pollTimer = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimer.current !== null) {
      window.clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const pollJobs = useCallback(async () => {
    try {
      const next = await ragApi.listJobs(libraryId, true);
      setJobs(next);
      if (next.some(isActive)) return;
      stopPolling();
      setJobs(null);
      onQueued();
      onClose();
    } catch (err) {
      stopPolling();
      setJobs(null);
      setError(err instanceof Error ? err.message : "获取处理进度失败");
    }
  }, [libraryId, onQueued, onClose, stopPolling]);

  const startPolling = useCallback(() => {
    stopPolling();
    void pollJobs();
    pollTimer.current = window.setInterval(() => {
      void pollJobs();
    }, POLL_INTERVAL_MS);
  }, [pollJobs, stopPolling]);

  useEffect(() => {
    if (open) return;
    stopPolling();
  }, [open, stopPolling]);

  useEffect(() => stopPolling, [stopPolling]);

  async function handleUpload() {
    const files = fileList.map((item) => item.originFileObj).filter((file): file is NonNullable<typeof file> => Boolean(file));
    if (files.length === 0) {
      setError("请先选择要上传的文件。");
      return;
    }
    setUploading(true);
    setError("");
    try {
      for (const file of files) {
        await ragApi.uploadDocument(libraryId, file);
      }
      setFileList([]);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败，请稍后重试。");
    } finally {
      setUploading(false);
    }
  }

  async function handleImport() {
    setImporting(true);
    setError("");
    try {
      const body: { scope: "core" | "all"; category?: string; limit?: number } = { scope };
      if (category) body.category = category;
      if (limit !== null && limit > 0) body.limit = limit;
      await ragApi.importCollected(libraryId, body);
      startPolling();
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败，请稍后重试。");
    } finally {
      setImporting(false);
    }
  }

  const activeJobs = (jobs ?? []).filter(isActive);
  const total = activeJobs.reduce((sum, job) => sum + job.total, 0);
  const processed = activeJobs.reduce((sum, job) => sum + job.processed, 0);

  return (
    <Modal
      title="新建 / 导入"
      open={open}
      onOk={() => void (tab === "upload" ? handleUpload() : handleImport())}
      onCancel={onClose}
      okText={tab === "upload" ? "开始上传" : "开始导入"}
      cancelText="取消"
      okButtonProps={{
        autoInsertSpace: false,
        disabled: tab === "upload" ? fileList.length === 0 : importing,
      }}
      confirmLoading={tab === "upload" ? uploading : importing}
      destroyOnHidden
      afterClose={() => {
        stopPolling();
        setFileList([]);
        setJobs(null);
        setError("");
        setUploading(false);
        setImporting(false);
        setTab("upload");
      }}
    >
      {error ? <Alert type="error" title={error} showIcon style={{ marginBottom: 12 }} /> : null}

      <Tabs
        activeKey={tab}
        onChange={(key) => setTab(key as "upload" | "import")}
        items={[
          {
            key: "upload",
            label: "上传文件",
            children: (
              <Upload.Dragger
                multiple
                accept={ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(",")}
                fileList={fileList}
                beforeUpload={(file) => {
                  const ext = extensionOf(file.name);
                  if (!ACCEPTED_EXTENSIONS.includes(ext)) {
                    setError(`不支持的文件类型：.${ext || "未知"}（支持 ${ACCEPTED_EXTENSIONS.join(" / ")}）`);
                    return Upload.LIST_IGNORE;
                  }
                  if (file.size > MAX_SIZE) {
                    setError(`文件「${file.name}」超过 20MB 限制。`);
                    return Upload.LIST_IGNORE;
                  }
                  setError("");
                  return false;
                }}
                onChange={({ fileList: next }) => setFileList(next)}
                disabled={uploading}
              >
                <p className="ant-upload-drag-icon">
                  <InboxOutlined />
                </p>
                <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
                <p className="ant-upload-hint">支持 {ACCEPTED_EXTENSIONS.join(" / ")}，单个文件不超过 20MB</p>
              </Upload.Dragger>
            ),
          },
          {
            key: "import",
            label: "从已采集素材导入",
            children: (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div>
                  <Typography.Text type="secondary">素材范围</Typography.Text>
                  <Radio.Group
                    value={scope}
                    onChange={(event) => setScope(event.target.value as "core" | "all")}
                    style={{ display: "block", marginTop: 6 }}
                  >
                    <Radio value="core">核心方法论白名单（226 篇）</Radio>
                    <Radio value="all">全部已采集素材（601 篇）</Radio>
                  </Radio.Group>
                </div>
                <div>
                  <Typography.Text type="secondary">分类筛选（可选）</Typography.Text>
                  <Select
                    allowClear
                    placeholder="全部"
                    value={category}
                    onChange={(value) => setCategory(value)}
                    style={{ width: "100%", marginTop: 6 }}
                    options={[
                      { value: "methodology", label: "方法论" },
                      { value: "rules", label: "规则 / 协议" },
                      { value: "other", label: "其他" },
                    ]}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary">数量上限（可选，1-2000）</Typography.Text>
                  <InputNumber
                    min={1}
                    max={2000}
                    value={limit}
                    onChange={(value) => setLimit(value ?? null)}
                    placeholder="留空表示不限"
                    style={{ width: "100%", marginTop: 6 }}
                  />
                </div>
                <Typography.Text type="secondary">
                  素材位于服务端 var/kb_industry（601 篇已采集，其中核心方法论 226 篇）；已在库中的重复内容会自动跳过。
                </Typography.Text>
              </div>
            ),
          },
        ]}
      />

      {jobs !== null ? (
        <div style={{ marginTop: 16 }}>
          <Typography.Text>
            处理中 {processed}/{total}
          </Typography.Text>
          <Progress percent={total > 0 ? Math.round((processed / total) * 100) : 0} status="active" />
        </div>
      ) : null}
    </Modal>
  );
}
