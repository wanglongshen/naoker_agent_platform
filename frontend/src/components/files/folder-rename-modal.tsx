"use client";

import { useState } from "react";
import { Modal, Input, Alert } from "antd";
import { api, ApiError } from "@/lib/api";

interface FolderRenameModalProps {
  open: boolean;
  folderName: string;
  folderId: string;
  onClose: () => void;
  onSuccess: () => void;
}

export default function FolderRenameModal({
  open,
  folderName,
  folderId,
  onClose,
  onSuccess,
}: FolderRenameModalProps) {
  const [name, setName] = useState(folderName);
  const [renaming, setRenaming] = useState(false);
  const [error, setError] = useState("");

  function handleClose() {
    setName(folderName);
    setError("");
    setRenaming(false);
    onClose();
  }

  async function handleRename() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("请输入文件夹名称。");
      return;
    }

    setRenaming(true);
    setError("");

    try {
      await api(`/api/files/folders/${folderId}`, {
        method: "PUT",
        body: JSON.stringify({ name: trimmed }),
        csrf: true,
      });
      handleClose();
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message || "重命名失败，请稍后重试。");
      } else {
        setError("重命名失败，请稍后重试。");
      }
    } finally {
      setRenaming(false);
    }
  }

  return (
    <Modal
      title="重命名文件夹"
      open={open}
      onOk={handleRename}
      onCancel={handleClose}
      okText={renaming ? "保存中..." : "保存"}
      cancelText="取消"
      confirmLoading={renaming}
      destroyOnHidden
    >
      {error && (
        <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} />
      )}
      <div style={{ marginBottom: 8 }}>文件夹名称：</div>
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        onPressEnter={handleRename}
        placeholder="请输入新名称"
        maxLength={100}
        disabled={renaming}
      />
    </Modal>
  );
}
