"use client";

import { type ReactNode, useEffect, useState } from "react";
import { Layout, Drawer, Button } from "antd";
import { MenuFoldOutlined, MenuUnfoldOutlined } from "@ant-design/icons";
import AppSidebar from "@/components/layout/app-sidebar";
import AppHeader from "@/components/layout/app-header";
import type { CurrentUser } from "@/types/auth";

const STORAGE_KEY = "agent-loop-sidebar";

interface DashboardShellProps {
  currentUser: CurrentUser;
  children: ReactNode;
}

export default function DashboardShell({ currentUser, children }: DashboardShellProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [desktopOpen, setDesktopOpen] = useState(true);

  useEffect(() => {
    setDesktopOpen(window.localStorage.getItem(STORAGE_KEY) !== "closed");
  }, []);

  function toggleDesktopSidebar() {
    setDesktopOpen((open) => {
      window.localStorage.setItem(STORAGE_KEY, open ? "closed" : "open");
      return !open;
    });
  }

  return (
    <Layout className="warm-executive-layout">
      <Layout.Sider
        className={`warm-executive-sider${desktopOpen ? "" : " sider-collapsed"}`}
        width={240}
        breakpoint="md"
        collapsedWidth={0}
        trigger={null}
      >
        <div className="sider-inner">
          <Button
            type="text"
            className="sidebar-collapse-btn mobile-hide"
            icon={<MenuFoldOutlined />}
            onClick={toggleDesktopSidebar}
            aria-label="收起侧边栏"
          />
          <AppSidebar user={currentUser} />
        </div>
      </Layout.Sider>
      <Layout>
        <AppHeader user={currentUser} onMenuToggle={() => setDrawerOpen(true)} />
        {!desktopOpen ? (
          <Button
            type="text"
            className="sidebar-restore-btn"
            icon={<MenuUnfoldOutlined />}
            onClick={toggleDesktopSidebar}
            aria-label="展开侧边栏"
          />
        ) : null}
        <Layout.Content className="warm-executive-content">{children}</Layout.Content>
      </Layout>
      <Drawer
        placement="left"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        size="large"
        styles={{ body: { padding: 0 } }}
      >
        <AppSidebar user={currentUser} onNavigate={() => setDrawerOpen(false)} />
      </Drawer>
    </Layout>
  );
}
