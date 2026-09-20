"use client";

import { useState, useMemo } from "react";
import { Modal, TreeSelect, Alert } from "antd";
import { HomeOutlined, FolderOutlined } from "@ant-design/icons";
import { api, ApiError } from "@/lib/api";
import type { FileListItem, FolderNode } from "@/types/file";

interface MoveModalProps {
  open: boolean;
  file: FileListItem | null;
  treeData: FolderNode[];
  currentFolderId: string;
  onClose: () => void;
  onSuccess: () => void;
}

interface TreeNode {
  value: string;
  title: string;
  selectable: boolean;
  children?: TreeNode[];
}

function buildTreeData(nodes: FolderNode[], excludeId?: string): TreeNode[] {
  return nodes
    .filter((n) => n.id !== excludeId)
    .map((node) => ({
      value: node.id,
      title: node.name,
      selectable: true,
      children: node.children
        ? buildTreeData(node.children, excludeId)
        : undefined,
    }));
}

export default function MoveModal({
  open,
  file,
  treeData,
  currentFolderId,
  onClose,
  onSuccess,
}: MoveModalProps) {
  const [targetFolderId, setTargetFolderId] = useState<string>("");
  const [moving, setMoving] = useState(false);
  const [error, setError] = useState("");

  const treeNodes = useMemo(() => {
    const root: TreeNode = {
      value: "",
      title: "全部文件（根目录）",
      selectable: true,
      children: buildTreeData(treeData),
    };
    return [root];
  }, [treeData]);

  function handleClose() {
    setTargetFolderId("");
    setError("");
    setMoving(false);
    onClose();
  }

  async function handleMove() {
    if (!file) return;

    if (targetFolderId === file.folder_id || (targetFolderId === "" && !file.folder_id)) {
      setError("目标文件夹与当前文件夹相同。");
      return;
    }

    setMoving(true);
    setError("");

    try {
      await api(`/api/files/${file.id}/move`, {
        method: "PUT",
        body: JSON.stringify({ folder_id: targetFolderId || null }),
        csrf: true,
      });
      handleClose();
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message || "移动失败，请稍后重试。");
      } else {
        setError("移动失败，请稍后重试。");
      }
    } finally {
      setMoving(false);
    }
  }

  return (
    <Modal
      title={`移动文件: ${file?.original_filename ?? ""}`}
      open={open}
      onOk={handleMove}
      onCancel={handleClose}
      okText={moving ? "移动中..." : "确认移动"}
      cancelText="取消"
      confirmLoading={moving}
      destroyOnHidden
    >
      {error && (
        <Alert type="error" title={error} showIcon style={{ marginBottom: 16 }} />
      )}
      <div style={{ marginBottom: 8 }}>选择目标文件夹：</div>
      <TreeSelect
        style={{ width: "100%" }}
        value={targetFolderId}
        treeData={treeNodes}
        onChange={(v) => setTargetFolderId(v)}
        placeholder="请选择目标文件夹"
        treeDefaultExpandAll
        allowClear
        showSearch
        filterTreeNode={(input, treeNode) =>
          (treeNode.title as string).toLowerCase().includes(input.toLowerCase())
        }
      />
    </Modal>
  );
}
