"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert } from "antd";
import { fetchCurrentUser } from "@/lib/auth";
import { isSuperAdmin } from "@/lib/roles";
import { copy } from "@/lib/copy";
import PageHeader from "@/components/layout/page-header";
import LibraryGrid from "@/components/knowledge/library-grid";
import { PageLoading } from "@/components/ui/view-states";
import type { CurrentUser } from "@/types/auth";

export default function KnowledgePage() {
  const router = useRouter();
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [checking, setChecking] = useState(true);

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
          title={copy.navigation.knowledge}
          description="按库组织文档、控制启用状态、验证检索效果 · 仅超级管理员可访问"
        />
      </div>
      <div className="content">
        <LibraryGrid />
      </div>
    </div>
  );
}
