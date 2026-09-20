"use client";

import { useRef, useState } from "react";
import { Avatar, Button, Form, Input, message, Space } from "antd";
import { resolveAvatarUrl } from "@/lib/avatar";
import {
  DeleteOutlined,
  LockOutlined,
  MailOutlined,
  PhoneOutlined,
  SafetyOutlined,
  SaveOutlined,
  UploadOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { api } from "@/lib/api";
import PageHeader from "@/components/layout/page-header";
import type { CurrentUser } from "@/types/auth";

interface ProfilePageProps {
  currentUser: CurrentUser;
}

export default function ProfilePage({ currentUser }: ProfilePageProps) {
  const [avatarUrl, setAvatarUrl] = useState<string | null>(currentUser.avatar_url ?? null);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    setUploading(true);
    try {
      const data = await api<{ avatar_url: string }>("/api/avatars/me", {
        method: "POST",
        body: formData,
        csrf: true,
      });
      setAvatarUrl(data.avatar_url);
      message.success("头像已更新");
    } catch {
      message.error("头像上传失败");
    } finally {
      setUploading(false);
    }
  }

  async function handleClearAvatar() {
    setUploading(true);
    try {
      const data = await api<{ avatar_url: string | null }>("/api/avatars/me", {
        method: "DELETE",
        csrf: true,
      });
      setAvatarUrl(data.avatar_url);
      message.success("头像已移除");
    } catch {
      message.error("移除头像失败");
    } finally {
      setUploading(false);
    }
  }

  async function handleSaveProfile(values: { display_name: string; email?: string; phone?: string }) {
    setSaving(true);
    try {
      await api("/api/users/me/profile", {
        method: "PUT",
        body: JSON.stringify(values),
        csrf: true,
      });
      message.success("资料已保存");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "保存失败，请检查输入");
    } finally {
      setSaving(false);
    }
  }

  async function handleChangePassword(values: { old_password: string; new_password: string; confirm: string }) {
    if (values.new_password !== values.confirm) {
      message.error("两次输入的新密码不一致");
      return;
    }
    setSaving(true);
    try {
      await api("/api/users/me/password", {
        method: "POST",
        body: JSON.stringify({ old_password: values.old_password, new_password: values.new_password }),
        csrf: true,
      });
      message.success("密码已更新");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "修改密码失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="profile-page-root">
      <div className="profile-page-inner">
        <div className="page-hero">
          <PageHeader title="个人资料" description="管理你的头像、基本信息和密码" />
        </div>
        <section className="profile-hero">
          <span className="profile-decor-circle big" aria-hidden />
          <span className="profile-decor-circle small" aria-hidden />
          <div className="profile-avatar-ring">
            <Avatar size={80} src={resolveAvatarUrl(avatarUrl)} icon={avatarUrl ? undefined : <UserOutlined />} />
          </div>
          <div className="profile-info">
            <div className="profile-name">{currentUser.display_name}</div>
            <div className="profile-account">@{currentUser.username}</div>
            {currentUser.roles.length > 0 && (
              <div className="profile-roles">
                {currentUser.roles.map((role) => (
                  <span key={role.id} className="profile-role-tag">
                    {role.name}
                  </span>
                ))}
              </div>
            )}
            {currentUser.email && (
              <div className="profile-email">
                <MailOutlined />
                <span>{currentUser.email}</span>
              </div>
            )}
          </div>
          <div className="profile-hero-actions">
            <Space>
              <Button icon={<UploadOutlined />} loading={uploading} onClick={() => fileRef.current?.click()}>
                上传头像
              </Button>
              {avatarUrl && (
                <Button icon={<DeleteOutlined />} danger onClick={handleClearAvatar} disabled={uploading}>
                  移除头像
                </Button>
              )}
            </Space>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleUpload(file);
              e.target.value = "";
            }}
          />
        </section>

        <div className="profile-cards">
          <section className="profile-card">
            <div className="profile-card-title">
              <UserOutlined />
              <span>基本信息</span>
            </div>
          <Form
            layout="vertical"
            className="profile-form"
            initialValues={{
              display_name: currentUser.display_name,
              email: currentUser.email ?? undefined,
              phone: currentUser.phone ?? undefined,
            }}
            onFinish={handleSaveProfile}
          >
            <Form.Item name="display_name" label="姓名" rules={[{ required: true, message: "请输入姓名" }]}>
              <Input prefix={<UserOutlined />} />
            </Form.Item>
            <Form.Item name="email" label="邮箱" rules={[{ type: "email", message: "邮箱格式不正确" }]}>
              <Input prefix={<MailOutlined />} />
            </Form.Item>
            <Form.Item name="phone" label="手机号">
              <Input prefix={<PhoneOutlined />} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={saving} icon={<SaveOutlined />}>
              保存
            </Button>
          </Form>
        </section>

        <section className="profile-card">
          <div className="profile-card-title">
            <LockOutlined />
            <span>安全设置</span>
          </div>
          <Form layout="vertical" className="profile-form" onFinish={handleChangePassword}>
            <Form.Item name="old_password" label="旧密码" rules={[{ required: true, message: "请输入旧密码" }]}>
              <Input.Password prefix={<LockOutlined />} />
            </Form.Item>
            <Form.Item name="new_password" label="新密码" rules={[{ required: true, message: "请输入新密码" }]}>
              <Input.Password prefix={<LockOutlined />} />
            </Form.Item>
            <Form.Item name="confirm" label="确认新密码" rules={[{ required: true, message: "请确认新密码" }]}>
              <Input.Password prefix={<LockOutlined />} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={saving} icon={<SafetyOutlined />}>
              修改密码
            </Button>
            <div className="profile-hint" style={{ marginTop: 12 }}>
              新密码需至少 8 位，且同时包含字母和数字
            </div>
          </Form>
        </section>
      </div>
      </div>
    </div>
  );
}
