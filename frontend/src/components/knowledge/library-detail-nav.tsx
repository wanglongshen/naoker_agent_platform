"use client";

import { useRouter } from "next/navigation";
import { Tag } from "antd";

const KIND_LABELS: Record<string, string> = {
  industry: "行业",
  rules: "规则",
  custom: "自定义",
};

const TABS = [
  { key: "datasets", label: "数据集" },
  { key: "search", label: "搜索测试" },
  { key: "config", label: "配置" },
];

interface LibraryDetailNavProps {
  libraryId: string;
  libraryName: string;
  libraryKind?: string;
  activeTab: string;
}

export default function LibraryDetailNav({ libraryId, libraryName, libraryKind, activeTab }: LibraryDetailNavProps) {
  const router = useRouter();
  const kindLabel = KIND_LABELS[libraryKind ?? ""] ?? libraryKind ?? "自定义";

  return (
    <aside
      style={{
        borderRight: "1px solid #efe0d4",
        background: "#fffdfb",
        padding: "16px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 8px 12px" }}>
        <div
          style={{
            width: 34,
            height: 34,
            flexShrink: 0,
            borderRadius: 9,
            background: "#fdf0e5",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 16,
          }}
        >
          📚
        </div>
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontWeight: 700,
              fontSize: 14,
              color: "#2b2521",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {libraryName}
          </div>
          <div style={{ marginTop: 4 }}>
            <Tag color="blue">{kindLabel}</Tag>
          </div>
        </div>
      </div>

      {TABS.map((tab) => {
        const active = tab.key === activeTab;
        return (
          <button
            key={tab.key}
            type="button"
            aria-current={active ? "page" : undefined}
            onClick={() => router.push(`/knowledge/${libraryId}?tab=${tab.key}`)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 9,
              padding: "9px 10px",
              borderRadius: 8,
              border: active ? "1px solid #f4d9c2" : "1px solid transparent",
              background: active ? "#fdf0e5" : "transparent",
              color: active ? "#a03c08" : "#765f52",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              textAlign: "left",
            }}
          >
            {tab.label}
          </button>
        );
      })}

      <div style={{ flex: 1 }} />

      <button
        type="button"
        onClick={() => router.push("/knowledge")}
        style={{
          padding: "9px 10px",
          borderRadius: 8,
          border: "none",
          background: "transparent",
          color: "#8e7f76",
          fontSize: 13,
          fontWeight: 600,
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        ← 全部知识库
      </button>
    </aside>
  );
}
