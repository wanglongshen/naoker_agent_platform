"use client";

import { useState, useEffect } from "react";
import { api, adminGrantPoints, adminPointsAll } from "@/lib/api";
import { hasPermission, USER_CREATE } from "@/lib/permissions";
import { copy } from "@/lib/copy";
import type { CurrentUser } from "@/types/auth";
import type { UserListItem, UserListResponse } from "@/types/user";
import PageHeader from "@/components/layout/page-header";
import PageSummary from "@/components/layout/page-summary";
import DataSurface from "@/components/ui/data-surface";
import { Alert, Button, Empty, Input, InputNumber, Modal, Pagination, Skeleton, message } from "antd";
import UserFilters from "./user-filters";
import UserTable from "./user-table";
import UserDrawer from "./user-drawer";
import PasswordResetDialog from "./password-reset-dialog";
import ConfirmDialog from "./confirm-dialog";
import RedeemCodesModal from "./redeem-codes-modal";

interface UserManagementProps {
  currentUser: CurrentUser;
}

const PAGE_SIZE = 10;

type DialogState =
  | { kind: "none" }
  | { kind: "create" }
  | { kind: "edit"; user: UserListItem }
  | { kind: "resetPassword"; user: UserListItem }
  | { kind: "toggleStatus"; user: UserListItem }
  | { kind: "delete"; user: UserListItem };

