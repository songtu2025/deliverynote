import { lazy, Suspense, useEffect, useState } from "react";
import {
  App as AntApp,
  Button,
  ConfigProvider,
  Form,
  Input,
  Layout,
  Menu,
  Skeleton,
  Typography,
  message,
  theme
} from "antd";
import {
  ApartmentOutlined,
  InboxOutlined,
  LockOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  UserOutlined
} from "@ant-design/icons";

import { api, AUTH_EXPIRED_EVENT, clearLegacyToken } from "./api";
import type { User } from "./types";

const USER_KEY = "delivery-note-user";

type LoginResponse = { user: User };
type WorkspacePage = "batches" | "self-operated" | "overreceipt" | "admin";
type WorkspaceRoute = {
  page: WorkspacePage;
  batchId: number | null;
};

const loadAdminPage = () => import("./pages/AdminPage");
const loadBatchDetail = () => import("./pages/BatchDetail");
const loadBatchesPage = () => import("./pages/BatchesPage");
const loadOverreceiptRulesPage = () => import("./pages/OverreceiptRulesPage");

const AdminPage = lazy(loadAdminPage);
const BatchDetail = lazy(loadBatchDetail);
const BatchesPage = lazy(loadBatchesPage);
const OverreceiptRulesPage = lazy(loadOverreceiptRulesPage);

const WORKSPACE_LOADERS: Record<WorkspacePage, () => Promise<unknown>> = {
  batches: loadBatchesPage,
  "self-operated": loadBatchesPage,
  overreceipt: loadOverreceiptRulesPage,
  admin: loadAdminPage
};

function preloadWorkspaceRoute(route: WorkspaceRoute) {
  void (route.batchId === null ? WORKSPACE_LOADERS[route.page]() : loadBatchDetail());
}

function WorkspacePageFallback() {
  return (
    <div className="page-shell" aria-busy="true" aria-label="正在加载页面">
      <Skeleton active title={{ width: 220 }} paragraph={{ rows: 8 }} />
    </div>
  );
}

function readWorkspaceRoute(): WorkspaceRoute {
  const pathname = window.location.pathname.replace(/\/+$/, "") || "/";
  const batchMatch = pathname.match(/^\/batches\/([1-9]\d*)$/);
  if (batchMatch) {
    return { page: "batches", batchId: Number(batchMatch[1]) };
  }
  const selfOperatedBatchMatch = pathname.match(/^\/self-operated\/([1-9]\d*)$/);
  if (selfOperatedBatchMatch) {
    return { page: "self-operated", batchId: Number(selfOperatedBatchMatch[1]) };
  }
  if (pathname === "/self-operated") {
    return { page: "self-operated", batchId: null };
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
  if (route.batchId !== null) {
    return route.page === "self-operated"
      ? `/self-operated/${route.batchId}`
      : `/batches/${route.batchId}`;
  }
  if (route.page === "self-operated") return "/self-operated";
  if (route.page === "overreceipt") return "/overreceipt";
  if (route.page === "admin") return "/admin";
  return "/batches";
}

function clearStoredUser(): void {
  try {
    localStorage.removeItem(USER_KEY);
  } catch {
    // 浏览器禁用存储时无需清理旧的非敏感用户缓存。
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
      }, { notifyUnauthorized: false });
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

        <img
          className="login-story-illustration"
          src="/login-document-flow.svg"
          alt=""
          aria-hidden="true"
        />
      </aside>

      <main className="login-panel">
        <div className="login-form-wrap">
          <header className="login-form-header">
            <h2>欢迎回来</h2>
            <p>请使用系统账号登录</p>
          </header>

          <Form className="login-form" layout="vertical" onFinish={submit} requiredMark={false}>
            <Form.Item
              label="用户名"
              name="username"
              rules={[{ required: true, message: "请输入用户名" }]}
            >
              <Input
                size="large"
                prefix={<UserOutlined />}
                placeholder="请输入用户名"
                autoComplete="username"
              />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password
                size="large"
                prefix={<LockOutlined />}
                placeholder="请输入密码"
                autoComplete="current-password"
              />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              block
              loading={submitting}
              autoInsertSpace={false}
            >
              登录
            </Button>
          </Form>
        </div>

        <footer className="login-footer">DeliveryNote · 内部供应链单据处理系统</footer>
      </main>
    </div>
  );
}

