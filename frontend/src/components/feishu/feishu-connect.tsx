"use client";

import { useCallback, useEffect, useState } from "react";
import { App, Button, Input, Modal, Popconfirm, Switch, Tag } from "antd";
import { CheckOutlined, LinkOutlined } from "@ant-design/icons";
import { api } from "@/lib/api";
import {
  listFeishuConfigs,
  createFeishuConfig,
  activateFeishuConfig,
  deleteFeishuConfig,
  updateSyncFeishu,
  type FeishuConfigItem,
} from "@/lib/api";
import { fetchCurrentUser } from "@/lib/auth";
import { isSuperAdmin } from "@/lib/roles";

async function fetchFeishuStatus(): Promise<boolean> {
  try {
    const data = await api<{ connected: boolean }>("/api/feishu/status");
    return data.connected;
  } catch {
    return false;
  }
}

export function useFeishuConnection(): { connected: boolean; refresh: () => Promise<void> } {
  const [connected, setConnected] = useState(false);
  const refresh = useCallback(async () => {
    setConnected(await fetchFeishuStatus());
  }, []);
  useEffect(() => {
    void fetchFeishuStatus().then(setConnected);
  }, []);
  return { connected, refresh };
}

interface FeishuConnectModalProps {
  open: boolean;
  onClose: () => void;
  connected: boolean;
  onConnectedChange: (value: boolean) => void;
}

