"use client";

import { useEffect, useState } from "react";
import { Alert, Form, Input, Modal } from "antd";
import { ApiError } from "@/lib/api";
import { ragApi, type RagLibrary } from "@/lib/rag-api";

interface NewLibraryModalProps {
  open: boolean;
  library?: RagLibrary | null;
  onClose: () => void;
  onSaved: () => void;
}

interface LibraryFormValues {
  name: string;
  description?: string;
}

export default function NewLibraryModal({ open, library, onClose, onSaved }: NewLibraryModalProps) {
  const [form] = Form.useForm<LibraryFormValues>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const editing = Boolean(library);

  useEffect(() => {
    if (!open) return;
    if (library) {
      form.setFieldsValue({ name: library.name, description: library.description ?? undefined });
    } else {
      form.resetFields();
    }
  }, [open, library, form]);

  async function handleFinish(values: LibraryFormValues) {
    setSaving(true);
    setError("");
    try {
      if (library) {
        await ragApi.updateLibrary(library.id, {
          name: values.name,
          description: values.description ?? "",
        });
      } else {
        await ragApi.createLibrary({ name: values.name, description: values.description });
      }
      onClose();
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.code === "LIBRARY_NAME_EXISTS") {
        setError(err.message || "知识库名称已存在，请换一个名称。");
      } else if (err instanceof Error) {
        setError(err.message || "保存失败，请稍后重试。");
      } else {
        setError("保存失败，请稍后重试。");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={editing ? "编辑知识库" : "新建知识库"}
      open={open}
      onOk={() => form.submit()}
      onCancel={onClose}
      confirmLoading={saving}
      okText={editing ? "保存" : "创建"}
      cancelText="取消"
      okButtonProps={{ autoInsertSpace: false }}
      destroyOnHidden
      afterClose={() => {
        form.resetFields();
        setError("");
      }}
    >
      {error ? <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} /> : null}
      <Form form={form} layout="vertical" onFinish={handleFinish} noValidate>
        <Form.Item
          name="name"
          label="名称"
          rules={[{ required: true, whitespace: true, message: "请输入知识库名称。" }]}
        >
          <Input aria-label="名称" placeholder="例如：行业知识库" maxLength={120} disabled={saving} />
        </Form.Item>
        <Form.Item name="description" label="介绍">
          <Input.TextArea
            aria-label="介绍"
            placeholder="这个知识库收录什么内容、供谁使用"
            rows={3}
            maxLength={2000}
            disabled={saving}
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
