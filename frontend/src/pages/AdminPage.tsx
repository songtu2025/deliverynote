import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Tabs, Typography } from "antd";

import { api } from "../api";
import type { AuditLog, InputVersion, User } from "../types";
import { AuditLogPanel } from "./admin/AuditLogPanel";
import { InputDataPanel } from "./admin/InputDataPanel";
import { PositionMaintenance } from "./admin/PositionMaintenance";
import { UserManagementPanel } from "./admin/UserManagementPanel";

type AdminPageProps = { currentUser: User };
type InputView = "catalog" | "position";

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

export default function AdminPage({ currentUser }: AdminPageProps) {
  const [users, setUsers] = useState<User[]>([]);
  const [versions, setVersions] = useState<InputVersion[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState<LoadingState>(INITIAL_LOADING);
  const [errors, setErrors] = useState<LoadErrors>(EMPTY_ERRORS);
  const [inputView, setInputView] = useState<InputView>("catalog");
  const inputWorkspaceRef = useRef<HTMLDivElement>(null);
  const focusInputViewRef = useRef(false);
  const mountedRef = useRef(false);
  const usersRequestRef = useRef(0);
  const versionsRequestRef = useRef(0);
  const auditRequestRef = useRef(0);

  const load = useCallback(async () => {
    const usersRequestId = ++usersRequestRef.current;
    const versionsRequestId = ++versionsRequestRef.current;
    const auditRequestId = ++auditRequestRef.current;
    if (!mountedRef.current) return;

    setLoading(INITIAL_LOADING);
    setErrors(EMPTY_ERRORS);
    const [userResult, versionResult, auditResult] = await Promise.allSettled([
      api<User[]>("/api/users"),
      api<InputVersion[]>("/api/input-versions"),
      api<AuditLog[]>("/api/audit-logs")
    ]);

    if (mountedRef.current && usersRequestRef.current === usersRequestId) {
      if (userResult.status === "fulfilled") setUsers(userResult.value);
      else {
        setErrors((current) => ({
          ...current,
          users: errorMessage(userResult.reason, "读取用户账号失败")
        }));
      }
      setLoading((current) => ({ ...current, users: false }));
    }

    if (mountedRef.current && versionsRequestRef.current === versionsRequestId) {
      if (versionResult.status === "fulfilled") setVersions(versionResult.value);
      else {
        setErrors((current) => ({
          ...current,
          versions: errorMessage(versionResult.reason, "读取基础资料失败")
        }));
      }
      setLoading((current) => ({ ...current, versions: false }));
    }

    if (mountedRef.current && auditRequestRef.current === auditRequestId) {
      if (auditResult.status === "fulfilled") setAuditLogs(auditResult.value);
      else {
        setErrors((current) => ({
          ...current,
          audit: errorMessage(auditResult.reason, "读取操作记录失败")
        }));
      }
      setLoading((current) => ({ ...current, audit: false }));
    }
  }, []);

  const refreshVersions = useCallback(async () => {
    const requestId = ++versionsRequestRef.current;
    if (!mountedRef.current) return;

    setLoading((current) => ({ ...current, versions: true }));
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
        setLoading((current) => ({ ...current, versions: false }));
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void load();
    return () => {
      mountedRef.current = false;
      usersRequestRef.current += 1;
      versionsRequestRef.current += 1;
      auditRequestRef.current += 1;
    };
  }, [load]);

  useEffect(() => {
    if (!focusInputViewRef.current) return undefined;
    focusInputViewRef.current = false;
    const timer = window.setTimeout(() => {
      const selector = inputView === "position"
        ? 'button[aria-label="返回基础资料"]'
        : '[data-input-catalog-heading="true"]';
      inputWorkspaceRef.current?.querySelector<HTMLElement>(selector)?.focus();
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

  return (
    <div className="page-shell admin-maintenance-pc">
      <div className="page-heading admin-maintenance-heading">
        <div>
          <Typography.Title level={2}>管理员维护</Typography.Title>
          <Typography.Text type="secondary">确保五类输入资料可用，并维护内部账号与操作记录。</Typography.Text>
        </div>
      </div>

      <Tabs
        className="admin-maintenance-tabs"
        animated={false}
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
                        <Typography.Text type="secondary">选择资料类型，查看当前版本、内容预览和历史记录。</Typography.Text>
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
                    <PositionMaintenance
                      activeVersion={activePositionVersion}
                      onPublished={() => void handlePublished()}
                      onBack={returnToCatalog}
                    />
                  </div>
                ) : null}
              </div>
            )
          },
          {
            key: "users",
            label: "用户账号",
            children: (
              <UserManagementPanel
                currentUser={currentUser}
                users={users}
                loading={loading.users}
                error={errors.users}
                onDataChanged={load}
              />
            )
          },
          {
            key: "audit",
            label: "操作记录",
            children: (
              <AuditLogPanel
                auditLogs={auditLogs}
                users={users}
                loading={loading.audit}
                error={errors.audit}
                onRetry={load}
              />
            )
          }
        ]}
      />
    </div>
  );
}
