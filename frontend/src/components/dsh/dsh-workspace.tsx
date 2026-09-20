"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import { Alert, Button, Tag } from "antd";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { fetchCurrentUser } from "@/lib/auth";
import { api } from "@/lib/api";
import { useDshBridge } from "@/lib/dsh-bridge";
import { dshBridgeStore, dshInstanceStore, type DshInstanceStatus } from "@/lib/dsh-bridge-store";
import { attachFrame, parkFrame, reloadFrame } from "./dsh-frame-keeper";

const LAST_SESSION_KEY_PREFIX = "dsh:last-session:";

function statusLabel(status: DshInstanceStatus | null): string {
  if (!status) return "状态查询中";
  if (status.state === "running") {
    return `运行中${status.port ? `（端口 ${status.port}）` : ""}`;
  }
  if (status.state === "stopped") return "未运行";
  if (status.state === "starting") return "正在启动…";
  return status.state;
}

function frameUrl(status: DshInstanceStatus | null): string | null {
  if (!status || status.state !== "running" || !status.port) return null;
  return `http://127.0.0.1:${status.port}/`;
}

export default function DshWorkspace() {
  const pathname = usePathname();
  const [userId, setUserId] = useState<string | null>(null);
  const status = useSyncExternalStore(
    dshInstanceStore.subscribe,
    dshInstanceStore.getStatus,
    dshInstanceStore.getStatus,
  );
  const [statusError, setStatusError] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const autoStartRef = useRef(false);
  const prevStateRef = useRef<string | null>(null);
  const lastReloadRef = useRef(0);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const lastSessionRef = useRef<string | null>(null);
  const { nav, connection, searchResults, ready, send } = useDshBridge(iframeRef);

  useEffect(() => {
    dshBridgeStore.setSender(send);
    return () => dshBridgeStore.setSender(null);
  }, [send]);

  useEffect(() => {
    dshBridgeStore.publish({ nav, connection, searchResults, ready });
  }, [nav, connection, searchResults, ready]);

  useEffect(() => {
    let cancelled = false;
    fetchCurrentUser()
      .then((user) => {
        if (!cancelled && user) setUserId(user.id);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const url = frameUrl(status);

  // 单例 iframe：进入 /agent 挂到内容区，离开时移到隐藏容器保活（不重载）。
  useLayoutEffect(() => {
    const container = containerRef.current;
    if (container === null || url === null) return;
    attachFrame(container, url);
    iframeRef.current = container.querySelector("iframe");
    if (reloadToken !== lastReloadRef.current) {
      lastReloadRef.current = reloadToken;
      reloadFrame();
    }
  }, [url, reloadToken]);

  useLayoutEffect(() => () => parkFrame(), []);

  // 实例从死到活（重建/自动拉起）时强制重载旧文档。
  useEffect(() => {
    const prev = prevStateRef.current;
    prevStateRef.current = status?.state ?? null;
    if (url === null) return;
    if (prev === "stopped" || prev === "error") reloadFrame();
  }, [status?.state, url]);

  // 首次进入 /agent 且实例未运行：自动拉起一次。
  useEffect(() => {
    if (status?.state !== "stopped" || autoStartRef.current) return;
    autoStartRef.current = true;
    void startInstance();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.state]);

  // 深链：?session=<id> 选中会话；?new=1 新建会话后清掉参数。路径变化（从别的页面跳回）也会重新执行。
  // 每次 iframe 重新加载（ready 由 false→true）后重置去重标记，保证深链重新武装。
  useEffect(() => {
    if (ready) lastSessionRef.current = null;
  }, [ready]);

  useEffect(() => {
    if (!ready) return;
    const params = new URLSearchParams(window.location.search);
    const target = params.get("session");
    if (target && target !== lastSessionRef.current) {
      lastSessionRef.current = target;
      send({ v: 1, type: "cmd", action: "select-session", payload: { sessionId: target } });
    }
    if (params.get("new") === "1") {
      send({ v: 1, type: "cmd", action: "new-session" });
      const next = new URL(window.location.href);
      next.searchParams.delete("new");
      window.history.replaceState(null, "", next);
    }
    if (params.get("settings") === "1") {
      send({ v: 1, type: "cmd", action: "open-settings" });
      const next = new URL(window.location.href);
      next.searchParams.delete("settings");
      window.history.replaceState(null, "", next);
    }
  }, [ready, pathname, send]);

  // 记忆上次会话：URL 同步 + localStorage（刷新/重开后可恢复同一段对话）。
  const currentSessionId = nav?.currentSessionId;
  useEffect(() => {
    if (!currentSessionId) return;
    lastSessionRef.current = currentSessionId;
    const url = new URL(window.location.href);
    if (url.searchParams.get("session") !== currentSessionId) {
      url.searchParams.set("session", currentSessionId);
      window.history.replaceState(null, "", url);
    }
    if (userId) {
      window.localStorage.setItem(`${LAST_SESSION_KEY_PREFIX}${userId}`, currentSessionId);
    }
  }, [currentSessionId, userId]);

  // 刷新后无 ?session= 时，恢复到上次会话。
  useEffect(() => {
    if (!ready || !userId) return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("session") || params.get("new") === "1") return;
    const remembered = window.localStorage.getItem(`${LAST_SESSION_KEY_PREFIX}${userId}`);
    if (remembered) {
      lastSessionRef.current = remembered;
      send({ v: 1, type: "cmd", action: "select-session", payload: { sessionId: remembered } });
    }
  }, [ready, userId, send]);

  const startInstance = useCallback(async () => {
    setRestarting(true);
    try {
      const next = await api<DshInstanceStatus>("/api/dsh/instances/me/restart", {
        method: "POST",
        csrf: true,
      });
      dshInstanceStore.publishStatus(next);
      setStatusError(null);
    } catch {
      setStatusError("启动 DSH 实例失败");
    } finally {
      setRestarting(false);
    }
  }, []);

  async function handleRestart() {
    setRestarting(true);
    try {
      const next = await api<DshInstanceStatus>("/api/dsh/instances/me/restart", {
        method: "POST",
        csrf: true,
      });
      dshInstanceStore.publishStatus(next);
      setStatusError(null);
      setReloadToken((token) => token + 1);
    } catch {
      setStatusError("重建 DSH 实例失败");
    } finally {
      setRestarting(false);
    }
  }

  return (
    <section className="dsh-workspace" aria-label="DSH 工作区">
      <div className="dsh-workspace-statusbar">
        <span className="dsh-workspace-title">DSH 工作区</span>
        <Tag className="dsh-workspace-status" color={status?.state === "running" ? "green" : "default"}>
          {statusLabel(status)}
        </Tag>
        <span className="dsh-workspace-port">端口 {status?.port ?? "—"}</span>
        {status?.error_hint ? (
          <span className="dsh-workspace-error-hint" title={status.error_hint}>
            {status.error_hint}
          </span>
        ) : null}
        <Button size="small" loading={restarting} onClick={handleRestart}>
          重建
        </Button>
        <Link className="dsh-workspace-legacy-link" href="/agent/legacy">
          打开原版
        </Link>
      </div>
      {statusError ? (
        <Alert type="error" title={statusError} showIcon className="dsh-workspace-alert" />
      ) : null}
      <div className="dsh-workspace-frame-host" ref={containerRef}>
        {userId === null ? (
          <div className="dsh-workspace-loading">加载工作区中…</div>
        ) : url === null ? (
          <div className="dsh-workspace-loading">
            {status?.state === "stopped" ? "实例未运行，正在启动…" : "正在启动 DSH 实例…（首次 5-20 秒）"}
          </div>
        ) : null}
      </div>
    </section>
  );
}
