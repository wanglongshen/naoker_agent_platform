import type { Metadata } from "next";
import "antd/dist/reset.css";
import AntDesignProvider from "@/components/ui/ant-design-provider";
import DshInstanceWatcher from "@/components/dsh/dsh-instance-watcher";
import { PRODUCT_NAME, PRODUCT_SUBTITLE } from "@/lib/copy";
import "./globals.css";
import "./agent-globals.css";

export const metadata: Metadata = {
  title: PRODUCT_NAME,
  description: PRODUCT_SUBTITLE,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>
        <AntDesignProvider>
          {children}
          <DshInstanceWatcher />
        </AntDesignProvider>
      </body>
    </html>
  );
}