function Workspace({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [route, setRoute] = useState<WorkspaceRoute>(() => readWorkspaceRoute());
  const { page, batchId } = route;
  const [visitedPages, setVisitedPages] = useState<Set<WorkspacePage>>(() => new Set([page]));
  const batchFocused = batchId !== null;
  const roleLabel = user.role === "admin" ? "管理员" : "操作员";
  const userInitial = user.username.trim().slice(0, 1).toUpperCase() || "U";

  const navigate = (nextRoute: WorkspaceRoute, replace = false) => {
    preloadWorkspaceRoute(nextRoute);
    const path = workspacePath(nextRoute);
    if (window.location.pathname !== path) {
      window.history[replace ? "replaceState" : "pushState"]({}, "", path);
    }
    setVisitedPages((current) => {
      if (current.has(nextRoute.page)) return current;
      const next = new Set(current);
      next.add(nextRoute.page);
      return next;
    });
    setRoute(nextRoute);
  };

  useEffect(() => {
    const handlePopState = () => {
      const nextRoute = readWorkspaceRoute();
      setVisitedPages((current) => {
        if (current.has(nextRoute.page)) return current;
        const next = new Set(current);
        next.add(nextRoute.page);
        return next;
      });
      setRoute(nextRoute);
    };
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

  const menuLabel = (targetPage: WorkspacePage, label: string) => (
    <span onMouseEnter={() => void WORKSPACE_LOADERS[targetPage]()}>{label}</span>
  );
  const menuItems = [
    { key: "batches", icon: <ApartmentOutlined />, label: menuLabel("batches", "交货批次") },
    { key: "self-operated", icon: <InboxOutlined />, label: menuLabel("self-operated", "自营仓入库") },
    { key: "overreceipt", icon: <SafetyCertificateOutlined />, label: menuLabel("overreceipt", "超收规则") },
    ...(user.role === "admin"
      ? [{ key: "admin", icon: <SettingOutlined />, label: menuLabel("admin", "管理员维护") }]
      : [])
  ];

  return (
    <Layout className={`app-layout ${batchFocused ? "batch-focus-layout" : ""}`}>
      {!batchFocused && <Layout.Sider width={236} breakpoint="lg" collapsedWidth={72} theme="light">
        <div className="brand">
          <span className="brand-mark">DN</span>
          <span className="brand-name">单据处理</span>
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
          <Suspense fallback={<WorkspacePageFallback />}>
            {batchId !== null && (
              <BatchDetail
                batchId={batchId}
                onBack={() => navigate({ page, batchId: null })}
              />
            )}
            {visitedPages.has("batches") && (
              <div hidden={batchId !== null || page !== "batches"}>
                <BatchesPage
                  active={batchId === null && page === "batches"}
                  canActivatePurchaseSync={user.role === "admin"}
                  canDeleteBatches={user.role === "admin"}
                  onOpen={(id) => navigate({ page: "batches", batchId: id })}
                />
              </div>
            )}
            {visitedPages.has("self-operated") && (
              <div hidden={batchId !== null || page !== "self-operated"}>
                <BatchesPage
                  active={batchId === null && page === "self-operated"}
                  workflow="self_operated_inbound"
                  canDeleteBatches={user.role === "admin"}
                  onOpen={(id) => navigate({ page: "self-operated", batchId: id })}
                />
              </div>
            )}
            {visitedPages.has("overreceipt") && (
              <div hidden={batchId !== null || page !== "overreceipt"}>
                <OverreceiptRulesPage active={batchId === null && page === "overreceipt"} />
              </div>
            )}
            {visitedPages.has("admin") && user.role === "admin" && (
              <div hidden={batchId !== null || page !== "admin"}>
                <AdminPage currentUser={user} active={batchId === null && page === "admin"} />
              </div>
            )}
          </Suspense>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    const handleExpired = (event: Event) => {
      clearStoredUser();
      setUser(null);
      const detail = (event as CustomEvent<{ message?: string }>).detail;
      message.warning(detail?.message ?? "登录已过期，请重新登录");
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, handleExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleExpired);
  }, []);

  useEffect(() => {
    let cancelled = false;
    clearLegacyToken();
    clearStoredUser();
    void api<User>("/api/auth/me", {}, { notifyUnauthorized: false })
      .then((currentUser) => {
        if (!cancelled) setUser(currentUser);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setCheckingSession(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const logout = async () => {
    try {
      await api<void>("/api/auth/logout", { method: "POST" });
    } catch {
      // Local logout must still work if the session already expired.
    }
    clearLegacyToken();
    clearStoredUser();
    setUser(null);
  };

  return (
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#055247",
          colorInfo: "#055247",
          colorText: "#141b18",
          colorTextSecondary: "#63736e",
          colorBgLayout: "#fbfcfb",
          colorBorder: "#dfe6e3",
          borderRadius: 8,
          fontFamily: "Inter, Microsoft YaHei, sans-serif"
        }
      }}
    >
      <AntApp>
        {checkingSession ? (
          <WorkspacePageFallback />
        ) : user ? (
          <Workspace user={user} onLogout={logout} />
        ) : (
          <LoginPage onLogin={setUser} />
        )}
      </AntApp>
    </ConfigProvider>
  );
}
