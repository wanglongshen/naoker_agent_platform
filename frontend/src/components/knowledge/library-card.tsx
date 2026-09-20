"use client";

import { useState } from "react";
import { Button, Dropdown, Modal, Tag, message } from "antd";
import type { MenuProps } from "antd";
import { MoreOutlined } from "@ant-design/icons";
import { ApiError } from "@/lib/api";
import { ragApi, type RagLibrary } from "@/lib/rag-api";
import NewLibraryModal from "./new-library-modal";

const KIND_LABELS: Record<string, string> = {
  industry: "行业",
  rules: "规则",
  custom: "自定义",
};

const VISIBILITY_LABELS: Record<string, string> = {
  admins_only: "仅管理员",
  all_members: "全员可见",
};

interface LibraryCardProps {
  library: RagLibrary;
  onOpen: () => void;
  onChanged: () => void;
}

export default function LibraryCard({ library, onOpen, onChanged }: LibraryCardProps) {
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [forceOpen, setForceOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [toggling, setToggling] = useState(false);

  const kindLabel = KIND_LABELS[library.kind] ?? library.kind;
  const visibilityLabel = VISIBILITY_LABELS[library.visibility] ?? library.visibility;

  async function handleToggleRetrieval() {
    setToggling(true);
    try {
      await ragApi.updateLibrary(library.id, { retrieval_enabled: !library.retrieval_enabled });
      message.success(library.retrieval_enabled ? "已停用检索" : "已启用检索");
      onChanged();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "操作失败，请稍后重试");
    } finally {
      setToggling(false);
    }
  }

  async function handleDelete(force: boolean) {
    setDeleting(true);
    try {
      await ragApi.deleteLibrary(library.id, force);
      setDeleteOpen(false);
      setForceOpen(false);
      message.success("知识库已删除");
      onChanged();
    } catch (err) {
      if (!force && err instanceof ApiError && err.code === "LIBRARY_NOT_EMPTY") {
        setDeleteOpen(false);
        setForceOpen(true);
      } else {
        message.error(err instanceof Error ? err.message : "删除失败，请稍后重试");
      }
    } finally {
      setDeleting(false);
    }
  }

  const menuItems: MenuProps["items"] = [
    { key: "rename", label: "重命名" },
    { key: "retrieval", label: library.retrieval_enabled ? "停用检索" : "启用检索", disabled: toggling },
    { type: "divider" },
    { key: "delete", label: "删除", danger: true },
  ];

  return (
    <>
      <div
        onClick={onOpen}
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          padding: "18px 20px",
          border: "1px solid #efe0d1",
          borderRadius: 14,
          background: "#fff",
          boxShadow: "0 6px 20px rgba(90,50,20,.04)",
          cursor: "pointer",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onOpen();
            }}
            style={{
              border: "none",
              background: "transparent",
              padding: 0,
              fontSize: 15,
              fontWeight: 700,
              color: "#2b2521",
              cursor: "pointer",
              textAlign: "left",
            }}
          >
            {library.name}
          </button>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: menuItems,
              onClick: ({ key }) => {
                if (key === "rename") setEditOpen(true);
                if (key === "retrieval") void handleToggleRetrieval();
                if (key === "delete") setDeleteOpen(true);
              },
            }}
          >
            <Button
              type="text"
              size="small"
              className="action-trigger"
              icon={<MoreOutlined />}
              aria-label="更多操作"
              onClick={(event) => event.stopPropagation()}
            />
          </Dropdown>
        </div>

        <div
          style={{
            fontSize: 12,
            color: "#8e7f76",
            minHeight: 34,
            overflow: "hidden",
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
          }}
        >
          {library.description || "暂无介绍"}
        </div>

        <div style={{ fontSize: 13, fontWeight: 600, color: "#2b2521" }}>
          {library.stats.doc_count} 篇 · {library.stats.chunk_count.toLocaleString("zh-CN")} 块
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          <Tag color="blue">{kindLabel}</Tag>
          <Tag>{visibilityLabel}</Tag>
          <Tag color={library.retrieval_enabled ? "green" : "default"}>
            {library.retrieval_enabled ? "检索已启用" : "检索已停用"}
          </Tag>
        </div>
      </div>

      <NewLibraryModal open={editOpen} library={library} onClose={() => setEditOpen(false)} onSaved={onChanged} />

      <Modal
        title="删除知识库"
        open={deleteOpen}
        onCancel={() => setDeleteOpen(false)}
        onOk={() => void handleDelete(false)}
        okText="删除"
        cancelText="取消"
        okButtonProps={{ danger: true, autoInsertSpace: false }}
        confirmLoading={deleting}
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
        confirmLoading={deleting}
        destroyOnHidden
      >
        <p>
          该知识库仍有 {library.stats.doc_count} 篇文档。请先清空文档，或选择「强制删除」一并删除全部文档与向量。
        </p>
      </Modal>
    </>
  );
}
