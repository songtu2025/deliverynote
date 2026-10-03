import { useState } from "react";
import { App as AntApp, Button, Form, Input } from "antd";
import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { api } from "../api";
import type { User } from "../types";

type LoginResponse = { user: User };

export default function LoginPage({ onLogin }: { onLogin: (user: User) => void }) {
  const { message } = AntApp.useApp();
  const [submitting, setSubmitting] = useState(false);

  const submit = async (values: { username: string; password: string }) => {
    setSubmitting(true);
    try {
      const result = await api<LoginResponse>(
        "/api/auth/login",
        {
          method: "POST",
          body: JSON.stringify(values)
        },
        { notifyUnauthorized: false }
      );
      onLogin(result.user);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-shell">
      <aside className="login-story" aria-label="DeliveryNote 产品介绍">
        <div className="login-brand-lockup">
          <span className="login-company-mark">SEEKWAY</span>
          <span className="login-brand-divider" aria-hidden="true" />
          <span className="login-product-name">DeliveryNote</span>
        </div>

        <div className="login-story-copy">
          <h1>
            让每一份交货数据，
            <br />
            清晰抵达下一站
          </h1>
          <p>
            从供应商交货单到标准导入表，
            <br />
            集中处理、清晰审校、完整追溯。
          </p>
        </div>

        <img className="login-story-illustration" src="/login-document-flow.svg" alt="" aria-hidden="true" />
      </aside>

      <main className="login-panel">
        <div className="login-form-wrap">
          <header className="login-form-header">
            <h2>欢迎回来</h2>
            <p>请使用系统账号登录</p>
          </header>

          <Form className="login-form" layout="vertical" onFinish={submit} requiredMark={false}>
            <Form.Item label="用户名" name="username" rules={[{ required: true, message: "请输入用户名" }]}>
              <Input size="large" prefix={<UserOutlined />} placeholder="请输入用户名" autoComplete="username" />
            </Form.Item>
            <Form.Item label="密码" name="password" rules={[{ required: true, message: "请输入密码" }]}>
              <Input.Password
                size="large"
                prefix={<LockOutlined />}
                placeholder="请输入密码"
                autoComplete="current-password"
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" size="large" block loading={submitting} autoInsertSpace={false}>
              登录
            </Button>
          </Form>
        </div>

        <footer className="login-footer">DeliveryNote · 内部供应链单据处理系统</footer>
      </main>
    </div>
  );
}
