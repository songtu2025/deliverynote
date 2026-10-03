import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { api, ApiError } from "../../api";
import type { AuditLog, InputVersion, User } from "../../types";
import { errorMessage } from "./positionDraftApi";

export type AdminTab = "inputs" | "integrations" | "users" | "audit";

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

function handleReadUnauthorized(error: unknown, afterWrite: boolean): boolean {
  if (!(error instanceof ApiError && error.status === 401)) return false;
  if (afterWrite) throw error;
  return true;
}

export function useAdminData(active: boolean, activeTab: AdminTab) {
  const [users, setUsers] = useState<User[]>([]);

  const [versions, setVersions] = useState<InputVersion[]>([]);

  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);

  const [loading, setLoading] = useState<LoadingState>(INITIAL_LOADING);

  const [errors, setErrors] = useState<LoadErrors>(EMPTY_ERRORS);

  const mountedRef = useRef(false);

  const usersRequestRef = useRef(0);

  const versionsRequestRef = useRef(0);

  const auditRequestRef = useRef(0);

  const usersLoadedRef = useRef(false);

  const versionsLoadedRef = useRef(false);

  const auditLoadedRef = useRef(false);

  const isLatestRequest = useCallback(
    (requestRef: RefObject<number>, requestId: number) => mountedRef.current && requestRef.current === requestId,
    []
  );

  const loadUsers = useCallback(
    async (background = false, afterWrite = false) => {
      const requestId = ++usersRequestRef.current;
      if (!mountedRef.current) return false;

      if (!background) setLoading((current) => ({ ...current, users: true }));
      setErrors((current) => ({ ...current, users: null }));
      try {
        const nextUsers = await api<User[]>("/api/users");
        if (isLatestRequest(usersRequestRef, requestId)) {
          setUsers(nextUsers);
          return true;
        }
        return false;
      } catch (error) {
        if (handleReadUnauthorized(error, afterWrite)) return false;
        if (isLatestRequest(usersRequestRef, requestId)) {
          setErrors((current) => ({
            ...current,
            users: `${afterWrite ? "变更已保存，但读取用户账号失败：" : ""}${errorMessage(error, "读取用户账号失败")}`
          }));
        }
        return false;
      } finally {
        if (isLatestRequest(usersRequestRef, requestId)) {
          usersLoadedRef.current = true;
          setLoading((current) => ({ ...current, users: false }));
        }
      }
    },
    [isLatestRequest]
  );

  const loadVersions = useCallback(
    async (background = false, afterWrite = false, savedMessage?: string) => {
      const requestId = ++versionsRequestRef.current;
      if (!mountedRef.current) return false;

      if (!background) setLoading((current) => ({ ...current, versions: true }));
      setErrors((current) => ({ ...current, versions: null }));
      try {
        const nextVersions = await api<InputVersion[]>("/api/input-versions");
        if (isLatestRequest(versionsRequestRef, requestId)) {
          setVersions(nextVersions);
          return true;
        }
        return false;
      } catch (error) {
        if (handleReadUnauthorized(error, afterWrite)) return false;
        if (isLatestRequest(versionsRequestRef, requestId)) {
          setErrors((current) => ({
            ...current,
            versions: `${afterWrite ? (savedMessage ?? "变更已保存，但读取基础资料失败：") : ""}${errorMessage(error, "读取基础资料失败")}`
          }));
        }
        return false;
      } finally {
        if (isLatestRequest(versionsRequestRef, requestId)) {
          versionsLoadedRef.current = true;
          setLoading((current) => ({ ...current, versions: false }));
        }
      }
    },
    [isLatestRequest]
  );

  const loadAudit = useCallback(
    async (background = false) => {
      const requestId = ++auditRequestRef.current;
      if (!mountedRef.current) return;

      if (!background) setLoading((current) => ({ ...current, audit: true }));
      setErrors((current) => ({ ...current, audit: null }));
      try {
        const nextAuditLogs = await api<AuditLog[]>("/api/audit-logs");
        if (isLatestRequest(auditRequestRef, requestId)) {
          setAuditLogs(nextAuditLogs);
        }
      } catch (error) {
        if (handleReadUnauthorized(error, false)) return;
        if (isLatestRequest(auditRequestRef, requestId)) {
          setErrors((current) => ({
            ...current,
            audit: errorMessage(error, "读取操作记录失败")
          }));
        }
      } finally {
        if (isLatestRequest(auditRequestRef, requestId)) {
          auditLoadedRef.current = true;
          setLoading((current) => ({ ...current, audit: false }));
        }
      }
    },
    [isLatestRequest]
  );

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
  return {
    users,
    versions,
    auditLogs,
    loading,
    errors,
    initialized: versionsLoadedRef.current,
    loadUsers,
    loadVersions,
    refreshVersions,
    retryAudit
  };
}

export type AdminData = ReturnType<typeof useAdminData>;
