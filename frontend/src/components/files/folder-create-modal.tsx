"use client";

import { useState } from "react";
import { Modal, Input, Alert } from "antd";
import { api, ApiError } from "@/lib/api";

interface FolderCreateModalProps {
  open: boolean;
  parentId: string;
  onClose: () => void;
  onSuccess: () => void;
}

export default function FolderCreateModal({
  open,
  parentId,
  onClose,
  onSuccess,
}: FolderCreateModalProps) {
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  function handleClose() {
    setName("");
    setError("");
    setCreating(false);
    onClose();
  }

  async function handleCreate() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("请输入文件夹名称。");
      return;
    }

    setCreating(true);
    setError("");

    try {
      await api("/api/files/folders", {
        method: "POST",
        body: JSON.stringify({
          name: trimmed,
          parent_id: parentId || null,
        }),
        csrf: true,
      });
      handleClose();
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) {
        switch (err.status) {
          case 409:
            setError("该文件夹名称已存在。");
            break;
          default:
            setError(err.message || "创建失败，请稍后重试。");
        }
      } else {
        setError("创建失败，请稍后重试。");
      }
    } finally {
      setCreating(false);
    }
  }

  return (
    <Modal
      title="新建文件夹"
      open={open}
      onOk={handleCreate}
      onCancel={handleClose}
      okText={creating ? "创建中..." : "创建"}
      cancelText="取消"
      confirmLoading={creating}
      destroyOnHidden
    >
      {error && (
        <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} />
      )}
      <div style={{ marginBottom: 8 }}>文件夹名称：</div>
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        onPressEnter={handleCreate}
        placeholder="请输入文件夹名称"
        maxLength={100}
        disabled={creating}
      />
    </Modal>
  );
}
