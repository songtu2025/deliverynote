import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Button, Layout, Menu, Skeleton } from "antd";
import {
  ApartmentOutlined,
  InboxOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  SettingOutlined
} from "@ant-design/icons";
import type { User } from "../types";
import { readWorkspaceRoute, workspacePath } from "./workspaceRoutes";
import type { WorkspacePage, WorkspaceRoute } from "./workspaceRoutes";

const loadAdminPage = () => import("../pages/AdminPage");

const loadBatchDetail = () => import("../pages/BatchDetail");

const loadBatchesPage = () => import("../pages/BatchesPage");

const loadOverreceiptRulesPage = () => import("../pages/OverreceiptRulesPage");

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

export function WorkspacePageFallback() {
  return (
    <div className="page-shell" aria-busy="true" aria-label="正在加载页面">
      <Skeleton active title={{ width: 220 }} paragraph={{ rows: 8 }} />
    </div>
  );
}

function WorkspacePages({
  user,
  route,
  visitedPages,
  navigate
}: {
  user: User;
  route: WorkspaceRoute;
  visitedPages: ReadonlySet<WorkspacePage>;
  navigate: (route: WorkspaceRoute) => void;
}) {
  const { page, batchId } = route;
  const activePage = batchId === null ? page : null;
  return (
    <Suspense fallback={<WorkspacePageFallback />}>
      {batchId !== null && (
        <BatchDetail
          batchId={batchId}
          canRefreshSupplierVersion={user.role === "admin"}
          onBack={() => navigate({ page, batchId: null })}
        />
      )}
      {visitedPages.has("batches") && (
        <div hidden={activePage !== "batches"}>
          <BatchesPage
            active={activePage === "batches"}
            canActivatePurchaseSync={user.role === "admin"}
            canDeleteBatches={user.role === "admin"}
            onOpen={(id) => navigate({ page: "batches", batchId: id })}
          />
        </div>
      )}
      {visitedPages.has("self-operated") && (
        <div hidden={activePage !== "self-operated"}>
          <BatchesPage
            active={activePage === "self-operated"}
            workflow="self_operated_inbound"
            canDeleteBatches={user.role === "admin"}
            onOpen={(id) => navigate({ page: "self-operated", batchId: id })}
          />
        </div>
      )}
      {visitedPages.has("overreceipt") && (
        <div hidden={activePage !== "overreceipt"}>
          <OverreceiptRulesPage active={activePage === "overreceipt"} />
        </div>
      )}
      {visitedPages.has("admin") && user.role === "admin" && (
        <div hidden={activePage !== "admin"}>
          <AdminPage currentUser={user} active={activePage === "admin"} />
        </div>
      )}
    </Suspense>
  );
}

export default function Workspace({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [route, setRoute] = useState<WorkspaceRoute>(() => readWorkspaceRoute(window.location.pathname));
  const { page, batchId } = route;
  const [visitedPages, setVisitedPages] = useState<Set<WorkspacePage>>(() => new Set([page]));
  const batchFocused = batchId !== null;
  const roleLabel = user.role === "admin" ? "管理员" : "操作员";
  const userInitial = user.username.trim().slice(0, 1).toUpperCase() || "U";

  const applyRoute = useCallback((nextRoute: WorkspaceRoute) => {
    setVisitedPages((current) => (current.has(nextRoute.page) ? current : new Set([...current, nextRoute.page])));
    setRoute(nextRoute);
  }, []);

  const navigate = useCallback(
    (nextRoute: WorkspaceRoute, replace = false) => {
      preloadWorkspaceRoute(nextRoute);
      const path = workspacePath(nextRoute);
      if (window.location.pathname !== path) {
        window.history[replace ? "replaceState" : "pushState"]({}, "", path);
      }
      applyRoute(nextRoute);
    },
    [applyRoute]
  );

  useEffect(() => {
    const handlePopState = () => applyRoute(readWorkspaceRoute(window.location.pathname));
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [applyRoute]);

  useEffect(() => {
    if (page === "admin" && user.role !== "admin") {
      navigate({ page: "batches", batchId: null }, true);
      return;
    }
    const canonicalPath = workspacePath(route);
    if (window.location.pathname !== canonicalPath) {
      window.history.replaceState({}, "", canonicalPath);
    }
  }, [navigate, page, route, user.role]);

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
      {!batchFocused && (
        <Layout.Sider width={236} breakpoint="lg" collapsedWidth={72} theme="light">
          <div className="brand">
            <span className="brand-mark">DN</span>
            <span className="brand-name">
              单据处理
              <small>DeliveryNote</small>
            </span>
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
          <div className="sidebar-caption">供应链工作台</div>
        </Layout.Sider>
      )}
      <Layout>
        <Layout.Header className="app-header">
          <span className="workspace-context">
            DeliveryNote <span>/</span> 供应链工作台
          </span>
          <div className="account-controls" role="group" aria-label="当前用户">
            <div className="account-identity">
              <span className="account-avatar" aria-hidden="true">
                {userInitial}
              </span>
              <span className="account-copy">
                <strong>{user.username}</strong>
                <small>{roleLabel}</small>
              </span>
            </div>
            <Button className="account-logout" aria-label="退出登录" icon={<LogoutOutlined />} onClick={onLogout}>
              退出
            </Button>
          </div>
        </Layout.Header>
        <Layout.Content className="app-content">
          <WorkspacePages user={user} route={route} visitedPages={visitedPages} navigate={navigate} />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
