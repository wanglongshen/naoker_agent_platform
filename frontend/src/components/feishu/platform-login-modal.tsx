"use client";

import { useEffect, useRef, useState } from "react";
import { Modal, Button, Tag, Spin, Input, message, Popconfirm } from "antd";
import { QrcodeOutlined, ReloadOutlined, CloseOutlined, SafetyOutlined, LogoutOutlined } from "@ant-design/icons";
import { api, submitLoginPhone, submitLoginCode } from "@/lib/api";

interface CookieItem {
  domain: string;
  cookie_string: string;
}

const PLATFORMS = [
  { key: "douyin", name: "抖音", domain: "www.douyin.com", iconBg: "#141414", iconChar: "抖" },
  { key: "xiaohongshu", name: "小红书", domain: "www.xiaohongshu.com", iconBg: "#ff2442", iconChar: "红" },
] as const;

const ERROR_TEXT: Record<string, string> = {
  platform_blocked: "平台安全验证拦截，请稍后重试",
  qr_timeout: "二维码加载超时，请点击刷新",
  browser_failed: "浏览器启动失败（无桌面环境请改用手动导入 Cookie）",
  window_closed: "登录窗口已关闭，请重新发起",
  environment_no_display: "当前环境无桌面，请使用手动导入 Cookie 登录",
};

interface PlatformLoginModalProps {
  open: boolean;
  onClose: () => void;
}

