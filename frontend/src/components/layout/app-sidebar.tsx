"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";
import { Menu, type MenuProps, Avatar, Button, Dropdown } from "antd";
import { TeamOutlined, SafetyCertificateOutlined, UserOutlined, AuditOutlined, LogoutOutlined, FolderOpenOutlined, WalletOutlined, SettingOutlined, BookOutlined } from "@ant-design/icons";
import type { CurrentUser } from "@/types/auth";
import type { AgentSession } from "@/types/agent";
import { agentApi } from "@/lib/agent-api";
import { onAgentSessionsInvalidated } from "@/lib/agent-session-store";
import { hasPermission, USER_READ, ROLE_READ, FILE_ADMIN_VIEW } from "@/lib/permissions";
import { isSuperAdmin } from "@/lib/roles";
import { copy, PRODUCT_NAME } from "@/lib/copy";
import { api } from "@/lib/api";
import { resolveAvatarUrl } from "@/lib/avatar";
import SessionSidebarList from "@/components/agent/session-sidebar-list";
import DshNavSection from "@/components/agent/dsh-nav-section";
import { dshBridgeStore, dshInstanceStore } from "@/lib/dsh-bridge-store";

interface AppSidebarProps {
  user: CurrentUser;
  onNavigate?: () => void;
}

