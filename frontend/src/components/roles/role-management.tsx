"use client";

import { useState, useEffect } from "react";
import { Skeleton, Alert, Empty, Pagination, Modal, Button } from "antd";
import { api, ApiError } from "@/lib/api";
import {
  hasPermission,
  ROLE_CREATE,
  ROLE_STATUS,
} from "@/lib/permissions";
import { copy } from "@/lib/copy";
import type { CurrentUser } from "@/types/auth";
import type { RoleListItem, RoleListResponse, PermissionSummary } from "@/types/role";
import PageHeader from "@/components/layout/page-header";
import PageSummary from "@/components/layout/page-summary";
import DataSurface from "@/components/ui/data-surface";
import RoleFilters from "./role-filters";
import RoleTable from "./role-table";
import RoleDrawer from "./role-drawer";
import ConfirmDialog from "@/components/users/confirm-dialog";

interface RoleManagementProps {
  currentUser: CurrentUser;
}

const PAGE_SIZE = 10;

type DialogState =
  | { kind: "none" }
  | { kind: "create" }
  | { kind: "edit"; role: RoleListItem }
  | { kind: "toggleStatus"; role: RoleListItem }
  | { kind: "delete"; role: RoleListItem };

export default function RoleManagement({ currentUser }: RoleManagementProps) {
  const [roles, setRoles] = useState<RoleListItem[]>([]);
  const [permissions, setPermissions] = useState<PermissionSummary[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [mounted, setMounted] = useState(false);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [actionError, setActionError] = useState("");

  async function doFetch(currentPage: number) {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (keyword) params.set("keyword", keyword);
      if (status) params.set("status", status);
      params.set("page", String(currentPage));
      params.set("page_size", String(PAGE_SIZE));

      const [rolesData, perms] = await Promise.all([
        api<RoleListResponse>(`/api/roles?${params.toString()}`),
        api<PermissionSummary[]>("/api/permissions"),
      ]);
      setRoles(rolesData.items);
      setPage(rolesData.page);
      setTotal(rolesData.total);
      setPermissions(perms);
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

  if (loading) {
    return (
      <div>
        <div className="page-hero">
          <PageHeader title={copy.navigation.roles} />
          <div className="page-summary">
            {[0, 1, 2].map((i) => (
              <div key={i} className="summary-card">
                <Skeleton.Input active style={{ width: "100%" }} />
              </div>
            ))}
          </div>
        </div>
        <div className="content">
          <DataSurface>
            <Skeleton active paragraph={{ rows: 5 }} />
          </DataSurface>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <div className="page-hero">
          <PageHeader title={copy.navigation.roles} />
        </div>
        <div className="content">
          <DataSurface>
            <Alert
              type="error"
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

  if (roles.length === 0 && !keyword && !status) {
    return (
      <div>
        <div className="page-hero">
          <PageHeader
            title={copy.navigation.roles}
            actions={
              hasPermission(currentUser, ROLE_CREATE) ? (
                <Button type="primary" onClick={() => setDialog({ kind: "create" })}>{copy.role.create}</Button>
              ) : undefined
            }
          />
        </div>
        <div className="content">
          <DataSurface>
            {actionError && <div className="alert alert-error">{actionError}</div>}
            <Empty description="暂无角色数据">
              <p>暂无角色数据，请新建角色。</p>
              {hasPermission(currentUser, ROLE_CREATE) && (
                <Button type="primary" onClick={() => setDialog({ kind: "create" })} style={{ marginTop: "0.75rem" }}>
                  {copy.role.create}
                </Button>
              )}
            </Empty>
          </DataSurface>
        </div>
        <RoleDrawer
          open={dialog.kind === "create" || dialog.kind === "edit"}
          role={dialog.kind === "edit" ? dialog.role : null}
          currentUser={currentUser}
          permissions={permissions}
          onClose={() => setDialog({ kind: "none" })}
          onSuccess={handleSuccess}
        />
        <ConfirmDialog
          open={dialog.kind === "toggleStatus"}
          title={dialog.kind === "toggleStatus" ? `${dialog.role.status === "active" ? "停用" : "启用"}角色` : ""}
          message={
            dialog.kind === "toggleStatus"
              ? `确认${dialog.role.status === "active" ? "停用" : "启用"}"${dialog.role.name}"？`
              : ""
          }
          confirmLabel={dialog.kind === "toggleStatus" ? (dialog.role.status === "active" ? "停用" : "启用") : ""}
          onConfirm={async () => {
            if (dialog.kind !== "toggleStatus") return;
            try {
              await api(`/api/roles/${dialog.role.id}/status`, {
                method: "PATCH",
                body: JSON.stringify({
                  status: dialog.role.status === "active" ? "disabled" : "active",
                }),
              });
              setDialog({ kind: "none" });
              handleSuccess();
            } catch (err) {
              if (err instanceof ApiError) {
                if (err.code === "SYSTEM_ROLE_IMMUTABLE") {
                  setActionError("系统角色不可修改。");
                } else {
                  setActionError(err.message || "操作失败");
                }
              } else {
                setActionError(err instanceof Error ? err.message : "操作失败");
              }
            }
          }}
          onClose={() => setDialog({ kind: "none" })}
        />
        <DeleteConfirmModal
          open={dialog.kind === "delete"}
          roleId={dialog.kind === "delete" ? dialog.role.id : ""}
          roleName={dialog.kind === "delete" ? dialog.role.name : ""}
          onClose={() => setDialog({ kind: "none" })}
          onSuccess={handleSuccess}
        />
      </div>
    );
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div>
      <div className="page-hero">
        <PageHeader
          title={copy.navigation.roles}
          actions={
            hasPermission(currentUser, ROLE_CREATE) ? (
              <Button type="primary" onClick={() => setDialog({ kind: "create" })}>{copy.role.create}</Button>
            ) : undefined
          }
        />
        <PageSummary items={[
          { label: "角色总数", value: total },
          { label: "当前页角色", value: roles.length },
          { label: "权限总数", value: permissions.length },
        ]} />
      </div>
      <div className="content">
        <DataSurface>
          <div className="data-surface-toolbar">
            <RoleFilters
              keyword={keyword}
              status={status}
              onFilterChange={({ keyword: k, status: s }) => {
                setKeyword(k);
                setStatus(s);
              }}
              onSearch={handleSearch}
            />
          </div>
          {actionError && <div className="alert alert-error">{actionError}</div>}
          <RoleTable
            roles={roles}
            currentUser={currentUser}
            onEdit={(role) => setDialog({ kind: "edit", role })}
            onToggleStatus={(role) => setDialog({ kind: "toggleStatus", role })}
            onDelete={(role) => setDialog({ kind: "delete", role })}
          />
          {totalPages > 1 && (
            <Pagination
              current={page}
              pageSize={PAGE_SIZE}
              total={total}
              onChange={handlePageChange}
              showTotal={(total) => `共 ${total} 条`}
              style={{ marginTop: 16, textAlign: "center" }}
            />
          )}
        </DataSurface>
      </div>

      <RoleDrawer
        open={dialog.kind === "create" || dialog.kind === "edit"}
        role={dialog.kind === "edit" ? dialog.role : null}
        currentUser={currentUser}
        permissions={permissions}
        onClose={() => setDialog({ kind: "none" })}
        onSuccess={handleSuccess}
      />

      <ConfirmDialog
        open={dialog.kind === "toggleStatus"}
        title={dialog.kind === "toggleStatus" ? `${dialog.role.status === "active" ? "停用" : "启用"}角色` : ""}
        message={
          dialog.kind === "toggleStatus"
            ? `确认${dialog.role.status === "active" ? "停用" : "启用"}"${dialog.role.name}"？`
            : ""
        }
        confirmLabel={dialog.kind === "toggleStatus" ? (dialog.role.status === "active" ? "停用" : "启用") : ""}
        onConfirm={async () => {
          if (dialog.kind !== "toggleStatus") return;
          try {
            await api(`/api/roles/${dialog.role.id}/status`, {
              method: "PATCH",
              body: JSON.stringify({
                status: dialog.role.status === "active" ? "disabled" : "active",
              }),
            });
            setDialog({ kind: "none" });
            handleSuccess();
          } catch (err) {
            if (err instanceof ApiError) {
              if (err.code === "SYSTEM_ROLE_IMMUTABLE") {
                setActionError("系统角色不可修改。");
              } else {
                setActionError(err.message || "操作失败");
              }
            } else {
              setActionError(err instanceof Error ? err.message : "操作失败");
            }
          }
        }}
        onClose={() => setDialog({ kind: "none" })}
      />

      <DeleteConfirmModal
        open={dialog.kind === "delete"}
        roleId={dialog.kind === "delete" ? dialog.role.id : ""}
        roleName={dialog.kind === "delete" ? dialog.role.name : ""}
        onClose={() => setDialog({ kind: "none" })}
        onSuccess={handleSuccess}
      />
    </div>
  );
}

function DeleteConfirmModal({
  open,
  roleId,
  roleName,
  onClose,
  onSuccess,
}: {
  open: boolean;
  roleId: string;
  roleName: string;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [userCount, setUserCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) {
      setUserCount(null);
      setError("");
      return;
    }
    setLoading(true);
    api<{ assigned_user_count: number }>(`/api/roles/${roleId}`)
      .then((d) => setUserCount(d.assigned_user_count))
      .catch(() => setUserCount(0))
      .finally(() => setLoading(false));
  }, [open, roleId]);

  const message =
    userCount === null
      ? copy.common.loading
      : userCount > 0
        ? `删除该角色后，将解除 ${userCount} 位用户的角色关联。`
        : `确认删除"${roleName}"？`;

  return (
    <Modal
      title="删除角色"
      open={open}
      onCancel={onClose}
      confirmLoading={loading || deleting}
      onOk={async () => {
        setDeleting(true);
        try {
          await api(`/api/roles/${roleId}`, { method: "DELETE" });
          onClose();
          onSuccess();
        } catch (err) {
          if (err instanceof ApiError) {
            if (err.code === "SYSTEM_ROLE_IMMUTABLE") {
              setError("系统角色不可删除。");
            } else {
              setError(err.message || "操作失败");
            }
          } else {
            setError(err instanceof Error ? err.message : "操作失败");
          }
        } finally {
          setDeleting(false);
        }
      }}
      okText="删除"
      cancelText={copy.common.cancel}
      okButtonProps={{ danger: true, disabled: loading || userCount === null }}
    >
      {error && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}
      <p>{message}</p>
    </Modal>
  );
}
