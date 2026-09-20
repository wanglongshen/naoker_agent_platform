"use client";

import type { ReactNode } from "react";
import { App, ConfigProvider, theme } from "antd";

export default function AntDesignProvider({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#D96313",
          colorPrimaryHover: "#B94F0C",
          colorBgLayout: "#FAF7F3",
          colorBgContainer: "#FFFFFF",
          colorText: "#2B2521",
          colorTextSecondary: "#71645C",
          colorBorder: "#E6DDD6",
          borderRadius: 10,
          fontFamily: '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif',
        },
        components: {
          Button: { colorPrimary: "#D96313", primaryColor: "#FFFFFF", primaryShadow: "0 4px 10px rgba(217,99,19,.20)" },
          Layout: { bodyBg: "#FAF7F3", siderBg: "transparent", headerBg: "rgba(255,255,255,0.90)", headerHeight: 56 },
          Menu: { darkItemBg: "transparent", darkItemSelectedBg: "rgba(217,99,19,0.18)", darkItemSelectedColor: "#FFFFFF" },
          Table: { headerBg: "#FFFAF4", headerColor: "#8F786A", cellPaddingBlock: 14, cellPaddingInline: 16 },
          Tag: { borderRadiusSM: 99 },
          Drawer: { colorBgElevated: "#FFF", borderRadiusLG: 14 },
          Modal: { borderRadiusLG: 14 },
          Card: { borderRadiusLG: 14 },
          Pagination: { itemSize: 34, borderRadius: 8 },
          Select: { borderRadius: 8 },
          Input: { borderRadius: 8 },
        },
      }}
    >
      <App>{children}</App>
    </ConfigProvider>
  );
}
