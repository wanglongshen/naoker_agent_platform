"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Form, Input } from "antd";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { api, ApiError } from "@/lib/api";
import { copy } from "@/lib/copy";

function getCallbackPath(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const params = new URLSearchParams(window.location.search);
    const callback = params.get("callback");
    if (callback && callback.startsWith("/") && !callback.startsWith("//")) {
      return callback;
    }
  } catch {
    // ignore
  }
  return null;
}

export default function LoginForm() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit() {
    setError("");
    if (!username.trim()) {
      setError(copy.auth.usernameRequired);
      return;
    }
    if (!password) {
      setError(copy.auth.passwordRequired);
      return;
    }
    setLoading(true);
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const callback = getCallbackPath();
      if (callback) {
        router.push(callback);
      } else {
        router.push("/agent");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message || copy.auth.invalidCredentials : copy.auth.invalidCredentials);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="login-card-header">
        <h2 className="login-card-title">欢迎登录</h2>
        <p className="login-card-subtitle">组织专属的私有智能助手</p>
      </div>
      <Form layout="vertical" onFinish={handleSubmit} requiredMark={false}>
      {error ? <Alert type="error" showIcon title={error} role="alert" /> : null}
      <Form.Item label={copy.user.username} htmlFor="username">
        <Input
          id="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          disabled={loading}
          placeholder={copy.auth.usernamePlaceholder}
          autoComplete="username"
          prefix={<UserOutlined />}
        />
      </Form.Item>
      <Form.Item label={copy.auth.password} htmlFor="password">
        <Input.Password
          id="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={loading}
          placeholder={copy.auth.passwordPlaceholder}
          autoComplete="current-password"
          prefix={<LockOutlined />}
        />
      </Form.Item>
      <Button className="login-submit" type="primary" htmlType="submit" loading={loading} disabled={loading} block autoInsertSpace={false}>
        {loading ? copy.auth.signingIn : copy.auth.signIn}
      </Button>
    </Form>
      <div className="login-card-foot">
        <span className="login-forgot">忘记密码？</span>
        <span className="login-version">V1.0</span>
      </div>
    </>
  );
}