export default function UserManagement({ currentUser }: UserManagementProps) {
  const [users, setUsers] = useState<UserListItem[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [roleId, setRoleId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [mounted, setMounted] = useState(false);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [actionError, setActionError] = useState("");
  const [balances, setBalances] = useState<Record<string, number>>({});
  const [rechargeUser, setRechargeUser] = useState<UserListItem | null>(null);
  const [rechargePoints, setRechargePoints] = useState<number | null>(null);
  const [rechargeDesc, setRechargeDesc] = useState("");
  const [rechargeSaving, setRechargeSaving] = useState(false);
  const [rechargeError, setRechargeError] = useState("");
  const [codesOpen, setCodesOpen] = useState(false);

  async function loadBalances() {
    try {
      const data = await adminPointsAll();
      const map: Record<string, number> = {};
      for (const u of data.users ?? []) {
        map[u.user_id] = u.balance;
      }
      setBalances(map);
    } catch {
      setBalances({});
    }
  }

  async function doFetch(currentPage: number) {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (keyword) params.set("keyword", keyword);
      if (status) params.set("status", status);
      if (roleId) params.set("role_id", roleId);
      params.set("page", String(currentPage));
      params.set("page_size", String(PAGE_SIZE));

      const data = await api<UserListResponse>(
        `/api/users?${params.toString()}`
      );
      setUsers(data.items);
      setPage(data.page);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.common.requestFailed);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    doFetch(1);
    void loadBalances();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mounted]);

  function handleSearch() {
    doFetch(1);
  }

  function handlePageChange(newPage: number) {
    doFetch(newPage);
  }

  function handleSuccess() {
    setActionError("");
    doFetch(page);
  }

  async function handleRechargeConfirm() {
    if (!rechargeUser || !rechargePoints || rechargePoints <= 0) {
      setRechargeError("请输入积点数量");
      return;
    }
    setRechargeSaving(true);
    setRechargeError("");
    try {
      await adminGrantPoints(rechargeUser.id, rechargePoints, rechargeDesc);
      message.success(`已为 ${rechargeUser.username} 充值 ${rechargePoints} 积点`);
      setRechargeUser(null);
      setRechargePoints(null);
      setRechargeDesc("");
      await loadBalances();
    } catch (err) {
      setRechargeError(err instanceof Error ? err.message : "充值失败");
    } finally {
      setRechargeSaving(false);
    }
  }

  if (loading) {
    return (
      <div>
        <div className="page-hero">
          <PageHeader title={copy.navigation.users} />
          <div className="page-summary">
            {[0, 1, 2].map((i) => (
              <div key={i} className="summary-card">
                <Skeleton.Button active block style={{ height: 48 }} />
              </div>
            ))}
          </div>
        </div>
        <div className="content">
          <DataSurface>
            <Skeleton active paragraph={{ rows: 8 }} />
          </DataSurface>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <div className="page-hero">
          <PageHeader title={copy.navigation.users} />
        </div>
        <div className="content">
          <DataSurface>
            <Alert
              type="error"
              showIcon
              message={error}
              action={
                <Button size="small" onClick={() => doFetch(1)}>
                  {copy.common.retry}
                </Button>
              }
            />
          </DataSurface>
        </div>
      </div>
    );
  }

  if (users.length === 0 && !keyword && !status && !roleId) {
    return (
      <div>
        <div className="page-hero">
          <PageHeader
            title={copy.navigation.users}
            actions={
              hasPermission(currentUser, USER_CREATE) ? (
                <Button type="primary" onClick={() => setDialog({ kind: "create" })}>
                  {copy.user.create}
                </Button>
              ) : undefined
            }
          />
        </div>
        <div className="content">
          <DataSurface>
            {actionError && <Alert type="error" showIcon title={actionError} />}
            <Empty description="暂无用户数据，请新建用户。">
              {hasPermission(currentUser, USER_CREATE) && (
                <Button type="primary" onClick={() => setDialog({ kind: "create" })}>
                  {copy.user.create}
                </Button>
              )}
            </Empty>
          </DataSurface>
        </div>
        <UserDrawer
          open={dialog.kind === "create" || dialog.kind === "edit"}
          user={dialog.kind === "edit" ? dialog.user : null}
          currentUser={currentUser}
          assignableRoles={currentUser.assignable_roles}
          onClose={() => setDialog({ kind: "none" })}
          onSuccess={handleSuccess}
        />
        <PasswordResetDialog
          open={dialog.kind === "resetPassword"}
          userId={dialog.kind === "resetPassword" ? dialog.user.id : ""}
          userName={dialog.kind === "resetPassword" ? dialog.user.username : ""}
          onClose={() => setDialog({ kind: "none" })}
          onSuccess={handleSuccess}
        />
        <ConfirmDialog
          open={dialog.kind === "toggleStatus"}
          title={dialog.kind === "toggleStatus" ? `${dialog.user.status === "active" ? "停用" : "启用"}用户` : ""}
          message={
            dialog.kind === "toggleStatus"
              ? `确认${dialog.user.status === "active" ? "停用" : "启用"}"${dialog.user.username}"？`
              : ""
          }
          confirmLabel={dialog.kind === "toggleStatus" ? (dialog.user.status === "active" ? "停用" : "启用") : ""}
          onConfirm={async () => {
            if (dialog.kind !== "toggleStatus") return;
            try {
              await api(`/api/users/${dialog.user.id}/status`, {
                method: "PATCH",
                body: JSON.stringify({
                  status: dialog.user.status === "active" ? "disabled" : "active",
                }),
              });
              setDialog({ kind: "none" });
              handleSuccess();
            } catch (err) {
              setActionError(err instanceof Error ? err.message : "操作失败");
            }
          }}
          onClose={() => setDialog({ kind: "none" })}
        />
        <ConfirmDialog
          open={dialog.kind === "delete"}
          title="删除用户"
          message={
            dialog.kind === "delete"
              ? `确认删除"${dialog.user.username}"？该操作不可撤销。`
              : ""
          }
          confirmLabel="删除"
          isDestructive
          onConfirm={async () => {
            if (dialog.kind !== "delete") return;
            try {
              await api(`/api/users/${dialog.user.id}`, { method: "DELETE" });
              setDialog({ kind: "none" });
              handleSuccess();
            } catch (err) {
              setActionError(err instanceof Error ? err.message : "操作失败");
            }
          }}
          onClose={() => setDialog({ kind: "none" })}
        />
      </div>
    );
  }

  const filterProps = {
    keyword,
    status,
    roleId,
    assignableRoles: currentUser.assignable_roles,
    onFilterChange: ({ keyword: k, status: s, roleId: r }: { keyword: string; status: string; roleId: string }) => {
      setKeyword(k);
      setStatus(s);
      setRoleId(r);
    },
    onSearch: handleSearch,
  };

  const tableProps = {
    users,
    currentUser,
    balances,
    onEdit: (user: UserListItem) => setDialog({ kind: "edit", user }),
    onToggleStatus: (user: UserListItem) => setDialog({ kind: "toggleStatus", user }),
    onResetPassword: (user: UserListItem) => setDialog({ kind: "resetPassword", user }),
    onDelete: (user: UserListItem) => setDialog({ kind: "delete", user }),
    onRecharge: (user: UserListItem) => {
      setRechargePoints(null);
      setRechargeDesc("");
      setRechargeError("");
      setRechargeUser(user);
    },
  };

  return (
    <div>
      <div className="page-hero">
        <PageHeader
          title={copy.navigation.users}
          actions={
            hasPermission(currentUser, USER_CREATE) ? (
              <Button type="primary" onClick={() => setDialog({ kind: "create" })}>
                {copy.user.create}
              </Button>
            ) : undefined
          }
        />
        <PageSummary items={[
          { label: "组织成员", value: total },
          { label: "当前页成员", value: users.length },
          { label: "筛选结果", value: keyword || status || roleId ? total : total },
        ]} />
      </div>
      <div className="content">
        <DataSurface>
          <div className="data-surface-toolbar">
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <UserFilters {...filterProps} />
              <div style={{ marginLeft: "auto" }}>
                <Button onClick={() => setCodesOpen(true)}>兑换码管理</Button>
              </div>
            </div>
          </div>
          {actionError ? <Alert type="error" showIcon title={actionError} /> : null}
          <UserTable {...tableProps} />
          <Pagination current={page} pageSize={PAGE_SIZE} total={total} onChange={handlePageChange} showTotal={(total) => `共 ${total} 条`} showSizeChanger={false} />
        </DataSurface>
      </div>

      <UserDrawer
        open={dialog.kind === "create" || dialog.kind === "edit"}
        user={dialog.kind === "edit" ? dialog.user : null}
        currentUser={currentUser}
        assignableRoles={currentUser.assignable_roles}
        onClose={() => setDialog({ kind: "none" })}
        onSuccess={handleSuccess}
      />

      <PasswordResetDialog
        open={dialog.kind === "resetPassword"}
        userId={dialog.kind === "resetPassword" ? dialog.user.id : ""}
        userName={dialog.kind === "resetPassword" ? dialog.user.username : ""}
        onClose={() => setDialog({ kind: "none" })}
        onSuccess={handleSuccess}
      />

      <ConfirmDialog
        open={dialog.kind === "toggleStatus"}
        title={dialog.kind === "toggleStatus" ? `${dialog.user.status === "active" ? "停用" : "启用"}用户` : ""}
        message={
          dialog.kind === "toggleStatus"
            ? `确认${dialog.user.status === "active" ? "停用" : "启用"}"${dialog.user.username}"？`
            : ""
        }
        confirmLabel={dialog.kind === "toggleStatus" ? (dialog.user.status === "active" ? "停用" : "启用") : ""}
        onConfirm={async () => {
          if (dialog.kind !== "toggleStatus") return;
          try {
            await api(`/api/users/${dialog.user.id}/status`, {
              method: "PATCH",
              body: JSON.stringify({
                status: dialog.user.status === "active" ? "disabled" : "active",
              }),
            });
            setDialog({ kind: "none" });
            handleSuccess();
          } catch (err) {
            setActionError(err instanceof Error ? err.message : "操作失败");
          }
        }}
        onClose={() => setDialog({ kind: "none" })}
      />

      <ConfirmDialog
        open={dialog.kind === "delete"}
        title="删除用户"
        message={
          dialog.kind === "delete"
            ? `确认删除"${dialog.user.username}"？该操作不可撤销。`
            : ""
        }
        confirmLabel="删除"
        isDestructive
        onConfirm={async () => {
          if (dialog.kind !== "delete") return;
          try {
            await api(`/api/users/${dialog.user.id}`, { method: "DELETE" });
            setDialog({ kind: "none" });
            handleSuccess();
          } catch (err) {
            setActionError(err instanceof Error ? err.message : "操作失败");
          }
        }}
        onClose={() => setDialog({ kind: "none" })}
      />

      <Modal
        title="充值积点"
        open={rechargeUser != null}
        onOk={() => void handleRechargeConfirm()}
        onCancel={() => setRechargeUser(null)}
        okText="确认"
        cancelText={copy.common.cancel}
        confirmLoading={rechargeSaving}
        destroyOnHidden
        afterClose={() => {
          setRechargePoints(null);
          setRechargeDesc("");
          setRechargeError("");
        }}
      >
        <p>
          为 <strong>{rechargeUser?.username}</strong> 充值积点。
        </p>
        {rechargeError && (
          <div className="ant-alert ant-alert-error" role="alert" style={{ marginBottom: 16 }}>
            <span className="ant-alert-message">{rechargeError}</span>
          </div>
        )}
        <div style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 4 }}>积点数量</div>
          <InputNumber
            min={1}
            max={1000000}
            style={{ width: "100%" }}
            value={rechargePoints}
            onChange={(v) => setRechargePoints(v)}
            placeholder="请输入积点数量"
          />
        </div>
        <div>
          <div style={{ marginBottom: 4 }}>说明</div>
          <Input
            value={rechargeDesc}
            onChange={(e) => setRechargeDesc(e.target.value)}
            placeholder="选填，例如：运营补偿"
          />
        </div>
      </Modal>

      <RedeemCodesModal open={codesOpen} onClose={() => setCodesOpen(false)} />
    </div>
  );
}
