"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { copy } from "@/lib/copy";
import { Modal, Form, Input } from "antd";

interface PasswordResetDialogProps {
  open: boolean;
  userId: string;
  userName: string;
  onClose: () => void;
  onSuccess: () => void;
}

export default function PasswordResetDialog({
  open,
  userId,
  userName,
  onClose,
  onSuccess,
}: PasswordResetDialogProps) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [form] = Form.useForm();

  async function handleFinish(values: { password: string; confirm: string }) {
    setError("");

    if (values.password.length < 8) {
      setError("密码长度至少为 8 位。");
      return;
    }
    if (!/[a-zA-Z]/.test(values.password) || !/\d/.test(values.password)) {
      setError("密码必须包含至少一个字母和一个数字。");
      return;
    }
    if (values.password !== values.confirm) {
      setError("两次输入的密码不一致。");
      return;
    }

    setSaving(true);
    try {
      await api(`/api/users/${userId}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ password: values.password }),
      });
      form.resetFields();
      onClose();
      onSuccess();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message || "重置密码失败。");
      } else {
        setError("操作失败。");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={copy.user.resetPassword}
      open={open}
      onOk={() => form.submit()}
      onCancel={onClose}
      confirmLoading={saving}
      okText={copy.user.resetPassword}
      cancelText={copy.common.cancel}
      destroyOnHidden
      afterClose={() => {
        form.resetFields();
        setError("");
      }}
    >
      <p>
        为 <strong>{userName}</strong> 设置新密码。
      </p>
      {error && (
        <div className="ant-alert ant-alert-error" role="alert" style={{ marginBottom: 16 }}>
          <span className="ant-alert-message">{error}</span>
        </div>
      )}
      <Form form={form} layout="vertical" onFinish={handleFinish} noValidate>
        <Form.Item
          name="password"
          label="新密码"
          rules={[{ required: true, message: "请输入新密码。" }]}
        >
          <Input.Password disabled={saving} />
        </Form.Item>
        <Form.Item
          name="confirm"
          label="确认密码"
          rules={[{ required: true, message: "请确认密码。" }]}
        >
          <Input.Password disabled={saving} />
        </Form.Item>
      </Form>
    </Modal>
  );
}
