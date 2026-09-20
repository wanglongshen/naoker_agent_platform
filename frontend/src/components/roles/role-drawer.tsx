"use client";

import { useState, useEffect } from "react";
import { Drawer, Form, Input, Select, Button, Space } from "antd";
import { api, ApiError } from "@/lib/api";
import {
  hasPermission,
  ROLE_ASSIGN_PERMISSION,
} from "@/lib/permissions";
import { copy } from "@/lib/copy";
import type { CurrentUser } from "@/types/auth";
import type { RoleListItem, RoleDetail, PermissionSummary } from "@/types/role";
import PermissionTree from "./permission-tree";

interface RoleDrawerProps {
  open: boolean;
  role: RoleListItem | null;
  currentUser: CurrentUser;
  permissions: PermissionSummary[];
  onClose: () => void;
  onSuccess: () => void;
}

export default function RoleDrawer({
  open,
  role,
  currentUser,
  permissions,
  onClose,
  onSuccess,
}: RoleDrawerProps) {
  const isCreate = !role;
  const isSystem = role?.is_system ?? false;
  const canAssignPerm = hasPermission(currentUser, ROLE_ASSIGN_PERMISSION);
  const canEditPerms = canAssignPerm && !isSystem;

  const [code, setCode] = useState("");
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [originalIds, setOriginalIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [form] = Form.useForm();

  useEffect(() => {
    if (!open) return;
    setCode("");
    setName(role?.name ?? "");
    setDescription(role?.description ?? "");
    setError("");

    if (role) {
      api<RoleDetail>(`/api/roles/${role.id}`)
        .then((detail) => {
          const ids = detail.permissions.map((p) => p.id);
          setSelectedIds(ids);
          setOriginalIds(ids);
        })
        .catch(() => {
          setSelectedIds([]);
          setOriginalIds([]);
        });
    } else {
      setSelectedIds([]);
      setOriginalIds([]);
    }
  }, [open, role]);

  const permissionChanges = selectedIds.length - originalIds.length;

  async function handleSubmit() {
    setError("");

    if (!name.trim()) {
      setError("请输入角色名称。");
      return;
    }
    if (isCreate && !code.trim()) {
      setError("请输入角色编码。");
      return;
    }

    const body: Record<string, unknown> = { name: name.trim() };
    if (description) body.description = description;
    else body.description = null;

    if (canEditPerms) {
      body.permission_ids = selectedIds;
    } else if (canAssignPerm && isCreate) {
      body.permission_ids = selectedIds;
    }

    setSaving(true);
    try {
      if (isCreate) {
        body.code = code.trim();
        await api("/api/roles", {
          method: "POST",
          body: JSON.stringify(body),
        });
      } else {
        await api(`/api/roles/${role!.id}`, {
          method: "PUT",
          body: JSON.stringify(body),
        });
      }
      onClose();
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) {
        switch (err.code) {
          case "SYSTEM_ROLE_IMMUTABLE":
            setError("系统角色不可修改。");
            break;
          case "DUPLICATE_VALUE":
            setError(err.message || "角色编码或名称已存在。");
            break;
          default:
            if (err.status === 403) {
              setError("您没有权限执行此操作。");
            } else if (err.status === 404) {
              setError("角色不存在。");
            } else {
              setError(err.message || "操作失败。");
            }
        }
      } else {
        setError("操作失败，请稍后重试。");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer
      title={isCreate ? copy.role.create : copy.role.edit}
      open={open}
      onClose={onClose}
      width={520}
      classNames={{ body: "drawer-body", footer: "drawer-footer" }}
      footer={
        <Space style={{ float: "right" }}>
          <Button onClick={onClose} disabled={saving}>
            {copy.common.cancel}
          </Button>
          <Button type="primary" loading={saving} onClick={handleSubmit}>
            {copy.common.save}
          </Button>
        </Space>
      }
    >
      {error && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      <Form form={form} layout="vertical" noValidate>
        <Form.Item label={copy.role.code}>
          <Input
            id="role-code"
            value={isCreate ? code : role?.code ?? ""}
            onChange={(e) => setCode(e.target.value)}
            disabled={!isCreate || saving}
            required
          />
        </Form.Item>

        <Form.Item label={copy.role.name}>
          <Input
            id="role-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={saving}
            required
          />
        </Form.Item>

        <Form.Item label={copy.role.description}>
          <Input.TextArea
            id="role-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={saving}
            rows={3}
          />
        </Form.Item>

        <Form.Item label={copy.role.permissionAssignment}>
          {isSystem && (
            <p className="system-role-notice">
              {copy.role.systemRoleNotice}
            </p>
          )}
          <PermissionTree
            permissions={permissions}
            selectedIds={selectedIds}
            onChange={setSelectedIds}
            readOnly={!canEditPerms}
          />
          {canEditPerms && permissionChanges !== 0 && (
            <div className="selected-permission-summary">
              <p className="permission-change-summary">
                {permissionChanges > 0
                  ? `+${permissionChanges} 项权限已选中`
                  : `-${-permissionChanges} 项权限已移除`}
              </p>
            </div>
          )}
        </Form.Item>
      </Form>
    </Drawer>
  );
}