export default function AppSidebar({ user, onNavigate }: AppSidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const bridge = useSyncExternalStore(dshBridgeStore.subscribe, dshBridgeStore.getSnapshot, dshBridgeStore.getSnapshot);
  const instanceState = useSyncExternalStore(dshInstanceStore.subscribe, dshInstanceStore.getSnapshot, dshInstanceStore.getSnapshot);
  const menuPerms = user.menu_permissions ?? user.permissions;
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [sessionTotal, setSessionTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loadingMore, setLoadingMore] = useState(false);
  const PAGE_SIZE = 20;

  const hasMore = sessions.length < sessionTotal;

  useEffect(() => {
    let active = true;

    function fetchSessions() {
      setPage(1);
      agentApi.listSessions(1, PAGE_SIZE)
        .then((result) => {
          if (active) {
            setSessions(result.items);
            setSessionTotal(result.total);
          }
        })
        .catch(() => {
          if (active) {
            setSessions([]);
            setSessionTotal(0);
          }
        });
    }

    fetchSessions();

    const unsubscribe = onAgentSessionsInvalidated(() => {
      if (active) {
        fetchSessions();
      }
    });

    return () => {
      active = false;
      unsubscribe();
    };
  }, [user.id]);

  async function handleLoadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const nextPage = page + 1;
      const result = await agentApi.listSessions(nextPage, PAGE_SIZE);
      setPage(nextPage);
      setSessions((prev) => {
        const seen = new Set(prev.map((s) => s.id));
        const merged = [...prev, ...result.items.filter((s) => !seen.has(s.id))];
        return merged;
      });
      setSessionTotal(result.total);
    } catch {
      // silent — user can scroll again to retry
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleLogout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {
      // proceed to login regardless
    }
    router.push("/login");
  }

  const activeSessionId = pathname.startsWith("/agent/sessions/")
    ? pathname.split("/agent/sessions/")[1]?.split("/")[0] ?? null
    : null;

  const isLegacyRoute = pathname.startsWith("/agent/legacy") || pathname.startsWith("/agent/sessions/");
  const isDshRoute = pathname === "/agent";

  const selectedKey = pathname.startsWith("/agent/audit")
    ? "/agent/audit"
    : pathname.startsWith("/knowledge")
      ? "/knowledge"
      : pathname.startsWith("/agent/files")
        ? "/agent/files"
        : pathname.startsWith("/account/points")
          ? "/account/points"
          : pathname.startsWith("/users")
            ? "/users"
            : pathname.startsWith("/roles")
              ? "/roles"
              : pathname.startsWith("/files")
                ? "/files"
                : "";

  const systemItems: MenuProps["items"] = [
    {
      key: "/agent/files",
      icon: <FolderOpenOutlined />,
      label: <Link href="/agent/files" onClick={onNavigate}>{copy.navigation.myFiles}</Link>,
    },
    {
      key: "/account/points",
      icon: <WalletOutlined />,
      label: <Link href="/account/points" onClick={onNavigate}>账户</Link>,
    },
    ...(isSuperAdmin(user)
      ? [{
          key: "/agent/audit",
          icon: <AuditOutlined />,
          label: <Link href="/agent/audit" onClick={onNavigate}>{copy.navigation.agentAudit}</Link>,
        }]
      : []),
    ...(hasPermission({ ...user, permissions: menuPerms }, FILE_ADMIN_VIEW)
      ? [{
          key: "/files",
          icon: <FolderOpenOutlined />,
          label: <Link href="/files" onClick={onNavigate}>{copy.navigation.files}</Link>,
        }]
      : []),
    ...(isSuperAdmin(user)
      ? [{
          key: "/knowledge",
          icon: <BookOutlined />,
          label: <Link href="/knowledge" onClick={onNavigate}>{copy.navigation.knowledge}</Link>,
        }]
      : []),
    ...(hasPermission({ ...user, permissions: menuPerms }, USER_READ)
      ? [{
          key: "/users",
          icon: <TeamOutlined />,
          label: <Link href="/users" onClick={onNavigate}>{copy.navigation.users}</Link>,
        }]
      : []),
    ...(hasPermission({ ...user, permissions: menuPerms }, ROLE_READ)
      ? [{
          key: "/roles",
          icon: <SafetyCertificateOutlined />,
          label: <Link href="/roles" onClick={onNavigate}>{copy.navigation.roles}</Link>,
        }]
      : []),
    {
      key: "dsh-settings",
      icon: <SettingOutlined />,
      label: (
        <button
          type="button"
          className="sidebar-settings-link"
          onClick={() => router.push("/agent?settings=1")}
        >
          DSH 设置
        </button>
      ),
    },
  ];

  const dropdownItems = {
    items: [
      {
        key: "logout",
        icon: <LogoutOutlined />,
        label: copy.navigation.logout,
        onClick: handleLogout,
      },
    ],
  };

  const roleBadges = user.roles
    .filter((r) => r.code !== "user")
    .map((r) => r.name);

  return (
    <nav aria-label="主导航" className="app-sidebar">
      <div className="sidebar-decor" aria-hidden="true">
        <span className="sidebar-decor-ring" />
        <span className="sidebar-decor-ring sidebar-decor-ring--dashed" />
        <span className="sidebar-decor-spark" />
        <span className="sidebar-decor-spark sidebar-decor-spark--slow" />
      </div>
      <div className="sidebar-brand">
        <Link href="/agent" className="sidebar-brand-link" aria-label={PRODUCT_NAME}>
          <div className="sidebar-brand-mark">脑</div>
          <div className="sidebar-brand-copy">
            <span className="sidebar-title">{PRODUCT_NAME}</span>
            <span className="sidebar-descriptor">AGENT WORKSPACE</span>
          </div>
        </Link>
      </div>

      <div className={isDshRoute ? "sidebar-new-chat sidebar-new-chat--hidden" : "sidebar-new-chat"}>
        <Link href="/agent" className="new-chat-link" onClick={onNavigate}>
          <span className="new-chat-plus" aria-hidden="true">+</span>
          开始新对话
        </Link>
      </div>

      <div className="sidebar-session-list-wrapper">
        {isLegacyRoute ? (
          <SessionSidebarList sessions={sessions} activeSessionId={activeSessionId} onNavigate={onNavigate} sessionTotal={sessionTotal} hasMore={hasMore} loadingMore={loadingMore} onLoadMore={handleLoadMore} />
        ) : (
          <DshNavSection
            nav={bridge.nav}
            connection={bridge.connection}
            instanceState={instanceState}
            onSend={dshBridgeStore.send}
            isDshRoute={isDshRoute}
            onOpenAgent={(query) => {
              const params = new URLSearchParams();
              if (query?.session) params.set("session", query.session);
              if (query?.newSession) params.set("new", "1");
              const suffix = params.toString();
              router.push(suffix ? `/agent?${suffix}` : "/agent");
              onNavigate?.();
            }}
          />
        )}
      </div>

      <div className="sidebar-footer">
        {systemItems.length > 0 ? (
          <div className="sidebar-management">
            <Menu
              theme="dark"
              mode="inline"
              selectedKeys={selectedKey !== activeSessionId ? [selectedKey] : []}
              items={systemItems}
            />
          </div>
        ) : null}

        <div className="sidebar-account">
          <Avatar
            src={resolveAvatarUrl(user.avatar_url)}
            icon={user.avatar_url ? undefined : <UserOutlined />}
            size="small"
          />
          <div className="sidebar-account-info">
            <span className="sidebar-account-name">{user.display_name}</span>
            <span className="sidebar-account-username">@{user.username}</span>
          </div>
          {roleBadges.length > 0 && (
            <div className="sidebar-account-badges">
              {roleBadges.map((badge) => (
                <span key={badge} className="sidebar-role-badge">{badge}</span>
              ))}
            </div>
          )}
          <Dropdown menu={dropdownItems} trigger={["click"]}>
            <Button type="text" className="sidebar-logout-btn" icon={<LogoutOutlined />} aria-label="退出登录" />
          </Dropdown>
        </div>
      </div>
    </nav>
  );
}
