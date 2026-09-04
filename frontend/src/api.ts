const LEGACY_TOKEN_KEY = "delivery-note-token";
const API_BASE = import.meta.env.VITE_API_BASE ?? "";
export const AUTH_EXPIRED_EVENT = "delivery-note-auth-expired";
let authExpirationReported = false;

type ApiOptions = {
  notifyUnauthorized?: boolean;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function clearLegacyToken(): void {
  try {
    localStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch {
    // 浏览器禁用本地存储时，会话 Cookie 仍可正常工作。
  }
  try {
    sessionStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch {
    // 浏览器禁用会话存储时，会话 Cookie 仍可正常工作。
  }
}

export function expireSession(message = "登录已过期，请重新登录"): void {
  clearLegacyToken();
  if (authExpirationReported) return;
  authExpirationReported = true;
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, { detail: { message } }));
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
  options: ApiOptions = {}
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include"
  });
  if (!response.ok) {
    if (response.status === 401 && options.notifyUnauthorized !== false) {
      expireSession();
    }
    let message = `请求失败（${response.status}）`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") {
        message = payload.detail;
      }
    } catch {
      // Keep the status-based message when the body is not JSON.
    }
    throw new ApiError(response.status, message);
  }
  if (path === "/api/auth/login" || path === "/api/auth/me") {
    authExpirationReported = false;
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function download(path: string, filename: string): Promise<void> {
  const headers = new Headers();
  const response = await fetch(`${API_BASE}${path}`, {
    headers,
    credentials: "include"
  });
  if (!response.ok) {
    if (response.status === 401) {
      expireSession();
    }
    throw new ApiError(response.status, "下载失败");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
