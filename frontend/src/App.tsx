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
  Typography,
  message,
  theme
} from "antd";
import {
  ApartmentOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  UserOutlined
} from "@ant-design/icons";

import { api, AUTH_EXPIRED_EVENT, getToken, setToken } from "./api";
import AdminPage from "./pages/AdminPage";
import BatchDetail from "./pages/BatchDetail";
import BatchesPage from "./pages/BatchesPage";
import OverreceiptRulesPage from "./pages/OverreceiptRulesPage";
import type { User } from "./types";

const USER_KEY = "delivery-note-user";

type LoginResponse = { token: string; user: User };
type WorkspacePage = "batches" | "overreceipt" | "admin";
type WorkspaceRoute = {
  page: WorkspacePage;
  batchId: number | null;
};

function readWorkspaceRoute(): WorkspaceRoute {
  const pathname = window.location.pathname.replace(/\/+$/, "") || "/";
  const batchMatch = pathname.match(/^\/batches\/([1-9]\d*)$/);
  if (batchMatch) {
    return { page: "batches", batchId: Number(batchMatch[1]) };
  }
  if (pathname === "/overreceipt") {
    return { page: "overreceipt", batchId: null };
  }
  if (pathname === "/admin") {
    return { page: "admin", batchId: null };
  }
  return { page: "batches", batchId: null };
}

function workspacePath(route: WorkspaceRoute): string {
  if (route.batchId !== null) return `/batches/${route.batchId}`;
  if (route.page === "overreceipt") return "/overreceipt";
  if (route.page === "admin") return "/admin";
  return "/batches";
}

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
  const [route, setRoute] = useState<WorkspaceRoute>(() => readWorkspaceRoute());
  const { page, batchId } = route;
  const batchFocused = batchId !== null;
  const roleLabel = user.role === "admin" ? "管理员" : "操作员";
  const userInitial = user.username.trim().slice(0, 1).toUpperCase() || "U";

  const navigate = (nextRoute: WorkspaceRoute, replace = false) => {
    const path = workspacePath(nextRoute);
    if (window.location.pathname !== path) {
      window.history[replace ? "replaceState" : "pushState"]({}, "", path);
    }
    setRoute(nextRoute);
  };

  useEffect(() => {
    const handlePopState = () => setRoute(readWorkspaceRoute());
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (page === "admin" && user.role !== "admin") {
      navigate({ page: "batches", batchId: null }, true);
      return;
    }
    const canonicalPath = workspacePath(route);
    if (window.location.pathname !== canonicalPath) {
      window.history.replaceState({}, "", canonicalPath);
    }
  }, [page, route, user.role]);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [page, batchId]);

  const menuItems = [
    { key: "batches", icon: <ApartmentOutlined />, label: "批次处理" },
    { key: "overreceipt", icon: <SafetyCertificateOutlined />, label: "超收规则" },
    ...(user.role === "admin"
      ? [{ key: "admin", icon: <SettingOutlined />, label: "管理员维护" }]
      : [])
  ];

  return (
    <Layout className={`app-layout ${batchFocused ? "batch-focus-layout" : ""}`}>
      {!batchFocused && <Layout.Sider width={236} breakpoint="lg" collapsedWidth={72} theme="light">
        <div className="brand">
          <span className="brand-mark">DN</span>
          <span className="brand-name">交货处理</span>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[page]}
          items={menuItems}
          onClick={({ key }) => {
            navigate({
              page: key as WorkspacePage,
              batchId: null
            });
          }}
        />
      </Layout.Sider>}
      <Layout>
        <Layout.Header className="app-header">
          <div className="account-controls" role="group" aria-label="当前用户">
            <div className="account-identity">
              <span className="account-avatar" aria-hidden="true">{userInitial}</span>
              <span className="account-copy">
                <strong>{user.username}</strong>
                <small>{roleLabel}</small>
              </span>
            </div>
            <Button
              className="account-logout"
              aria-label="退出登录"
              icon={<LogoutOutlined />}
              onClick={onLogout}
            >
              退出
            </Button>
          </div>
        </Layout.Header>
        <Layout.Content className="app-content">
          {batchId !== null ? (
            <BatchDetail
              batchId={batchId}
              onBack={() => navigate({ page: "batches", batchId: null })}
            />
          ) : page === "admin" && user.role === "admin" ? (
            <AdminPage currentUser={user} />
          ) : page === "overreceipt" ? (
            <OverreceiptRulesPage />
          ) : (
            <BatchesPage
              onOpen={(id) => navigate({ page: "batches", batchId: id })}
            />
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
