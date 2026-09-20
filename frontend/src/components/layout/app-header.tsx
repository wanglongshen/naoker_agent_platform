"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Avatar, Button, Dropdown } from "antd";
import {
  CheckOutlined,
  LinkOutlined,
  LogoutOutlined,
  MenuOutlined,
  QrcodeOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { api } from "@/lib/api";
import { resolveAvatarUrl } from "@/lib/avatar";
import { copy, PRODUCT_NAME } from "@/lib/copy";
import type { CurrentUser } from "@/types/auth";
import FeishuConnectModal, { useFeishuConnection } from "@/components/feishu/feishu-connect";
import PlatformLoginModal from "@/components/feishu/platform-login-modal";

interface AppHeaderProps {
  user: CurrentUser;
  onMenuToggle?: () => void;
}

export default function AppHeader({ user, onMenuToggle }: AppHeaderProps) {
  const router = useRouter();
  const { connected, refresh } = useFeishuConnection();
  const [feishuOpen, setFeishuOpen] = useState(false);
  const [cookieModalOpen, setCookieModalOpen] = useState(false);

  async function handleLogout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {
      // proceed to login regardless
    }
    router.push("/login");
  }

  return (
    <header className="app-header">
      <div className="header-context">
        <Button
          type="text"
          icon={<MenuOutlined />}
          onClick={onMenuToggle}
          aria-label="Open navigation"
          className="mobile-only"
        />
        <span className="top-bar-logo" aria-hidden="true">脑</span>
        <span className="header-product-name">{PRODUCT_NAME}</span>
      </div>
      <div className="header-account">
        <Dropdown
          menu={{
            items: [
              {
                key: "feishu",
                icon: connected ? <CheckOutlined /> : <LinkOutlined />,
                label: connected ? "飞书已连接" : "连接飞书",
                onClick: () => setFeishuOpen(true),
              },
              {
                key: "platform-login",
                icon: <QrcodeOutlined />,
                label: "平台登录",
                onClick: () => setCookieModalOpen(true),
              },
              { type: "divider" },
              {
                key: "profile",
                icon: <UserOutlined />,
                label: "个人资料",
                onClick: () => router.push("/settings/profile"),
              },
              {
                key: "logout",
                icon: <LogoutOutlined />,
                label: copy.navigation.logout,
                onClick: handleLogout,
              },
            ],
          }}
          trigger={["click"]}
        >
          <button
            type="button"
            className="top-bar-user-btn"
            aria-label={`${user.display_name} 账户菜单`}
          >
            <Avatar
              size={28}
              src={resolveAvatarUrl(user.avatar_url)}
              icon={user.avatar_url ? undefined : <UserOutlined />}
              className="header-avatar"
            >
              {user.display_name?.[0]}
            </Avatar>
            <span className="header-user-name">{user.display_name}</span>
          </button>
        </Dropdown>
      </div>
      <FeishuConnectModal
        open={feishuOpen}
        onClose={() => setFeishuOpen(false)}
        connected={connected}
        onConnectedChange={() => {
          void refresh();
        }}
      />
      <PlatformLoginModal open={cookieModalOpen} onClose={() => setCookieModalOpen(false)} />
    </header>
  );
}