export default function PlatformLoginModal({ open, onClose }: PlatformLoginModalProps) {
  const [items, setItems] = useState<CookieItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [scanPlatform, setScanPlatform] = useState<string>("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [scanStatus, setScanStatus] = useState<string>("");
  const [scanError, setScanError] = useState<string>("");
  const [importOpen, setImportOpen] = useState<"douyin" | "xiaohongshu" | null>(null);
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState("");
  const [importing, setImporting] = useState(false);
  const [verifyPhase, setVerifyPhase] = useState<"phone" | "code" | null>(null);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [verifyError, setVerifyError] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionRef = useRef<string | null>(null);

  const loggedDomains = new Set(items.map((i) => i.domain));

  async function load() {
    setLoading(true);
    try {
      const data = await api<{ items: CookieItem[] }>("/api/agent/cookies");
      setItems(data.items);
    } catch {
      message.error("加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (open) load();
  }, [open]);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  useEffect(() => {
    return () => stopPolling();
  }, []);

  async function startScan(platformKey: string) {
    stopPolling();
    setScanning(true);
    setScanPlatform(platformKey);
    setScanStatus("starting");
    setScanError("");
    setVerifyPhase(null);
    setVerifyError("");
    setPhone("");
    setCode("");
    try {
      const data = await api<{ session_id: string; status: string }>(
        "/api/agent/login-sessions",
        { method: "POST", body: JSON.stringify({ platform: platformKey }), csrf: true }
      );
      sessionRef.current = data.session_id;
      setSessionId(data.session_id);
      setScanStatus(data.status);
      pollRef.current = setInterval(() => {
        void pollSession();
      }, 800);
    } catch {
      setScanError("无法启动登录，请稍后重试");
    }
  }

  async function pollSession() {
    const sid = sessionRef.current;
    if (!sid) return;
    try {
      const st = await api<{ status: string; detail: string }>(
        `/api/agent/login-sessions/${sid}/status`
      );
      setScanStatus(st.status);
      if (st.status === "verify_required") {
        setVerifyPhase("phone");
        setScanError("");
      } else if (st.status === "verify_code_required") {
        setVerifyPhase("code");
        setScanError("");
      } else if (st.status === "logged_in") {
        stopPolling();
        message.success("登录成功");
        setScanning(false);
        sessionRef.current = null;
        load();
      } else if (st.status === "timeout") {
        stopPolling();
        setScanError("登录超时，请重新扫码");
      } else if (st.status === "error") {
        stopPolling();
        setScanError(ERROR_TEXT[st.detail] ?? (st.detail || "登录失败，请重试"));
      }
    } catch {
      /* status errors are non-fatal */
    }
  }

  async function handleRefresh() {
    const sid = sessionRef.current;
    if (!sid) return;
    try {
      await api(`/api/agent/login-sessions/${sid}/refresh`, {
        method: "POST",
        csrf: true,
      });
      message.info("已刷新，请重新扫码");
    } catch {
      message.error("刷新失败");
    }
  }

  async function handleCloseScan() {
    const sid = sessionRef.current;
    if (sid) {
      try {
        await api(`/api/agent/login-sessions/${sid}`, { method: "DELETE", csrf: true });
      } catch {
        /* ignore */
      }
    }
    sessionRef.current = null;
    stopPolling();
    setScanning(false);
    setVerifyPhase(null);
    setVerifyError("");
    setPhone("");
    setCode("");
    load();
  }

  function handleRetry() {
    if (scanPlatform) startScan(scanPlatform);
  }

  async function handleLogout(domain: string) {
    try {
      await api(`/api/agent/cookies/${domain}`, { method: "DELETE", csrf: true });
      message.success("已退出登录");
      load();
    } catch {
      message.error("退出失败，请重试");
    }
  }

  async function handleImport() {
    if (!importOpen) return;
    setImporting(true);
    setImportError("");
    try {
      let parsed: unknown;
      try {
        parsed = JSON.parse(importText);
      } catch {
        setImportError("JSON 格式不正确，请粘贴 Cookie-Editor 导出的 JSON");
        return;
      }
      if (!Array.isArray(parsed) || parsed.length === 0) {
        setImportError("请粘贴至少一条 cookie");
        return;
      }
      const data = await api<{ saved: Record<string, number> }>(
        "/api/agent/cookies/import",
        { method: "POST", body: JSON.stringify({ cookies: parsed }), csrf: true }
      );
      const total = Object.values(data.saved).reduce((a, b) => a + b, 0);
      message.success(`已保存 ${total} 条 Cookie`);
      setImportOpen(null);
      setImportText("");
      load();
    } catch (err) {
      setImportError(err instanceof Error ? err.message : "导入失败，请重试");
    } finally {
      setImporting(false);
    }
  }

  async function handleSendCode() {
    const sid = sessionRef.current;
    if (!sid) return;
    if (!/^1\d{10}$/.test(phone)) {
      setVerifyError("请输入正确的手机号");
      return;
    }
    setSubmitting(true);
    setVerifyError("");
    try {
      await submitLoginPhone(sid, phone);
      setVerifyPhase("code");
    } catch (err) {
      setVerifyError(err instanceof Error && err.message ? err.message : "提交失败，请重试");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerifyCode() {
    const sid = sessionRef.current;
    if (!sid) return;
    if (!/^\d{4,6}$/.test(code)) {
      setVerifyError("请输入验证码");
      return;
    }
    setSubmitting(true);
    setVerifyError("");
    try {
      await submitLoginCode(sid, code);
      setVerifyPhase(null);
    } catch (err) {
      setVerifyError(err instanceof Error && err.message ? err.message : "验证失败，请重试");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleResend() {
    const sid = sessionRef.current;
    if (!sid) return;
    setSubmitting(true);
    setVerifyError("");
    try {
      await submitLoginPhone(sid, phone);
    } catch (err) {
      setVerifyError(err instanceof Error && err.message ? err.message : "重新发送失败");
    } finally {
      setSubmitting(false);
    }
  }

  const platform = PLATFORMS.find((p) => p.key === scanPlatform);

  return (
    <Modal title="平台登录" open={open} onCancel={onClose} footer={null} width={560}>
      {!scanning ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ fontSize: 13, color: "#8c8c8c", padding: "2px 4px" }}>
            连接抖音 / 小红书登录态，Agent 抓取内容时自动使用你的账号
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {PLATFORMS.map((p) => {
              const logged = loggedDomains.has(p.domain);
              const importPlatform = PLATFORMS.find((pl) => pl.key === importOpen);
              return (
                <div key={p.key} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      padding: "14px 16px",
                      borderRadius: 10,
                      background: "#fafafa",
                      border: "1px solid #f0f0f0",
                      transition: "box-shadow 0.2s ease",
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLElement).style.boxShadow = "0 2px 8px rgba(0,0,0,0.08)";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLElement).style.boxShadow = "none";
                    }}
                  >
                    <div
                      style={{
                        width: 40,
                        height: 40,
                        borderRadius: "50%",
                        background: p.iconBg,
                        color: "#fff",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 18,
                        flexShrink: 0,
                      }}
                    >
                      {p.iconChar}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: 600 }}>{p.name}</div>
                      <div style={{ fontSize: 12, color: "#8c8c8c", marginTop: 2 }}>
                        {p.domain}
                      </div>
                    </div>
                    <Tag color={logged ? "success" : "default"} style={{ borderRadius: 12, marginRight: 0 }}>
                      {logged ? "已登录" : "未登录"}
                    </Tag>
                    {logged && (
                      <Popconfirm title="退出登录？" description="退出后可扫码登录其他账号" onConfirm={() => handleLogout(p.domain)}>
                        <Button icon={<LogoutOutlined />}>退出登录</Button>
                      </Popconfirm>
                    )}
                    <Button
                      type={logged ? "default" : "primary"}
                      icon={<QrcodeOutlined />}
                      onClick={() => startScan(p.key)}
                    >
                      {logged ? "重新扫码" : "扫码登录"}
                    </Button>
                    <Button onClick={() => { setImportOpen(importOpen === p.key ? null : p.key); setImportError(""); }}>
                      导入 Cookie
                    </Button>
                  </div>
                  {importOpen === p.key && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      <div style={{ fontSize: 12, color: "#8c8c8c" }}>
                        在浏览器登录{importPlatform?.name ?? ""}后，用 Cookie-Editor 扩展导出 JSON 粘贴到这里
                      </div>
                      <Input.TextArea
                        rows={6}
                        value={importText}
                        onChange={(e) => setImportText(e.target.value)}
                        placeholder={'[{"name":"sessionid","value":"...","domain":".douyin.com"}]'}
                      />
                      <div style={{ display: "flex", gap: 8 }}>
                        <Button type="primary" loading={importing} onClick={handleImport}>
                          保存
                        </Button>
                        <Button onClick={() => setImportOpen(null)}>取消</Button>
                      </div>
                      {importError && (
                        <p style={{ margin: 0, fontSize: 12, color: "#cf1322" }}>{importError}</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div
              style={{
                width: 24,
                height: 24,
                borderRadius: "50%",
                background: platform?.iconBg ?? "#141414",
                color: "#fff",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 12,
              }}
            >
              {platform?.iconChar ?? "?"}
            </div>
            <span style={{ fontWeight: 600 }}>{platform?.name ?? ""}</span>
            {scanStatus === "waiting_scan" && (
              <Tag color="processing" style={{ borderRadius: 12 }}>
                <span
                  style={{
                    display: "inline-block",
                    width: 6,
                    height: 6,
                    borderRadius: "50%",
                    background: "#1677ff",
                    marginRight: 6,
                    animation: "plm-blink 1.2s infinite",
                  }}
                />
                等待扫码
              </Tag>
            )}
          </div>

          <p style={{ fontSize: 13, color: "#595959", margin: 0 }}>
            打开{platform?.name ?? ""}App 扫一扫，确认登录
          </p>

          {scanStatus === "waiting_scan" && (
            <div
              style={{
                width: "100%",
                background: "#e6f4ff",
                border: "1px solid #91caff",
                color: "#0958d9",
                borderRadius: 8,
                padding: "8px 12px",
                fontSize: 13,
                textAlign: "center",
              }}
            >
              浏览器窗口已弹出，请在弹出的窗口中扫码或完成登录
              （无桌面环境请改用手动导入 Cookie）
            </div>
          )}

          <div
            style={{
              width: 320,
              padding: 16,
              borderRadius: 12,
              background: "#fff",
              border: "1px solid #f0f0f0",
              boxShadow: "0 4px 16px rgba(0,0,0,0.06)",
              textAlign: "center",
            }}
          >
            {verifyPhase ? (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                  textAlign: "left",
                }}
              >
                {verifyPhase === "phone" ? (
                  <>
                    <Input
                      placeholder="请输入手机号"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      maxLength={11}
                    />
                    <Button type="primary" block loading={submitting} onClick={handleSendCode}>
                      获取验证码
                    </Button>
                  </>
                ) : (
                  <>
                    <p style={{ margin: 0, fontSize: 13, color: "#595959" }}>
                      验证码已发送至 {phone}
                    </p>
                    <Input
                      placeholder="请输入验证码"
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                      maxLength={6}
                    />
                    <Button type="primary" block loading={submitting} onClick={handleVerifyCode}>
                      提交验证
                    </Button>
                    <Button type="link" block disabled={submitting} onClick={handleResend}>
                      重新获取验证码
                    </Button>
                  </>
                )}
                {verifyError && (
                  <p style={{ margin: 0, fontSize: 12, color: "#cf1322", textAlign: "center" }}>
                    {verifyError}
                  </p>
                )}
              </div>
            ) : (
              <div style={{ height: 288, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <Spin size="large" />
              </div>
            )}
          </div>

          {scanError && (
            <div
              style={{
                width: "100%",
                background: "#fff1f0",
                border: "1px solid #ffa39e",
                color: "#cf1322",
                borderRadius: 8,
                padding: "8px 12px",
                fontSize: 13,
                textAlign: "center",
              }}
            >
              {scanError}
            </div>
          )}

          <div style={{ display: "flex", gap: 10 }}>
            {!verifyPhase &&
              (scanError ? (
                <Button type="primary" icon={<ReloadOutlined />} onClick={handleRetry}>
                  重试
                </Button>
              ) : (
                <Button icon={<ReloadOutlined />} onClick={handleRefresh} disabled={!sessionId}>
                  二维码失效？刷新
                </Button>
              ))}
            <Button icon={<CloseOutlined />} onClick={handleCloseScan}>
              取消登录
            </Button>
          </div>

          {!scanError && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#bfbfbf" }}>
              <SafetyOutlined />
              登录态仅用于为你抓取内容，加密保存
            </div>
          )}

          <style>{`
            @keyframes plm-blink {
              0%, 100% { opacity: 1; }
              50% { opacity: 0.25; }
            }
          `}</style>
        </div>
      )}
    </Modal>
  );
}
