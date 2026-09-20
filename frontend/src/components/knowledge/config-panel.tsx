"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Descriptions, Form, Input, Modal, Select, Switch, Tag, Typography, message } from "antd";
import { ApiError } from "@/lib/api";
import { ragApi, type RagLibrary } from "@/lib/rag-api";

const VISIBILITY_OPTIONS = [
  { label: "仅管理员", value: "admins_only" },
  { label: "全员可见", value: "all_members" },
];

const MODEL_ITEMS = [
  { key: "embedding", label: "Embedding 模型", children: "bge-small-zh-v1.5 · 512 维" },
  { key: "runtime", label: "运行位置", children: "本地 CPU" },
  { key: "chunking", label: "切分方式", children: "标题感知 · 512 字符 / 64 重叠" },
  { key: "retrieval", label: "检索方式", children: "精确余弦 · Top-K 20" },
];

const SOURCE_ITEMS = [
  { key: "jinritemai", label: "抖音电商官方学习中心", enabled: true },
  { key: "others", label: "巨量算数 / 艾瑞 / 小红书种草学", enabled: false },
];

const PANEL_STYLE = {
  border: "1px solid #efe0d4",
  borderRadius: 12,
  background: "#fff",
  padding: 16,
} as const;

interface ConfigPanelProps {
  library: RagLibrary;
  onSaved: () => void;
}

interface LibraryFormValues {
  name: string;
  description?: string;
  visibility: string;
  retrieval_enabled: boolean;
}

export default function ConfigPanel({ library, onSaved }: ConfigPanelProps) {
  const router = useRouter();
  const [form] = Form.useForm<LibraryFormValues>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [clearOpen, setClearOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [forceOpen, setForceOpen] = useState(false);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    form.setFieldsValue({
      name: library.name,
      description: library.description ?? "",
      visibility: library.visibility,
      retrieval_enabled: library.retrieval_enabled,
    });
  }, [library, form]);

  async function handleFinish(values: LibraryFormValues) {
    setSaving(true);
    setError("");
    try {
      await ragApi.updateLibrary(library.id, {
        name: values.name,
        description: values.description ?? "",
        visibility: values.visibility,
        retrieval_enabled: values.retrieval_enabled,
      });
      message.success("配置已保存");
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  }

  async function handleClearDocuments() {
    setWorking(true);
    setError("");
    try {
      const ids: string[] = [];
      let page = 1;
      for (;;) {
        const result = await ragApi.listLibraryDocuments(library.id, { page, pageSize: 100 });
        ids.push(...result.items.map((item) => item.id));
        if (result.items.length === 0 || ids.length >= result.total) break;
        page += 1;
      }
      await Promise.all(ids.map((id) => ragApi.deleteDocument(id)));
      message.success(`已清空 ${ids.length} 篇文档`);
      setClearOpen(false);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "清空文档失败，请稍后重试。");
    } finally {
      setWorking(false);
    }
  }

  async function handleDelete(force: boolean) {
    setWorking(true);
    setError("");
    try {
      await ragApi.deleteLibrary(library.id, force);
      message.success("知识库已删除");
      router.push("/knowledge");
    } catch (err) {
      if (!force && err instanceof ApiError && err.code === "LIBRARY_NOT_EMPTY") {
        setDeleteOpen(false);
        setForceOpen(true);
      } else {
        setError(err instanceof Error ? err.message : "删除失败，请稍后重试。");
      }
    } finally {
      setWorking(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {error ? <Alert type="error" title={error} showIcon /> : null}

      <div style={PANEL_STYLE}>
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          基础信息
        </Typography.Title>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          名称与介绍会显示在库列表和检索结果来源里
        </Typography.Text>
        <Form form={form} layout="vertical" onFinish={handleFinish} noValidate style={{ marginTop: 12 }}>
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, whitespace: true, message: "请输入知识库名称。" }]}
          >
            <Input aria-label="名称" maxLength={120} disabled={saving} />
          </Form.Item>
          <Form.Item name="description" label="介绍">
            <Input.TextArea aria-label="介绍" rows={3} maxLength={2000} disabled={saving} />
          </Form.Item>
          <Form.Item name="visibility" label="可见范围">
            <Select aria-label="可见范围" options={VISIBILITY_OPTIONS} disabled={saving} />
          </Form.Item>
          <Form.Item name="retrieval_enabled" label="参与检索" valuePropName="checked">
            <Switch aria-label="参与检索" disabled={saving} />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={saving} autoInsertSpace={false}>
            保存
          </Button>
        </Form>
      </div>

      <div style={PANEL_STYLE}>
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          向量与切分
        </Typography.Title>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          当前为平台默认，改动只影响后续新入库文档
        </Typography.Text>
        <Descriptions column={1} size="small" items={MODEL_ITEMS} style={{ marginTop: 8 }} />
      </div>

      <div style={PANEL_STYLE}>
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          采集来源（白名单）
        </Typography.Title>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          仅采集已审批的公开来源，默认关闭、逐源开启
        </Typography.Text>
        <Descriptions
          column={1}
          size="small"
          style={{ marginTop: 8 }}
          items={SOURCE_ITEMS.map((item) => ({
            key: item.key,
            label: item.label,
            children: <Tag color={item.enabled ? "green" : "default"}>{item.enabled ? "已启用" : "未启用"}</Tag>,
          }))}
        />
      </div>

      <div style={{ ...PANEL_STYLE, borderColor: "#f0cfcf" }}>
        <Typography.Title level={5} style={{ marginTop: 0, color: "#cf1322" }}>
          危险区
        </Typography.Title>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          以下操作不可撤销
        </Typography.Text>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 12 }}>
          <span style={{ fontSize: 13 }}>清空本库全部文档（{library.stats.doc_count} 篇）</span>
          <Button danger onClick={() => setClearOpen(true)} disabled={library.stats.doc_count === 0}>
            清空
          </Button>
        </div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 10 }}>
          <span style={{ fontSize: 13 }}>删除本库</span>
          <Button danger onClick={() => setDeleteOpen(true)}>
            删除
          </Button>
        </div>
      </div>

      <Modal
        title="清空文档"
        open={clearOpen}
        onCancel={() => setClearOpen(false)}
        onOk={() => void handleClearDocuments()}
        okText="清空"
        cancelText="取消"
        okButtonProps={{ danger: true, autoInsertSpace: false }}
        confirmLoading={working}
        destroyOnHidden
      >
        <p>确认清空「{library.name}」的全部 {library.stats.doc_count} 篇文档吗？该操作不可撤销。</p>
      </Modal>

      <Modal
        title="删除知识库"
        open={deleteOpen}
        onCancel={() => setDeleteOpen(false)}
        onOk={() => void handleDelete(false)}
        okText="删除"
        cancelText="取消"
        okButtonProps={{ danger: true, autoInsertSpace: false }}
        confirmLoading={working}
        destroyOnHidden
      >
        <p>确认删除「{library.name}」吗？该操作不可撤销。</p>
      </Modal>

      <Modal
        title="知识库非空"
        open={forceOpen}
        onCancel={() => setForceOpen(false)}
        onOk={() => void handleDelete(true)}
        okText="强制删除"
        cancelText="取消"
        okButtonProps={{ danger: true, autoInsertSpace: false }}
        confirmLoading={working}
        destroyOnHidden
      >
        <p>
          该知识库仍有 {library.stats.doc_count} 篇文档。请先清空文档，或选择「强制删除」一并删除全部文档与向量。
        </p>
      </Modal>
    </div>
  );
}
