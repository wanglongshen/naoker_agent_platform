"use client";

import { useState, useEffect, useRef } from "react";
import { api, ApiError } from "@/lib/api";
import { hasPermission, USER_ASSIGN_ROLE } from "@/lib/permissions";
import { copy } from "@/lib/copy";
import { resolveAvatarUrl } from "@/lib/avatar";
import type { CurrentUser } from "@/types/auth";
import type { RoleReference } from "@/types/role";
import type { UserListItem } from "@/types/user";
import { Drawer, Form, Input, Select, Button, Avatar, Space, message } from "antd";
import { UserOutlined } from "@ant-design/icons";

interface UserDrawerProps {
  open: boolean;
  user: UserListItem | null;
  currentUser: CurrentUser;
  assignableRoles?: RoleReference[];
  onClose: () => void;
  onSuccess: () => void;
}

const PASSWORD_RULE = /^(?=.*[a-zA-Z])(?=.*\d).{8,}$/;

function validatePassword(_: unknown, value: string): Promise<void> {
  if (!value) return Promise.reject(new Error("请输入密码。"));
  if (value.length < 8) {
    return Promise.reject(new Error("密码长度至少为 8 位，且需包含字母和数字。"));
  }
  if (!PASSWORD_RULE.test(value)) {
    return Promise.reject(new Error("密码必须包含至少一个字母和一个数字。"));
  }
  return Promise.resolve();
}

export default function UserDrawer({
  open,
  user,
  currentUser,
  assignableRoles,
  onClose,
  onSuccess,
}: UserDrawerProps) {
  const isCreate = !user;
  const canAssignRoles =
    hasPermission(currentUser, USER_ASSIGN_ROLE) &&
    assignableRoles &&
    assignableRoles.length > 0;

  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [avatarUrl, setAvatarUrl] = useState<string | null>(user?.avatar_url ?? null);
  const [prevUser, setPrevUser] = useState<UserListItem | null>(user);
  const fileRef = useRef<HTMLInputElement>(null);

  if (user !== prevUser) {
    setPrevUser(user);
    setAvatarUrl(user?.avatar_url ?? null);
  }

  useEffect(() => {
    if (open) {
      form.setFieldsValue({
        username: "",
        password: "",
        display_name: user?.display_name ?? "",
        email: user?.email ?? "",
        phone: user?.phone ?? "",
        status: "active",
        role_ids: user?.roles ? user.roles.map((role) => role.id) : [],
      });
      setError("");
    }
  }, [open, user, form]);

  const title = isCreate ? copy.user.create : copy.user.edit;

  async function handleDrawerUpload(file: File) {
    if (!user) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const data = await api<{ avatar_url: string }>(`/api/avatars/${user.id}`, {
        method: "POST",
        body: formData,
        csrf: true,
      });
      setAvatarUrl(data.avatar_url);
      message.success("头像已更新");
    } catch {
      message.error("头像上传失败");
    }
  }

  async function handleDrawerClearAvatar() {
    if (!user) return;
    try {
      const data = await api<{ avatar_url: string | null }>(`/api/avatars/${user.id}`, {
        method: "DELETE",
        csrf: true,
      });
      setAvatarUrl(data.avatar_url);
      message.success("头像已移除");
    } catch {
      message.error("移除头像失败");
    }
  }

  async function handleFinish(values: Record<string, unknown>) {
    setError("");

    if (isCreate) {
      if (!(values.username as string)?.trim()) {
        setError("请输入用户名。");
        return;
      }
    }
    if (!(values.display_name as string)?.trim()) {
      setError("请输入姓名。");
      return;
    }

    const body: Record<string, unknown> = {};
    if (isCreate) {
      body.username = (values.username as string).trim();
      body.status = values.status;
      body.password = values.password;
    }
    body.display_name = (values.display_name as string).trim();
    if (values.email) body.email = values.email;
    else body.email = null;
    if (values.phone) body.phone = values.phone;
    else body.phone = null;
    if (canAssignRoles) body.role_ids = values.role_ids;

    setSaving(true);
    try {
      await api(isCreate ? "/api/users" : `/api/users/${user!.id}`, {
        method: isCreate ? "POST" : "PUT",
        body: JSON.stringify(body),
      });
      onClose();
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) {
        switch (err.status) {
          case 400:
            setError(err.message || "输入有误。");
            break;
          case 403:
            setError("您没有权限执行此操作。");
            break;
          case 404:
            setError("用户不存在。");
            break;
          case 409:
            setError("用户名、邮箱或手机号已存在。");
            break;
          case 422:
            setError(err.message || "输入有误，请检查填写内容。");
            break;
          default:
            setError(err.message || "操作失败。");
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
      title={title}
      open={open}
      onClose={onClose}
      width={560}
      placement="right"
      destroyOnHidden
      styles={{ body: { paddingBottom: 88 } }}
    >
      {error && (
        <div style={{ marginBottom: 16 }}>
          <div className="ant-alert ant-alert-error" role="alert">
            <span className="ant-alert-message">{error}</span>
          </div>
        </div>
      )}
      {user && (
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
          <Avatar size={48} src={resolveAvatarUrl(avatarUrl)} icon={avatarUrl ? undefined : <UserOutlined />} />
          <Space>
            <Button size="small" onClick={() => fileRef.current?.click()}>上传头像</Button>
            {avatarUrl && (
              <Button size="small" danger onClick={handleDrawerClearAvatar}>移除头像</Button>
            )}
          </Space>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleDrawerUpload(file);
              e.target.value = "";
            }}
          />
        </div>
      )}
      <Form form={form} layout="vertical" onFinish={handleFinish} noValidate>
        {isCreate && (
          <>
            <Form.Item
              name="username"
              label={copy.user.username}
              rules={[{ required: true, message: "请输入用户名。" }]}
            >
              <Input disabled={saving} />
            </Form.Item>
            <Form.Item
              name="password"
              label="初始密码"
              rules={[{ required: true }, { validator: validatePassword }]}
            >
              <Input.Password disabled={saving} />
            </Form.Item>
          </>
        )}

        <Form.Item
          name="display_name"
          label={copy.user.displayName}
          rules={[{ required: true, message: "请输入姓名。" }]}
        >
          <Input disabled={saving} />
        </Form.Item>

        <Form.Item name="email" label={copy.user.email}>
          <Input type="email" disabled={saving} />
        </Form.Item>

        <Form.Item name="phone" label={copy.user.phone}>
          <Input disabled={saving} />
        </Form.Item>

        {isCreate && (
          <Form.Item name="status" label={copy.user.status}>
            <Select disabled={saving}>
              <Select.Option value="active">{copy.status.active}</Select.Option>
              <Select.Option value="disabled">{copy.status.disabled}</Select.Option>
            </Select>
          </Form.Item>
        )}

        {canAssignRoles && (
          <Form.Item name="role_ids" label={copy.user.roles}>
            <Select mode="multiple" disabled={saving}>
              {assignableRoles!.map((role) => (
                <Select.Option key={role.id} value={role.id}>
                  {role.name}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
        )}
      </Form>
      <div className="drawer-footer" style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <Button onClick={onClose} disabled={saving}>
          {copy.common.cancel}
        </Button>
        <Button type="primary" onClick={() => form.submit()} disabled={saving}>
          {saving ? "保存中..." : copy.common.save}
        </Button>
      </div>
    </Drawer>
  );
}
