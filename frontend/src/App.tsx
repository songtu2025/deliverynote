import { useEffect, useState } from "react";
import {
  App as AntApp,
  Button,
  Card,
  ConfigProvider,
  Form,
  Input,
  Layout,
  Menu,
  Space,
  Typography,
  message,
  theme
} from "antd";
import {
  ApartmentOutlined,
  LogoutOutlined,
  SettingOutlined,
  UserOutlined
} from "@ant-design/icons";

import { api, AUTH_EXPIRED_EVENT, getToken, setToken } from "./api";
import AdminPage from "./pages/AdminPage";
import BatchDetail from "./pages/BatchDetail";
import BatchesPage from "./pages/BatchesPage";
import type { User } from "./types";

const USER_KEY = "delivery-note-user";

type LoginResponse = { token: string; user: User };

function readStoredUser(): User | null {
  if (!getToken()) {
    localStorage.removeItem(USER_KEY);
    return null;
  }
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    localStorage.removeItem(USER_KEY);
    return null;
  }
}

function LoginPage({ onLogin }: { onLogin: (user: User) => void }) {
  const [submitting, setSubmitting] = useState(false);

  const submit = async (values: { username: string; password: string }) => {
    setSubmitting(true);
    try {
      const result = await api<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(values)
      });
      setToken(result.token);
      localStorage.setItem(USER_KEY, JSON.stringify(result.user));
      onLogin(result.user);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-shell">
      <Card className="login-card" variant="borderless">
        <div className="login-mark">DN</div>
        <Typography.Title level={2}>供应链交货处理</Typography.Title>
        <Typography.Paragraph type="secondary">
          上传、计算、审阅、拆分与导出
        </Typography.Paragraph>
        <Form layout="vertical" onFinish={submit} requiredMark={false}>
          <Form.Item label="用户名" name="username" rules={[{ required: true }]}>
            <Input size="large" prefix={<UserOutlined />} autoComplete="username" />
          </Form.Item>
          <Form.Item label="密码" name="password" rules={[{ required: true }]}>
            <Input.Password size="large" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" size="large" block loading={submitting}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  );
}

function Workspace({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [page, setPage] = useState<"batches" | "admin">("batches");
  const [batchId, setBatchId] = useState<number | null>(null);
  const menuItems = [
    { key: "batches", icon: <ApartmentOutlined />, label: "批次处理" },
    ...(user.role === "admin"
      ? [{ key: "admin", icon: <SettingOutlined />, label: "管理员维护" }]
      : [])
  ];

  return (
    <Layout className="app-layout">
      <Layout.Sider width={236} breakpoint="lg" collapsedWidth={72} theme="light">
        <div className="brand">
          <span className="brand-mark">DN</span>
          <span className="brand-name">交货处理</span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[page]}
          items={menuItems}
          onClick={({ key }) => {
            setPage(key as "batches" | "admin");
            setBatchId(null);
          }}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Header className="app-header">
          <Space>
            <span className="user-chip">{user.username} · {user.role === "admin" ? "管理员" : "操作员"}</span>
            <Button type="text" icon={<LogoutOutlined />} onClick={onLogout}>
              退出
            </Button>
          </Space>
        </Layout.Header>
        <Layout.Content className="app-content">
          {batchId !== null ? (
            <BatchDetail batchId={batchId} onBack={() => setBatchId(null)} />
          ) : page === "admin" && user.role === "admin" ? (
            <AdminPage currentUser={user} />
          ) : (
            <BatchesPage onOpen={setBatchId} />
          )}
        </Layout.Content>
      </Layout>
    </Layout>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(() => readStoredUser());

  useEffect(() => {
    const handleExpired = (event: Event) => {
      localStorage.removeItem(USER_KEY);
      setUser(null);
      const detail = (event as CustomEvent<{ message?: string }>).detail;
      message.warning(detail?.message ?? "登录已过期，请重新登录");
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, handleExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleExpired);
  }, []);

  const logout = async () => {
    try {
      await api<void>("/api/auth/logout", { method: "POST" });
    } catch {
      // Local logout must still work if the session already expired.
    }
    setToken(null);
    localStorage.removeItem(USER_KEY);
    setUser(null);
  };

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#176b5b",
          borderRadius: 8,
          fontFamily: "Inter, Microsoft YaHei, sans-serif"
        }
      }}
    >
      <AntApp>
        {user ? <Workspace user={user} onLogout={logout} /> : <LoginPage onLogin={setUser} />}
      </AntApp>
    </ConfigProvider>
  );
}
