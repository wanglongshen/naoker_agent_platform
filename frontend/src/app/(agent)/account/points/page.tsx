"use client";

import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Empty, Input, Spin, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ApiError, getMyPoints, getPointsUsage, redeemPoints, type MyPoints, type PointTxn } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/auth";
import { isSuperAdmin } from "@/lib/roles";
import RedeemCodesModal from "@/components/users/redeem-codes-modal";
import { INITIAL_GRANT_POINTS, TOKENS_PER_POINT } from "@/lib/points-config";

const BRAND = "#D96313";
const BRAND_DARK = "#B94F0C";
const INK = "#2A1812";
const MUTED = "#9c8b7d";
const TEXT = "#6b5d50";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN");
}

function typeTag(type: string) {
  if (type === "grant") return <Tag style={{ background: "#FFF0E4", color: BRAND_DARK, border: "none" }}>充值</Tag>;
  if (type === "redeem") return <Tag style={{ background: "#FFF0E4", color: BRAND_DARK, border: "none" }}>兑换</Tag>;
  if (type === "consume") return <Tag style={{ background: "#ffede8", color: "#e5452d", border: "none" }}>消耗</Tag>;
  return <Tag>{type}</Tag>;
}

type RangeKey = 7 | 30;

export default function PointsPage() {
  const [points, setPoints] = useState<MyPoints | null>(null);
  const [usage, setUsage] = useState<{ date: string; tokens: number; points: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [code, setCode] = useState("");
  const [redeeming, setRedeeming] = useState(false);
  const [range, setRange] = useState<RangeKey>(30);
  const [hoveredDate, setHoveredDate] = useState<string | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [codesOpen, setCodesOpen] = useState(false);

  useEffect(() => {
    fetchCurrentUser()
      .then((user) => {
        if (user && isSuperAdmin(user)) setIsAdmin(true);
      })
      .catch(() => {});
  }, []);

  async function loadAll() {
    setLoading(true);
    setError("");
    try {
      const [me, usageData] = await Promise.all([getMyPoints(), getPointsUsage()]);
      setPoints(me);
      setUsage(usageData.days ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAll();
  }, []);

  async function handleRedeem() {
    const trimmed = code.trim();
    if (!trimmed) return;
    setRedeeming(true);
    try {
      const result = await redeemPoints(trimmed);
      message.success(`兑换成功，获得 ${result.points} 积点`);
      setCode("");
      const me = await getMyPoints();
      setPoints(me);
    } catch (err) {
      if (err instanceof ApiError && (err.code === "INVALID_CODE" || err.code === "CODE_REUSED")) {
        message.error("兑换码无效或已被使用");
      } else {
        message.error(err instanceof Error ? err.message : "兑换失败");
      }
    } finally {
      setRedeeming(false);
    }
  }

  const balance = points?.balance ?? 0;
  const totalGranted = points?.total_granted ?? 0;
  const totalConsumed = points?.total_consumed ?? 0;
  const recent: PointTxn[] = points?.recent ?? [];

  const visibleUsage = useMemo(
    () => (range === 7 ? usage.slice(-7) : usage),
    [usage, range]
  );
  const maxTokens = visibleUsage.reduce((max, d) => Math.max(max, d.tokens), 0);

  const monthPrefix = new Date().toISOString().slice(0, 7);
  const monthTokens = usage
    .filter((d) => d.date.startsWith(monthPrefix))
    .reduce((sum, d) => sum + d.tokens, 0);

  const columns: ColumnsType<PointTxn> = [
    {
      title: "时间",
      key: "created_at",
      render: (_, txn) => <span style={{ fontSize: 13, color: MUTED }}>{formatTime(txn.created_at)}</span>,
    },
    {
      title: "类型",
      key: "type",
      width: 80,
      render: (_, txn) => typeTag(txn.type),
    },
    {
      title: "说明",
      key: "ref",
      render: (_, txn) => <span style={{ fontSize: 13, color: TEXT }}>{txn.ref || "—"}</span>,
    },
    {
      title: "数量",
      key: "amount",
      width: 110,
      align: "right",
      render: (_, txn) => (
        <span style={{ fontSize: 13, fontWeight: 600, color: txn.amount >= 0 ? "#00a870" : "#e5452d" }}>
          {txn.amount >= 0 ? `+${txn.amount.toLocaleString()}` : txn.amount.toLocaleString()}
        </span>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700, color: INK }}>我的积点</div>
          <div style={{ color: MUTED, fontSize: 12, marginTop: 3 }}>实时计费 · 按 token 消耗扣减</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Input
            placeholder="输入兑换码"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onPressEnter={() => void handleRedeem()}
            style={{ width: 170 }}
          />
          <Button
            type="primary"
            loading={redeeming}
            disabled={!code.trim()}
            onClick={() => void handleRedeem()}
            style={{ background: BRAND, borderColor: BRAND }}
          >
            兑换
          </Button>
          {isAdmin && (
            <Button onClick={() => setCodesOpen(true)} style={{ borderColor: BRAND, color: BRAND_DARK }}>
              ＋ 生成兑换码
            </Button>
          )}
        </div>
      </div>

      <RedeemCodesModal open={codesOpen} onClose={() => setCodesOpen(false)} />

      {loading ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : error ? (
        <Alert
          type="error"
          showIcon
          message="积点数据加载失败"
          description={error}
          action={
            <Button size="small" onClick={() => void loadAll()}>
              重新加载
            </Button>
          }
        />
      ) : (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 12,
              marginBottom: 14,
            }}
          >
            <div style={{ background: "#fff", border: "1px solid #f0e6dd", borderRadius: 12, padding: 18 }}>
              <div style={{ color: MUTED, fontSize: 12 }}>当前余额</div>
              <div style={{ fontSize: 30, fontWeight: 700, marginTop: 6, color: INK }}>
                {balance.toLocaleString()} <span style={{ fontSize: 13, fontWeight: 400, color: MUTED }}>积点</span>
              </div>
              <div style={{ color: BRAND, fontSize: 12, marginTop: 6 }}>可生成约 {Math.max(0, Math.floor(balance / 3)).toLocaleString()}+ 个方案</div>
            </div>
            <div style={{ background: "#fff", border: "1px solid #f0e6dd", borderRadius: 12, padding: 18 }}>
              <div style={{ color: MUTED, fontSize: 12 }}>累计获得</div>
              <div style={{ fontSize: 30, fontWeight: 700, marginTop: 6, color: INK }}>{totalGranted.toLocaleString()}</div>
              <div style={{ color: MUTED, fontSize: 12, marginTop: 6 }}>充值 + 兑换 + 赠送</div>
            </div>
            <div style={{ background: "#fff", border: "1px solid #f0e6dd", borderRadius: 12, padding: 18 }}>
              <div style={{ color: MUTED, fontSize: 12 }}>累计消耗</div>
              <div style={{ fontSize: 30, fontWeight: 700, marginTop: 6, color: INK }}>{totalConsumed.toLocaleString()}</div>
              <div style={{ color: MUTED, fontSize: 12, marginTop: 6 }}>共 {recent.filter((t) => t.type === "consume").length}+ 次生成</div>
            </div>
            <div
              style={{
                background: `linear-gradient(135deg, ${BRAND}, ${BRAND_DARK})`,
                borderRadius: 12,
                padding: 18,
                boxShadow: "0 6px 16px rgba(217,99,19,.25)",
              }}
            >
              <div style={{ color: "rgba(255,255,255,.88)", fontSize: 12 }}>本月用量</div>
              <div style={{ fontSize: 30, fontWeight: 700, marginTop: 6, color: "#fff" }}>
                {monthTokens >= 10000 ? `${(monthTokens / 10000).toFixed(1)}万` : monthTokens.toLocaleString()}{" "}
                <span style={{ fontSize: 12, fontWeight: 400 }}>token</span>
              </div>
              <div style={{ color: "rgba(255,255,255,.88)", fontSize: 12, marginTop: 6 }}>
                约 {Math.ceil(monthTokens / TOKENS_PER_POINT).toLocaleString()} 积点
              </div>
            </div>
          </div>

          <div style={{ background: "#fff", border: "1px solid #f0e6dd", borderRadius: 12, padding: 18, marginBottom: 14 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <div style={{ fontWeight: 600, color: INK }}>{range === 7 ? "近 7 天用量" : "近 30 天用量"}</div>
              <div style={{ display: "flex", gap: 4 }}>
                {([7, 30] as RangeKey[]).map((r) => (
                  <span
                    key={r}
                    onClick={() => setRange(r)}
                    style={{
                      fontSize: 11,
                      padding: "3px 10px",
                      borderRadius: 5,
                      cursor: "pointer",
                      color: range === r ? "#fff" : MUTED,
                      background: range === r ? BRAND : "#F7F2EE",
                    }}
                  >
                    {r} 天
                  </span>
                ))}
              </div>
            </div>
            {maxTokens === 0 ? (
              <div style={{ width: "100%", textAlign: "center", color: "#bbb", fontSize: 13, padding: "30px 0" }}>
                暂无消耗数据
              </div>
            ) : (
              <>
                <div style={{ position: "relative", paddingTop: 16 }}>
                  <div
                    style={{
                      position: "absolute",
                      top: 16,
                      left: 0,
                      right: 0,
                      borderTop: "1px dashed #e8dcd2",
                      pointerEvents: "none",
                    }}
                  >
                    <span
                      style={{
                        position: "absolute",
                        top: -9,
                        right: 0,
                        fontSize: 10,
                        color: MUTED,
                        background: "#fff",
                        padding: "0 4px",
                      }}
                    >
                      {maxTokens >= 10000 ? `${(maxTokens / 10000).toFixed(1)}万` : maxTokens.toLocaleString()} token
                    </span>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "flex-end",
                      gap: 2,
                      height: 130,
                      borderBottom: "1px solid #f5ede6",
                      position: "relative",
                    }}
                  >
                    {hoveredDate && (
                      <div
                        style={{
                          position: "absolute",
                          bottom: "100%",
                          left: `${
                            ((visibleUsage.findIndex((d) => d.date === hoveredDate) + 0.5) /
                              Math.max(visibleUsage.length, 1)) *
                            100
                          }%`,
                          transform: "translateX(-50%)",
                          background: "#2A1812",
                          color: "#fff",
                          borderRadius: 8,
                          padding: "8px 12px",
                          fontSize: 12,
                          zIndex: 1000,
                          whiteSpace: "nowrap",
                          pointerEvents: "none",
                          boxShadow: "0 4px 14px rgba(42,24,18,.25)",
                        }}
                      >
                        <div style={{ opacity: 0.75, fontSize: 11, marginBottom: 3 }}>{hoveredDate}</div>
                        <div style={{ fontWeight: 700 }}>
                          {(() => {
                            const day = visibleUsage.find((d) => d.date === hoveredDate);
                            const tokens = day?.tokens ?? 0;
                            return `${tokens >= 10000 ? `${(tokens / 10000).toFixed(1)}万` : tokens.toLocaleString()} token`;
                          })()}
                        </div>
                        {(() => {
                          const day = visibleUsage.find((d) => d.date === hoveredDate);
                          return day && day.points !== 0 ? (
                            <div style={{ opacity: 0.75, fontSize: 11, marginTop: 2 }}>
                              消耗 {Math.abs(day.points)} 积点
                            </div>
                          ) : null;
                        })()}
                        <div style={{ position: "absolute", top: "100%", left: "50%", transform: "translateX(-50%)", border: "5px solid transparent", borderTopColor: "#2A1812" }} />
                      </div>
                    )}
                    {visibleUsage.map((d) => {
                      const isToday = d.date === new Date().toISOString().slice(0, 10);
                      const percent = d.tokens > 0 ? Math.max(6, (d.tokens / maxTokens) * 100) : 0;
                      return (
                        <div
                          key={d.date}
                          data-date={d.date}
                          onMouseEnter={() => setHoveredDate(d.date)}
                          onMouseLeave={() => setHoveredDate(null)}
                          style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "flex-end", justifyContent: "center", height: "100%" }}
                        >
                          {d.tokens > 0 ? (
                            <div
                              style={{
                                width: "72%",
                                maxWidth: 26,
                                height: `${percent}%`,
                                minHeight: 6,
                                borderRadius: "3px 3px 0 0",
                                background: isToday
                                  ? `linear-gradient(180deg, ${BRAND_DARK}, ${BRAND})`
                                  : "linear-gradient(180deg, #F4B489, #FFEAD7)",
                                boxShadow: isToday ? "0 2px 8px rgba(217,99,19,.35)" : "none",
                              }}
                            />
                          ) : (
                            <div style={{ width: 1, height: 10, background: "#E8DCD2" }} />
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <div
                    style={{
                      display: "flex",
                      gap: 3,
                      padding: "5px 2px 0",
                      color: MUTED,
                      fontSize: 9,
                      justifyContent: "space-between",
                    }}
                  >
                    {visibleUsage.length <= 10
                      ? visibleUsage.map((d) => (
                          <span key={d.date} style={{ flex: 1, textAlign: "center" }}>
                            {d.date.slice(5)}
                          </span>
                        ))
                      : [
                          visibleUsage[0]?.date.slice(5),
                          visibleUsage[Math.floor(visibleUsage.length / 2)]?.date.slice(5),
                          visibleUsage[visibleUsage.length - 1]?.date.slice(5),
                        ].map((label, i) => (
                          <span key={i} style={{ flex: 1, textAlign: i === 0 ? "left" : i === 2 ? "right" : "center" }}>
                            {label}
                          </span>
                        ))}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 10, fontSize: 11, color: MUTED }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: "linear-gradient(180deg,#F4B489,#FFEAD7)" }} />
                    每日 token 消耗
                  </span>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    <span style={{ width: 10, height: 10, borderRadius: 2, background: `linear-gradient(180deg, ${BRAND_DARK}, ${BRAND})` }} />
                    今日
                  </span>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                    <span style={{ width: 1, height: 10, background: "#E8DCD2" }} />
                    无消耗
                  </span>
                </div>
              </>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 14 }}>
            <div style={{ background: "#fff", border: "1px solid #f0e6dd", borderRadius: 12, padding: 18 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                <div style={{ fontWeight: 600, color: INK }}>收支明细</div>
              </div>
              <Table
                rowKey="id"
                columns={columns}
                dataSource={recent}
                pagination={false}
                size="small"
                locale={{
                  emptyText: <Empty description="暂无流水" />,
                }}
              />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{ background: "#fff", border: "1px solid #f0e6dd", borderRadius: 12, padding: 18 }}>
                <div style={{ fontWeight: 600, color: INK, marginBottom: 10 }}>计费规则</div>
                <div style={{ fontSize: 12, color: TEXT, lineHeight: 2 }}>
                  <div>· 1 积点 = {TOKENS_PER_POINT.toLocaleString()} token</div>
                  <div>· 按方案生成实际消耗扣减</div>
                  <div>· 新用户赠送 {INITIAL_GRANT_POINTS.toLocaleString()} 积点</div>
                  <div style={{ color: MUTED }}>· 余额不足将暂停生成</div>
                </div>
              </div>
              <div style={{ background: "#fff", border: "1px solid #f0e6dd", borderRadius: 12, padding: 18 }}>
                <div style={{ fontWeight: 600, color: INK, marginBottom: 10 }}>充值方式</div>
                <div
                  style={{
                    background: "#F7F2EE",
                    borderRadius: 8,
                    padding: 12,
                    fontSize: 12,
                    color: TEXT,
                    lineHeight: 1.8,
                  }}
                >
                  联系管理员充值或输入兑换码。
                  <span style={{ color: BRAND, cursor: "pointer" }} onClick={() => message.info("请联系管理员获取兑换码")}>
                    获取兑换码 →
                  </span>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
