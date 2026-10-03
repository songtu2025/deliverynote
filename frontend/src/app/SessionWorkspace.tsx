import { useEffect, useState } from "react";
import { App as AntApp } from "antd";
import { api, AUTH_EXPIRED_EVENT, clearLegacyToken } from "../api";
import type { User } from "../types";
import LoginPage from "./LoginPage";
import Workspace, { WorkspacePageFallback } from "./Workspace";

const USER_KEY = "delivery-note-user";

function clearStoredUser(): void {
  try {
    localStorage.removeItem(USER_KEY);
  } catch {
    // 浏览器禁用存储时无需清理旧的非敏感用户缓存。
  }
}

export default function SessionWorkspace() {
  const { message } = AntApp.useApp();
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
  }, [message]);

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
      // 会话已失效时也要完成本地退出。
    }
    clearLegacyToken();
    clearStoredUser();
    setUser(null);
  };

  return checkingSession ? (
    <WorkspacePageFallback />
  ) : user ? (
    <Workspace user={user} onLogout={logout} />
  ) : (
    <LoginPage onLogin={setUser} />
  );
}
