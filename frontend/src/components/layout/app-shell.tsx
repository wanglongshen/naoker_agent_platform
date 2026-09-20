"use client";

import { type ReactNode, useEffect, useState } from "react";
import { Drawer, Button } from "antd";
import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import AppSidebar from "@/components/layout/app-sidebar";
import type { CurrentUser } from "@/types/auth";

const STORAGE_KEY = "agent-loop-sidebar";

interface AppShellProps {
  currentUser: CurrentUser;
  children: ReactNode;
}

function usePersistentSidebarState(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(true);

  useEffect(() => {
    setCollapsed(window.localStorage.getItem(STORAGE_KEY) === "closed");
  }, []);

  function toggle() {
    setCollapsed((open) => {
      window.localStorage.setItem(STORAGE_KEY, open ? "open" : "closed");
      return !open;
    });
  }

  return [collapsed, toggle];
}

export default function AppShell({ currentUser, children }: AppShellProps) {
  const [collapsed, toggleCollapsed] = usePersistentSidebarState();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="enterprise-shell">
      <aside
        className={`enterprise-sidebar${collapsed ? " sidebar-collapsed" : ""}`}
        aria-hidden={collapsed || undefined}
        {...({ inert: collapsed ? true : undefined } as Record<string, unknown>)}
      >
        <Button
          type="text"
          className="sidebar-collapse-btn mobile-hide"
          icon={<MenuFoldOutlined />}
          onClick={toggleCollapsed}
          aria-label={collapsed ? "展开导航" : "收起导航"}
        />
        <AppSidebar user={currentUser} />
      </aside>
      <div className="enterprise-main-column">
        <Button
          type="text"
          className="sidebar-restore-btn mobile-hide"
          icon={<MenuUnfoldOutlined />}
          onClick={toggleCollapsed}
          aria-label="展开导航"
          style={collapsed ? {} : { display: "none" }}
        />
        <button
          type="button"
          className="mobile-menu-trigger"
          aria-label="Open navigation"
          onClick={() => setMobileOpen(true)}
        >
          <MenuUnfoldOutlined />
        </button>
        <main className="enterprise-main">{children}</main>
      </div>
      <Drawer
        className="enterprise-navigation-drawer"
        placement="left"
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        size="large"
        styles={{ body: { padding: 0, background: "var(--color-sidebar)" } }}
      >
        <AppSidebar user={currentUser} onNavigate={() => setMobileOpen(false)} />
      </Drawer>
    </div>
  );
}