export default function FeishuConnectModal({
  open,
  onClose,
  connected,
  onConnectedChange,
}: FeishuConnectModalProps) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [configs, setConfigs] = useState<FeishuConfigItem[]>([]);
  const [showConfigForm, setShowConfigForm] = useState(false);
  const [cfgName, setCfgName] = useState("");
  const [cfgAppId, setCfgAppId] = useState("");
  const [cfgSecret, setCfgSecret] = useState("");
  const [cfgBusy, setCfgBusy] = useState(false);
  const [cfgError, setCfgError] = useState("");
  const [syncEnabled, setSyncEnabled] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const feishuState = params.get("feishu");
    if (feishuState) {
      if (feishuState === "connected") {
        message.success("飞书连接成功");
      } else if (feishuState.startsWith("error")) {
        message.error("飞书连接失败，请重试");
      }
      const url = new URL(window.location.href);
      url.searchParams.delete("feishu");
      window.history.replaceState(url.toString(), "", url.toString());
    }
    fetchCurrentUser()
      .then((user) => {
        if (user) {
          setSyncEnabled(!!user.sync_feishu_enabled);
          if (isSuperAdmin(user)) {
            setIsAdmin(true);
          }
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    listFeishuConfigs()
      .then((d) => setConfigs(d.configs))
      .catch(() => {});
  }, [isAdmin]);

  async function handleConnect() {
    setLoading(true);
    try {
      const data = await api<{ authorize_url: string }>("/api/feishu/oauth/start");
      window.location.href = data.authorize_url;
    } catch {
      message.error("飞书未配置，请联系管理员");
    } finally {
      setLoading(false);
    }
  }

  async function handleDisconnect() {
    setLoading(true);
    try {
      await api("/api/feishu/connection", { method: "DELETE", csrf: true });
      onConnectedChange(false);
      message.success("已退出飞书");
    } catch {
      message.error("退出失败，请重试");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal
      title={null}
      open={open}
      onCancel={onClose}
      footer={null}
      width={480}
      styles={{ body: { padding: 24 } }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
        <div
          style={{
            width: 44,
            height: 44,
            borderRadius: 12,
            background: "linear-gradient(135deg, #3370ff 0%, #2f54eb 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            fontSize: 22,
            fontWeight: 700,
            flexShrink: 0,
          }}
        >
          飞
        </div>
        <div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>飞书</div>
          <div style={{ fontSize: 13, color: "#8c8c8c" }}>连接飞书账号，方案文档自动同步</div>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div
          style={{
            border: "1px solid #f0f0f0",
            borderRadius: 12,
            padding: 16,
            background: "#fafafa",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>账号登录</span>
            {connected ? (
              <Tag color="success" style={{ marginInlineEnd: 0 }}>已连接</Tag>
            ) : (
              <Tag style={{ marginInlineEnd: 0 }}>未连接</Tag>
            )}
          </div>
          <div style={{ fontSize: 13, color: "#8c8c8c", marginBottom: 12 }}>
            登录后生成的方案文档将创建在你的飞书空间
          </div>
          {connected ? (
            <Popconfirm
              title="退出飞书账号？"
              description="退出后可连接其他飞书账号"
              onConfirm={handleDisconnect}
            >
              <Button icon={<CheckOutlined />} loading={loading}>
                已登录（退出）
              </Button>
            </Popconfirm>
          ) : (
            <Button
              type="primary"
              icon={<LinkOutlined />}
              onClick={handleConnect}
              loading={loading}
              style={{ background: "#3370ff" }}
            >
              登录飞书账号
            </Button>
          )}
        </div>

        <div
          style={{
            border: "1px solid #f0f0f0",
            borderRadius: 12,
            padding: 16,
            background: "#fafafa",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <Switch
              checked={syncEnabled}
              onChange={async (v) => {
                try {
                  await updateSyncFeishu(v);
                  setSyncEnabled(v);
                } catch {
                  message.error("设置失败，请重试");
                }
              }}
            />
            <span style={{ fontSize: 14, fontWeight: 600 }}>方案生成后同步到飞书</span>
          </div>
          <div style={{ fontSize: 13, color: "#8c8c8c", paddingLeft: 46 }}>
            开启后，每次方案生成成功都会自动创建一篇飞书文档
          </div>
        </div>

        {isAdmin && (
          <div
            style={{
              border: "1px solid #f0f0f0",
              borderRadius: 12,
              padding: 16,
              background: "#fafafa",
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>
              填写 API Key（企业飞书应用配置）
            </div>
            <div style={{ fontSize: 13, color: "#8c8c8c", marginBottom: 12 }}>
              配置企业飞书应用的 App ID 与 Secret，员工登录共用此配置
            </div>
            {!showConfigForm ? (
              <Button size="small" onClick={() => setShowConfigForm(true)}>
                添加配置
              </Button>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <Input
                  placeholder="企业名称"
                  value={cfgName}
                  onChange={(e) => setCfgName(e.target.value)}
                />
                <Input
                  placeholder="App ID"
                  value={cfgAppId}
                  onChange={(e) => setCfgAppId(e.target.value)}
                />
                <Input.Password
                  placeholder="App Secret"
                  value={cfgSecret}
                  onChange={(e) => setCfgSecret(e.target.value)}
                />
                {cfgError && <div style={{ color: "#cf1322", fontSize: 12 }}>{cfgError}</div>}
                <div style={{ display: "flex", gap: 8 }}>
                  <Button
                    type="primary"
                    size="small"
                    loading={cfgBusy}
                    onClick={async () => {
                      if (!cfgName.trim() || !cfgAppId.trim() || !cfgSecret.trim()) {
                        setCfgError("请填写完整");
                        return;
                      }
                      setCfgBusy(true);
                      setCfgError("");
                      try {
                        await createFeishuConfig({
                          name: cfgName.trim(),
                          app_id: cfgAppId.trim(),
                          app_secret: cfgSecret.trim(),
                        });
                        setCfgName("");
                        setCfgAppId("");
                        setCfgSecret("");
                        setShowConfigForm(false);
                        const d = await listFeishuConfigs();
                        setConfigs(d.configs);
                      } catch {
                        setCfgError("保存失败，请重试");
                      }
                      setCfgBusy(false);
                    }}
                  >
                    保存
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      setShowConfigForm(false);
                      setCfgError("");
                    }}
                  >
                    取消
                  </Button>
                </div>
              </div>
            )}
            {configs.length > 0 && (
              <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
                {configs.map((c) => (
                  <div
                    key={c.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      fontSize: 13,
                      background: "#fff",
                      border: "1px solid #f0f0f0",
                      borderRadius: 8,
                      padding: "6px 10px",
                    }}
                  >
                    <span>
                      {c.name}（{c.app_id_mask}…）
                    </span>
                    {c.is_default && <Tag color="green">默认</Tag>}
                    <div style={{ flex: 1 }} />
                    <Button
                      size="small"
                      type="text"
                      disabled={c.is_default}
                      onClick={async () => {
                        await activateFeishuConfig(c.id);
                        const d = await listFeishuConfigs();
                        setConfigs(d.configs);
                      }}
                    >
                      设为默认
                    </Button>
                    <Button
                      size="small"
                      type="text"
                      danger
                      onClick={async () => {
                        await deleteFeishuConfig(c.id);
                        const d = await listFeishuConfigs();
                        setConfigs(d.configs);
                      }}
                    >
                      删除
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
