"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Alert } from "antd";
import { fetchCurrentUser } from "@/lib/auth";
import { isSuperAdmin } from "@/lib/roles";
import { ragApi, type RagLibrary } from "@/lib/rag-api";
import PageHeader from "@/components/layout/page-header";
import { EmptyState, PageError, PageLoading } from "@/components/ui/view-states";
import LibraryDetailNav from "@/components/knowledge/library-detail-nav";
import DatasetTable from "@/components/knowledge/dataset-table";
import SearchTestPanel from "@/components/knowledge/search-test-panel";
import ConfigPanel from "@/components/knowledge/config-panel";
import type { CurrentUser } from "@/types/auth";

const TAB_KEYS = ["datasets", "search", "config"];

function normalizeTab(value: string | null): string {
  return value && TAB_KEYS.includes(value) ? value : "datasets";
}

function LibraryDetailView() {
  const router = useRouter();
  const params = useParams<{ libraryId: string }>();
  const searchParams = useSearchParams();
  const libraryId = params?.libraryId ?? "";
  const activeTab = normalizeTab(searchParams.get("tab"));

  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checking, setChecking] = useState(true);
  const [library, setLibrary] = useState<RagLibrary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchCurrentUser()
      .then((u) => {
        if (!u) {
          router.push("/login");
          return;
        }
        setUser(u);
      })
      .catch(() => router.push("/login"))
      .finally(() => setChecking(false));
  }, [router]);

  const loadLibrary = useCallback(async () => {
    if (!libraryId) return;
    setLoading(true);
    try {
      const libraries = await ragApi.listLibraries();
      setLibrary(libraries.find((item) => item.id === libraryId) ?? null);
      setError("");
    } catch {
      setError("加载知识库信息失败");
    } finally {
      setLoading(false);
    }
  }, [libraryId]);

  useEffect(() => {
    if (!user || !isSuperAdmin(user)) return;
    void (async () => {
      await loadLibrary();
    })();
  }, [user, loadLibrary]);

  if (checking) return <PageLoading />;
  if (!user) return null;
  if (!isSuperAdmin(user)) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 40 }}>
        <Alert type="error" title="无权限" description="仅超级管理员可访问知识库管理。" showIcon />
      </div>
    );
  }

  return (
    <div>
      <div className="page-hero">
        <PageHeader
          title={library?.name ?? "知识库详情"}
          description="数据集 / 搜索测试 / 配置 · 仅超级管理员可访问"
        />
      </div>
      <div className="content">
        {loading ? (
          <PageLoading />
        ) : error ? (
          <PageError message={error} onRetry={() => void loadLibrary()} />
        ) : !library ? (
          <EmptyState message="未找到该知识库，可能已被删除。" />
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "232px minmax(0, 1fr)",
              border: "1px solid #efe0d4",
              borderRadius: 14,
              overflow: "hidden",
              background: "#fff",
              boxShadow: "0 8px 24px rgba(90,50,20,.03)",
            }}
          >
            <LibraryDetailNav
              libraryId={library.id}
              libraryName={library.name}
              libraryKind={library.kind}
              activeTab={activeTab}
            />
            <div style={{ minWidth: 0, padding: "18px 20px" }}>
              {activeTab === "datasets" ? (
                <DatasetTable libraryId={library.id} />
              ) : activeTab === "search" ? (
                <SearchTestPanel libraryId={library.id} />
              ) : (
                <ConfigPanel library={library} onSaved={() => void loadLibrary()} />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function LibraryDetailPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <LibraryDetailView />
    </Suspense>
  );
}
