import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Skeleton, Tabs, Typography } from "antd";

import { api } from "../api";
import type { AuditLog, InputVersion, User } from "../types";
import { InputDataPanel } from "./admin/InputDataPanel";

const AuditLogPanel = lazy(() => import("./admin/AuditLogPanel").then((module) => ({
  default: module.AuditLogPanel
})));
const IntegrationConfigPanel = lazy(() => import("./admin/IntegrationConfigPanel").then((module) => ({
  default: module.IntegrationConfigPanel
})));
const PositionMaintenance = lazy(() => import("./admin/PositionMaintenance").then((module) => ({
  default: module.PositionMaintenance
})));
const UserManagementPanel = lazy(() => import("./admin/UserManagementPanel").then((module) => ({
  default: module.UserManagementPanel
})));

type AdminPageProps = { currentUser: User; active?: boolean };
type InputView = "catalog" | "position";
type AdminTab = "inputs" | "integrations" | "users" | "audit";

interface LoadErrors {
  users: string | null;
  versions: string | null;
  audit: string | null;
}

interface LoadingState {
  users: boolean;
  versions: boolean;
  audit: boolean;
}

const EMPTY_ERRORS: LoadErrors = { users: null, versions: null, audit: null };
const INITIAL_LOADING: LoadingState = { users: true, versions: true, audit: true };

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function AdminPanelFallback() {
  return (
    <div aria-busy="true" aria-label="正在加载维护模块">
      <Skeleton active title={false} paragraph={{ rows: 5 }} />
    </div>
  );
}

