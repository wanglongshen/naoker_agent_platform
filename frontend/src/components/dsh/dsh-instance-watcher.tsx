"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";
import { dshInstanceStore, type DshInstanceStatus } from "@/lib/dsh-bridge-store";

const POLL_INTERVAL_MS = 5000;

/**
 * 全局 DSH 实例状态轮询（挂在根布局，跨页面常驻）。
 *
 * 侧栏的会话区在所有页面都要显示，状态不能只在 /agent 页里更新；
 * 这里只负责查询与发布，自动拉起实例仍由 /agent 的工作区负责。
 */
export default function DshInstanceWatcher() {
  const pathname = usePathname();
  const enabled = !pathname.startsWith("/login");

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function poll() {
      try {
        const status = await api<DshInstanceStatus>("/api/dsh/instances/me");
        if (!cancelled) dshInstanceStore.publishStatus(status);
      } catch {
        // 未登录或网络异常：保留上一次状态
      }
    }

    void poll();
    const timer = setInterval(() => {
      void poll();
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled]);

  return null;
}
