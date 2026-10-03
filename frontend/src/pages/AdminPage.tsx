import { lazy, Suspense, useState } from "react";
import { Button, Skeleton, Tabs, Typography } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import type { User } from "../types";
import { AdminInputWorkspace } from "./admin/AdminInputWorkspace";
import { AdminPanelFallback } from "./admin/AdminPanelFallback";
import { useAdminData } from "./admin/useAdminData";
import type { AdminTab } from "./admin/useAdminData";

const AuditLogPanel = lazy(() =>
  import("./admin/AuditLogPanel").then((module) => ({
    default: module.AuditLogPanel
  }))
);
const IntegrationConfigPanel = lazy(() =>
  import("./admin/IntegrationConfigPanel").then((module) => ({
    default: module.IntegrationConfigPanel
  }))
);
const UserManagementPanel = lazy(() =>
  import("./admin/UserManagementPanel").then((module) => ({
    default: module.UserManagementPanel
  }))
);

type AdminPageProps = { currentUser: User; active?: boolean };

export default function AdminPage({ currentUser, active = true }: AdminPageProps) {
  const [activeTab, setActiveTab] = useState<AdminTab>("inputs");
  const data = useAdminData(active, activeTab);
  const { users, auditLogs, loading, errors, loadUsers, retryAudit } = data;
  if (!data.initialized) {
    return (
      <div className="page-shell admin-maintenance-pc" aria-busy="true" aria-label="正在加载管理员维护">
        <Skeleton active title={{ width: 220 }} paragraph={{ rows: 8 }} />
      </div>
    );
  }
  return (
    <div className="page-shell admin-maintenance-pc">
      <div className="page-heading admin-maintenance-heading">
        <div>
          <Typography.Title level={2}>管理员维护</Typography.Title>
        </div>
      </div>

      <Tabs
        className="admin-maintenance-tabs"
        animated={false}
        activeKey={activeTab}
        onChange={(key) => setActiveTab(key as AdminTab)}
        items={[
          {
            key: "inputs",
            label: "基础资料",
            children: <AdminInputWorkspace data={data} />
          },
          {
            key: "integrations",
            label: "接口配置",
            children: (
              <Suspense fallback={<AdminPanelFallback />}>
                <IntegrationConfigPanel />
              </Suspense>
            )
          },
          {
            key: "users",
            label: "用户账号",
            children: (
              <Suspense fallback={<AdminPanelFallback />}>
                {errors.users && (
                  <Button icon={<ReloadOutlined />} loading={loading.users} onClick={() => void loadUsers()}>
                    重新加载用户账号
                  </Button>
                )}
                <UserManagementPanel
                  currentUser={currentUser}
                  users={users}
                  loading={loading.users}
                  error={errors.users}
                  onDataChanged={() => loadUsers(true, true)}
                />
              </Suspense>
            )
          },
          {
            key: "audit",
            label: "操作记录",
            children: (
              <Suspense fallback={<AdminPanelFallback />}>
                <AuditLogPanel
                  auditLogs={auditLogs}
                  users={users}
                  loading={loading.audit}
                  error={errors.audit}
                  onRetry={retryAudit}
                />
              </Suspense>
            )
          }
        ]}
      />
    </div>
  );
}