export default function AdminPage({ currentUser, active = true }: AdminPageProps) {
  const [users, setUsers] = useState<User[]>([]);
  const [versions, setVersions] = useState<InputVersion[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState<LoadingState>(INITIAL_LOADING);
  const [errors, setErrors] = useState<LoadErrors>(EMPTY_ERRORS);
  const [inputView, setInputView] = useState<InputView>("catalog");
  const [activeTab, setActiveTab] = useState<AdminTab>("inputs");
  const inputWorkspaceRef = useRef<HTMLDivElement>(null);
  const focusInputViewRef = useRef(false);
  const mountedRef = useRef(false);
  const usersRequestRef = useRef(0);
  const versionsRequestRef = useRef(0);
  const auditRequestRef = useRef(0);
  const usersLoadedRef = useRef(false);
  const versionsLoadedRef = useRef(false);
  const auditLoadedRef = useRef(false);

  const loadUsers = useCallback(async (background = false) => {
    const requestId = ++usersRequestRef.current;
    if (!mountedRef.current) return;

    if (!background) setLoading((current) => ({ ...current, users: true }));
    setErrors((current) => ({ ...current, users: null }));
    try {
      const nextUsers = await api<User[]>("/api/users");
      if (mountedRef.current && usersRequestRef.current === requestId) {
        setUsers(nextUsers);
      }
    } catch (error) {
      if (mountedRef.current && usersRequestRef.current === requestId) {
        setErrors((current) => ({
          ...current,
          users: errorMessage(error, "读取用户账号失败")
        }));
      }
    } finally {
      if (mountedRef.current && usersRequestRef.current === requestId) {
        usersLoadedRef.current = true;
        setLoading((current) => ({ ...current, users: false }));
      }
    }
  }, []);

  const loadVersions = useCallback(async (background = false) => {
    const requestId = ++versionsRequestRef.current;
    if (!mountedRef.current) return;

    if (!background) setLoading((current) => ({ ...current, versions: true }));
    setErrors((current) => ({ ...current, versions: null }));
    try {
      const nextVersions = await api<InputVersion[]>("/api/input-versions");
      if (mountedRef.current && versionsRequestRef.current === requestId) {
        setVersions(nextVersions);
      }
    } catch (error) {
      if (mountedRef.current && versionsRequestRef.current === requestId) {
        setErrors((current) => ({
          ...current,
          versions: errorMessage(error, "读取基础资料失败")
        }));
      }
    } finally {
      if (mountedRef.current && versionsRequestRef.current === requestId) {
        versionsLoadedRef.current = true;
        setLoading((current) => ({ ...current, versions: false }));
      }
    }
  }, []);

  const loadAudit = useCallback(async (background = false) => {
    const requestId = ++auditRequestRef.current;
    if (!mountedRef.current) return;

    if (!background) setLoading((current) => ({ ...current, audit: true }));
    setErrors((current) => ({ ...current, audit: null }));
    try {
      const nextAuditLogs = await api<AuditLog[]>("/api/audit-logs");
      if (mountedRef.current && auditRequestRef.current === requestId) {
        setAuditLogs(nextAuditLogs);
      }
    } catch (error) {
      if (mountedRef.current && auditRequestRef.current === requestId) {
        setErrors((current) => ({
          ...current,
          audit: errorMessage(error, "读取操作记录失败")
        }));
      }
    } finally {
      if (mountedRef.current && auditRequestRef.current === requestId) {
        auditLoadedRef.current = true;
        setLoading((current) => ({ ...current, audit: false }));
      }
    }
  }, []);

  const refreshVersions = useCallback(() => loadVersions(false), [loadVersions]);

  const retryAudit = useCallback(async () => {
    await Promise.all([loadUsers(true), loadAudit(false)]);
  }, [loadAudit, loadUsers]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      usersRequestRef.current += 1;
      versionsRequestRef.current += 1;
      auditRequestRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (!versionsLoadedRef.current || active) {
      void loadVersions(versionsLoadedRef.current);
    }
  }, [active, loadVersions]);

  useEffect(() => {
    if (!active) return;
    if (activeTab === "users" && !usersLoadedRef.current) {
      void loadUsers();
    }
    if (activeTab === "audit") {
      if (!usersLoadedRef.current) void loadUsers();
      if (!auditLoadedRef.current) void loadAudit();
    }
  }, [active, activeTab, loadAudit, loadUsers]);

  useEffect(() => {
    if (!focusInputViewRef.current || inputView !== "catalog") return undefined;
    focusInputViewRef.current = false;
    const timer = window.setTimeout(() => {
      inputWorkspaceRef.current
        ?.querySelector<HTMLElement>('[data-input-catalog-heading="true"]')
        ?.focus();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [inputView]);

  const activePositionVersion = useMemo(
    () => versions.find((version) => version.kind === "position" && version.active) ?? null,
    [versions]
  );

  const openPosition = () => {
    focusInputViewRef.current = true;
    setInputView("position");
  };

  const returnToCatalog = () => {
    focusInputViewRef.current = true;
    setInputView("catalog");
  };

  const handlePublished = async () => {
    await refreshVersions();
    returnToCatalog();
  };

  if (!versionsLoadedRef.current) {
    return (
      <div
        className="page-shell admin-maintenance-pc"
        aria-busy="true"
        aria-label="正在加载管理员维护"
      >
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
            children: (
              <div className="input-workspace" ref={inputWorkspaceRef}>
                {inputView === "catalog" ? (
                  <div className="input-data-view">
                    <div className="admin-section-heading">
                      <div>
                        <Typography.Title data-input-catalog-heading="true" tabIndex={-1} level={4}>基础资料目录</Typography.Title>
                      </div>
                    </div>
                    {errors.versions && (
                      <Alert
                        className="inline-alert"
                        type="error"
                        showIcon
                        title="无法读取基础资料"
                        description={errors.versions}
                        action={<Button size="small" onClick={() => void refreshVersions()}>重新加载</Button>}
                      />
                    )}
                    <div className="input-data-layout">
                      <InputDataPanel
                        versions={versions}
                        loading={loading.versions}
                        onVersionsChanged={refreshVersions}
                        onOpenPositionDraft={openPosition}
                      />
                    </div>
                  </div>
                ) : activePositionVersion ? (
                  <div className="position-workspace">
                    <Suspense fallback={<AdminPanelFallback />}>
                      <PositionMaintenance
                        activeVersion={activePositionVersion}
                        onPublished={() => void handlePublished()}
                        onBack={returnToCatalog}
                      />
                    </Suspense>
                  </div>
                ) : null}
              </div>
            )
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
                <UserManagementPanel
                  currentUser={currentUser}
                  users={users}
                  loading={loading.users}
                  error={errors.users}
                  onDataChanged={() => loadUsers(true)}
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
